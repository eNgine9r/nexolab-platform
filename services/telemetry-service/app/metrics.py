from __future__ import annotations

from datetime import datetime
from typing import Any

PREFIX = "nexolab_telemetry_"

COUNTERS = {
    "received_total": "MQTT payloads received by the ingestion service.",
    "accepted_total": "Valid payloads accepted into the persistence queue.",
    "persisted_total": "Unique telemetry events committed to PostgreSQL.",
    "duplicate_total": "Duplicate telemetry events ignored by event_id.",
    "rejected_total": "Payloads rejected by size, decoding, JSON, or schema validation.",
    "queue_dropped_total": "Persistence work dropped because of queue or shutdown limits.",
    "dead_letter_queued_total": "Rejected payloads queued for dead-letter persistence.",
    "dead_letter_persisted_total": "Rejected payloads committed to the dead-letter table.",
    "dead_letter_dropped_total": "Rejected payloads that could not enter the bounded queue.",
    "persistence_failure_total": "Failed PostgreSQL persistence attempts.",
    "database_retry_total": "Persistence retries scheduled after database failures.",
    "database_recovery_total": "Observed database outage-to-ready transitions.",
    "retention_runs_total": "Completed retention cleanup runs.",
    "retention_failure_total": "Failed retention cleanup runs.",
    "retention_deleted_telemetry_total": "Telemetry rows deleted by retention.",
    "retention_redacted_raw_payload_total": "Raw payloads redacted by retention.",
    "retention_deleted_dead_letter_total": "Dead-letter rows deleted by retention.",
    "websocket_connect_total": "Accepted WebSocket client connections.",
    "websocket_disconnect_total": "Closed WebSocket client connections.",
    "websocket_broadcast_total": "Telemetry messages queued for WebSocket clients.",
    "websocket_filtered_total": "Telemetry messages excluded by client filters.",
    "websocket_slow_consumer_total": "WebSocket clients isolated as slow consumers.",
    "websocket_send_timeout_total": "WebSocket sends that exceeded their timeout.",
    "websocket_heartbeat_total": "Heartbeat messages sent to WebSocket clients.",
    "websocket_resume_total": "Persisted telemetry messages replayed after reconnect.",
    "websocket_publish_error_total": "Persist-first live-hub publish callback failures.",
}

GAUGES = {
    "mqtt_connected": "Whether the MQTT subscription is active after SUBACK.",
    "database_ready": "Whether PostgreSQL is currently reachable.",
    "queue_size": "Persistence queue items including the active retry item.",
    "websocket_clients": "Currently connected WebSocket clients.",
    "ingestion_lag_seconds": "Lag from event capture to successful persistence.",
}


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _sample(lines: list[str], name: str, value: int | float | bool) -> None:
    numeric = int(value) if isinstance(value, bool) else value
    lines.append(f"{PREFIX}{name} {numeric}")


def render_prometheus(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []

    for field, help_text in COUNTERS.items():
        name = f"{PREFIX}{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        _sample(lines, field, snapshot.get(field, 0))

    for field, help_text in GAUGES.items():
        value = snapshot.get(field)
        if value is None:
            continue
        name = f"{PREFIX}{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        _sample(lines, field, value)

    outage = 1 if snapshot.get("database_outage_since") else 0
    lines.extend(
        [
            f"# HELP {PREFIX}database_outage Whether a database outage is active.",
            f"# TYPE {PREFIX}database_outage gauge",
            f"{PREFIX}database_outage {outage}",
        ]
    )

    timestamp_metrics = {
        "last_persisted_timestamp_seconds": snapshot.get("last_persisted_at"),
        "last_event_captured_timestamp_seconds": snapshot.get(
            "last_event_captured_at"
        ),
        "database_outage_since_timestamp_seconds": snapshot.get(
            "database_outage_since"
        ),
        "last_database_recovery_timestamp_seconds": snapshot.get(
            "last_database_recovery_at"
        ),
    }
    for field, value in timestamp_metrics.items():
        parsed = _timestamp(value)
        if parsed is None:
            continue
        name = f"{PREFIX}{field}"
        lines.append(f"# HELP {name} Unix timestamp for {field}.")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {parsed}")

    reason_counts = snapshot.get("dead_letter_by_reason", {})
    if isinstance(reason_counts, dict):
        name = f"{PREFIX}dead_letter_reason_total"
        lines.append(
            f"# HELP {name} Persisted dead-letter payloads grouped by reason code."
        )
        lines.append(f"# TYPE {name} counter")
        for reason_code in sorted(reason_counts):
            value = reason_counts[reason_code]
            escaped = _escape_label(str(reason_code))
            lines.append(f'{name}{{reason_code="{escaped}"}} {value}')

    return "\n".join(lines) + "\n"
