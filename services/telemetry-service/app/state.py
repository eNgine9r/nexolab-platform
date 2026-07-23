from __future__ import annotations

from dataclasses import asdict, dataclass
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
    last_persisted_at: str | None = None
    last_error: str | None = None


class RuntimeState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = RuntimeSnapshot()

    def set_mqtt_connected(self, value: bool) -> None:
        with self._lock:
            self._snapshot.mqtt_connected = value

    def set_database_ready(self, value: bool) -> None:
        with self._lock:
            self._snapshot.database_ready = value

    def set_queue_size(self, value: int) -> None:
        with self._lock:
            self._snapshot.queue_size = value

    def increment(self, field: str, value: int = 1) -> None:
        with self._lock:
            current = getattr(self._snapshot, field)
            setattr(self._snapshot, field, current + value)

    def mark_persisted(self) -> None:
        with self._lock:
            self._snapshot.persisted_total += 1
            self._snapshot.last_persisted_at = datetime.now(UTC).isoformat()
            self._snapshot.last_error = None

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self._snapshot.last_error = message

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)
