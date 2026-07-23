from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any


@dataclass
class RuntimeSnapshot:
    mqtt_connected: bool = False
    database_ready: bool = False
    received_total: int = 0
    accepted_total: int = 0
    persisted_total: int = 0
    duplicate_total: int = 0
    rejected_total: int = 0
    queue_dropped_total: int = 0
    queue_size: int = 0
    dead_letter_queued_total: int = 0
    dead_letter_persisted_total: int = 0
    dead_letter_dropped_total: int = 0
    dead_letter_by_reason: dict[str, int] = field(default_factory=dict)
    persistence_failure_total: int = 0
    database_retry_total: int = 0
    database_recovery_total: int = 0
    retention_runs_total: int = 0
    retention_failure_total: int = 0
    retention_deleted_telemetry_total: int = 0
    retention_redacted_raw_payload_total: int = 0
    retention_deleted_dead_letter_total: int = 0
    websocket_clients: int = 0
    websocket_connect_total: int = 0
    websocket_disconnect_total: int = 0
    websocket_broadcast_total: int = 0
    websocket_filtered_total: int = 0
    websocket_slow_consumer_total: int = 0
    websocket_send_timeout_total: int = 0
    websocket_heartbeat_total: int = 0
    websocket_resume_total: int = 0
    websocket_publish_error_total: int = 0
    last_persisted_at: str | None = None
    last_event_captured_at: str | None = None
    ingestion_lag_seconds: float | None = None
    database_outage_since: str | None = None
    last_database_recovery_at: str | None = None
    mqtt_error: str | None = None
    database_error: str | None = None
    operational_error: str | None = None
    last_error: str | None = None


class RuntimeState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = RuntimeSnapshot()

    def _refresh_last_error(self) -> None:
        self._snapshot.last_error = (
            self._snapshot.database_error
            or self._snapshot.mqtt_error
            or self._snapshot.operational_error
        )

    def set_mqtt_connected(self, value: bool) -> None:
        with self._lock:
            self._snapshot.mqtt_connected = value

    def set_mqtt_error(self, message: str | None) -> None:
        with self._lock:
            self._snapshot.mqtt_error = message
            self._refresh_last_error()

    def set_database_ready(self, value: bool) -> None:
        if value:
            self.mark_database_success()
            return
        with self._lock:
            self._snapshot.database_ready = False

    def mark_database_failure(self, message: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._snapshot.database_ready = False
            if self._snapshot.database_outage_since is None:
                self._snapshot.database_outage_since = now
            self._snapshot.database_error = message
            self._refresh_last_error()

    def mark_database_success(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            if self._snapshot.database_outage_since is not None:
                self._snapshot.database_recovery_total += 1
                self._snapshot.last_database_recovery_at = now
            self._snapshot.database_ready = True
            self._snapshot.database_outage_since = None
            self._snapshot.database_error = None
            self._refresh_last_error()

    def set_queue_size(self, value: int) -> None:
        with self._lock:
            self._snapshot.queue_size = value

    def set_websocket_clients(self, value: int) -> None:
        with self._lock:
            self._snapshot.websocket_clients = value

    def increment(self, field: str, value: int = 1) -> None:
        with self._lock:
            current = getattr(self._snapshot, field)
            setattr(self._snapshot, field, current + value)

    def mark_persisted(self, captured_at: datetime) -> None:
        now = datetime.now(UTC)
        normalized_captured_at = captured_at.astimezone(UTC)
        lag = max(0.0, (now - normalized_captured_at).total_seconds())
        with self._lock:
            self._snapshot.persisted_total += 1
            self._snapshot.last_persisted_at = now.isoformat()
            self._snapshot.last_event_captured_at = normalized_captured_at.isoformat()
            self._snapshot.ingestion_lag_seconds = lag
            self._snapshot.database_ready = True
            if self._snapshot.database_outage_since is not None:
                self._snapshot.database_recovery_total += 1
                self._snapshot.last_database_recovery_at = now.isoformat()
            self._snapshot.database_outage_since = None
            self._snapshot.database_error = None
            self._snapshot.operational_error = None
            self._refresh_last_error()

    def mark_dead_letter_persisted(self, reason_code: str) -> None:
        with self._lock:
            self._snapshot.dead_letter_persisted_total += 1
            current = self._snapshot.dead_letter_by_reason.get(reason_code, 0)
            self._snapshot.dead_letter_by_reason[reason_code] = current + 1
            self._snapshot.database_ready = True
            if self._snapshot.database_outage_since is not None:
                self._snapshot.database_recovery_total += 1
                self._snapshot.last_database_recovery_at = datetime.now(UTC).isoformat()
            self._snapshot.database_outage_since = None
            self._snapshot.database_error = None
            self._refresh_last_error()

    def mark_retention(
        self,
        *,
        telemetry_deleted: int,
        raw_payloads_redacted: int,
        dead_letters_deleted: int,
    ) -> None:
        with self._lock:
            self._snapshot.retention_runs_total += 1
            self._snapshot.retention_deleted_telemetry_total += telemetry_deleted
            self._snapshot.retention_redacted_raw_payload_total += raw_payloads_redacted
            self._snapshot.retention_deleted_dead_letter_total += dead_letters_deleted

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self._snapshot.operational_error = message
            self._refresh_last_error()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)
