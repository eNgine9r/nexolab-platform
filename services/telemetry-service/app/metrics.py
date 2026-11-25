from __future__ import annotations

import os
from datetime import datetime
from typing import Any

PREFIX = "nexolab_telemetry_"

COUNTERS = {
    "received_total": "MQTT payloads received by the ingestion service.",
    "accepted_total": "Valid payloads accepted into the persistence pipeline.",
    "persisted_total": "Unique telemetry events committed to PostgreSQL.",
    "duplicate_total": "Duplicate telemetry events ignored by event_id.",
    "rejected_total": "Payloads rejected by size, decoding, JSON, or schema validation.",
    "queue_dropped_total": "Legacy in-memory persistence work dropped by queue or shutdown limits.",
    "dead_letter_queued_total": "Rejected payloads accepted for dead-letter persistence.",
    "dead_letter_persisted_total": "Rejected payloads committed to the dead-letter table.",
    "dead_letter_dropped_total": "Rejected payloads that could not enter the legacy queue.",
    "persistence_failure_total": "Failed PostgreSQL persistence attempts.",
    "database_retry_total": "Persistence retries scheduled after database failures.",
    "post_persist_retry_total": "Retries after committed telemetry downstream processing failures.",
    "database_recovery_total": "Observed database outage-to-ready transitions.",
    "spool_staged_total": "New records committed to the durable local ingestion spool.",
    "spool_duplicate_total": "MQTT deliveries deduplicated by event or delivery key in the spool.",
    "spool_recovered_total": "Pending durable records discovered when ingestion started.",
    "spool_replayed_total": "Durable records persisted after restart or a prior retry.",
    "spool_terminal_total": "Invalid durable records quarantined as terminal.",
    "spool_capacity_failure_total": "Durable staging attempts rejected by configured capacity.",
    "spool_error_total": "Durable spool I/O, integrity, or lifecycle failures.",
    "mqtt_manual_ack_total": "QoS messages manually acknowledged after durable staging.",
    "mqtt_ack_failure_total": "Manual MQTT acknowledgement calls that failed.",
    "mqtt_stage_retry_total": "MQTT messages kept unacknowledged while durable staging retried.",
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
    "spool_ready": "Whether the durable local ingestion spool is writable and readable.",
    "queue_size": "Legacy persistence queue items including the active retry item.",
    "queue_capacity": "Configured maximum legacy persistence queue capacity.",
    "spool_pending_records": "Durable records waiting for PostgreSQL persistence.",
    "spool_terminal_records": "Durable records quarantined for operator review.",
    "spool_payload_bytes": "Retained payload bytes in pending and terminal spool records.",
    "spool_oldest_pending_age_seconds": "Age of the oldest pending durable record.",
    "spool_max_records": "Configured durable spool record capacity.",
    "spool_max_bytes": "Configured durable spool payload-byte capacity.",
    "retention_telemetry_delete_enabled": "Whether retention may delete ordinary telemetry samples (#1551).",
    "retention_last_batches": "Batches executed by the last retention cycle.",
    "retention_last_duration_seconds": "Duration of the last retention cycle.",
    "retention_backlog_remaining": "Whether the last retention cycle stopped with eligible work left.",
    "websocket_clients": "Currently connected WebSocket clients.",
    "ingestion_lag_seconds": "Lag from event capture to successful persistence.",
}

# Rendered only when NEXOLAB_COMMITTED_RECEIPTS=enabled (#1762); the section
# is absent otherwise so the disabled exposition is unchanged.
RECEIPT_COUNTERS = {
    "committed_ingress_total": "Telemetry routed through the committed receipt path.",
    "conflict_dead_letter_total": "Committed-path identity conflicts dead-lettered.",
    "outbox_full_fallback_total": "Telemetry persisted without a receipt intent because the outbox was full.",
    "publish_attempts_total": "Receipt publication attempts (one durable intent each).",
    "published_total": "Receipts confirmed by a broker QoS1 PUBACK (not Edge delivery).",
    "publish_failures_total": "Receipt publication attempts without a broker PUBACK.",
    "loop_errors_total": "Receipt publisher loop errors such as database unavailability.",
}

RECEIPT_GAUGES = {
    "pending": "Committed receipt intents not yet confirmed by the broker.",
    "oldest_pending_age_seconds": "Age of the oldest unpublished committed receipt intent.",
    "consecutive_failures": "Consecutive receipt publisher failures.",
    "publisher_running": "Whether the receipt publisher loop is running.",
    "transport_connected": "Whether the dedicated receipt MQTT identity is connected.",
}


def _render_committed_receipts(lines: list[str], section: object) -> None:
    if not isinstance(section, dict):
        return
    for field, help_text in RECEIPT_COUNTERS.items():
        name = f"{PREFIX}committed_receipt_{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        _sample(lines, f"committed_receipt_{field}", section.get(field, 0))
    for field, help_text in RECEIPT_GAUGES.items():
        value = section.get(field)
        if value is None:
            continue
        name = f"{PREFIX}committed_receipt_{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        _sample(lines, f"committed_receipt_{field}", value)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _positive_integer(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _sample(lines: list[str], name: str, value: int | float | bool) -> None:
    numeric = int(value) if isinstance(value, bool) else value
    lines.append(f"{PREFIX}{name} {numeric}")


def _render_build_info(lines: list[str], service_version: object) -> None:
    if not isinstance(service_version, str) or not service_version:
        return
    escaped = _escape_label(service_version)
    name = f"{PREFIX}build_info"
    lines.append(f"# HELP {name} Static build information for the telemetry service.")
    lines.append(f"# TYPE {name} gauge")
    lines.append(f'{name}{{version="{escaped}"}} 1')

    legacy_name = f"{PREFIX}service_info"
    lines.append(
        f"# HELP {legacy_name} Static service information for compatibility."
    )
    lines.append(f"# TYPE {legacy_name} gauge")
    lines.append(f'{legacy_name}{{version="{escaped}"}} 1')


def render_prometheus(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    resolved = dict(snapshot)

    service_version = resolved.get("service_version") or os.getenv(
        "NEXOLAB_TELEMETRY_VERSION"
    )
    _render_build_info(lines, service_version)

    for capacity_field in (
        "queue_capacity",
        "spool_max_records",
        "spool_max_bytes",
    ):
        capacity = _positive_integer(resolved.get(capacity_field))
        if capacity is not None:
            resolved[capacity_field] = capacity

    for field, help_text in COUNTERS.items():
        name = f"{PREFIX}{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        _sample(lines, field, resolved.get(field, 0))

    for field, help_text in GAUGES.items():
        value = resolved.get(field)
        if value is None:
            continue
        name = f"{PREFIX}{field}"
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        _sample(lines, field, value)

    outage = 1 if resolved.get("database_outage_since") else 0
    lines.extend(
        [
            f"# HELP {PREFIX}database_outage Whether a database outage is active.",
            f"# TYPE {PREFIX}database_outage gauge",
            f"{PREFIX}database_outage {outage}",
        ]
    )

    timestamp_metrics = {
        "last_persisted_timestamp_seconds": resolved.get("last_persisted_at"),
        "last_event_captured_timestamp_seconds": resolved.get(
            "last_event_captured_at"
        ),
        "database_outage_since_timestamp_seconds": resolved.get(
            "database_outage_since"
        ),
        "last_database_recovery_timestamp_seconds": resolved.get(
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

    reason_counts = resolved.get("dead_letter_by_reason", {})
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

    if "committed_receipts" in resolved:
        _render_committed_receipts(lines, resolved["committed_receipts"])

    return "\n".join(lines) + "\n"
