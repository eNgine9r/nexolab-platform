from __future__ import annotations

from collections.abc import Callable
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adaptive_scheduler import ScheduledResult, SchedulerTarget


LOG = logging.getLogger("nexolab.device_agent.latest_values")


class LatestValueStore:
    """Atomic latest-value read model stored in the existing edge SQLite file."""

    def __init__(
        self,
        database_path: Path,
        *,
        busy_timeout_ms: int = 2000,
        busy_retry_attempts: int = 3,
        busy_retry_delay_seconds: float = 0.05,
        health_busy_timeout_ms: int = 100,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        if busy_retry_attempts <= 0:
            raise ValueError("busy_retry_attempts must be positive")
        if busy_retry_delay_seconds < 0:
            raise ValueError("busy_retry_delay_seconds must be non-negative")
        if health_busy_timeout_ms <= 0:
            raise ValueError("health_busy_timeout_ms must be positive")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database_uri = database_path.absolute().as_uri()
        self._health_busy_timeout_ms = health_busy_timeout_ms
        self._connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            timeout=busy_timeout_ms / 1000,
        )
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._busy_retry_attempts = busy_retry_attempts
        self._busy_retry_delay_seconds = busy_retry_delay_seconds
        self._busy_events_total = 0
        self._busy_retries_total = 0
        self._busy_exhausted_total = 0
        self._busy_recoveries_total = 0
        self._busy_consecutive_exhaustions = 0
        self._busy_last_operation: str | None = None
        self._busy_last_error: str | None = None
        self._health_stale_total = 0
        self._health_summary_cache: dict[str, Any] = {
            "schema_version": 1,
            "count": 0,
            "last_attempt_at": None,
            "last_success_at": None,
        }

        def initialize() -> None:
            with self._connection:
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS acquisition_latest_values (
                        target_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        last_attempt_at TEXT NOT NULL,
                        last_success_at TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                summary = self._summary_from_connection(self._connection)
                with self._state_lock:
                    self._health_summary_cache = summary

        with self._lock:
            self._retry_busy("initialize", initialize)

    @staticmethod
    def _is_busy_error(error: sqlite3.OperationalError) -> bool:
        message = str(error).casefold()
        return "locked" in message or "busy" in message

    def _retry_busy(self, label: str, operation: Callable[[], Any]) -> Any:
        saw_busy = False
        for attempt in range(1, self._busy_retry_attempts + 1):
            try:
                result = operation()
                with self._state_lock:
                    if saw_busy:
                        self._busy_recoveries_total += 1
                    self._busy_consecutive_exhaustions = 0
                return result
            except sqlite3.OperationalError as error:
                if self._connection.in_transaction:
                    self._connection.rollback()
                if not self._is_busy_error(error):
                    raise
                saw_busy = True
                exhausted = attempt >= self._busy_retry_attempts
                with self._state_lock:
                    self._busy_events_total += 1
                    self._busy_last_operation = label
                    self._busy_last_error = str(error)
                    if exhausted:
                        self._busy_exhausted_total += 1
                        self._busy_consecutive_exhaustions += 1
                    else:
                        self._busy_retries_total += 1
                if exhausted:
                    LOG.error(
                        "SQLite latest-value %s exhausted lock-contention retry budget %s/%s",
                        label,
                        attempt,
                        self._busy_retry_attempts,
                    )
                    raise
                LOG.warning(
                    "SQLite latest-value %s deferred by lock contention; retry %s/%s",
                    label,
                    attempt,
                    self._busy_retry_attempts,
                )
                if self._busy_retry_delay_seconds:
                    time.sleep(self._busy_retry_delay_seconds * attempt)
        raise RuntimeError("SQLite busy retry loop exhausted unexpectedly")

    def contention_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "schema_version": 1,
                "busy_events_total": self._busy_events_total,
                "busy_retries_total": self._busy_retries_total,
                "busy_exhausted_total": self._busy_exhausted_total,
                "busy_recoveries_total": self._busy_recoveries_total,
                "consecutive_exhaustions": self._busy_consecutive_exhaustions,
                "last_operation": self._busy_last_operation,
                "last_error": self._busy_last_error,
                "health_stale_total": self._health_stale_total,
            }

    def record_attempt(
        self,
        target: SchedulerTarget,
        result: ScheduledResult,
    ) -> None:
        record = result.record

        def operation() -> None:
            with self._connection:
                row = self._connection.execute(
                    """
                    SELECT payload, last_success_at
                    FROM acquisition_latest_values
                    WHERE target_id = ?
                    """,
                    (target.target_id,),
                ).fetchone()
                previous = json.loads(str(row[0])) if row else {}
                attempts_total = int(previous.get("attempts_total", 0)) + 1
                successes_total = int(previous.get("successes_total", 0))
                communication_failures_total = int(
                    previous.get("communication_failures_total", 0)
                )
                consecutive_failures = int(
                    previous.get("consecutive_failures", 0)
                )
                if result.communication_failed:
                    communication_failures_total += 1
                    consecutive_failures += 1
                else:
                    successes_total += 1
                payload = {
                    **previous,
                    "target_id": target.target_id,
                    "source_target": target.target_id,
                    "bus_id": target.bus_id,
                    "device_family": target.device_family,
                    "unit_id": target.unit_id,
                    "metric": record.metric,
                    "equipment_id": record.equipment_id,
                    "channel_id": record.channel_id,
                    "unit": record.unit,
                    "quality": record.quality,
                    "last_attempt_at": record.captured_at,
                    "source": record.source,
                    "last_error": (
                        result.error if result.communication_failed else None
                    ),
                    "attempts_total": attempts_total,
                    "successes_total": successes_total,
                    "communication_failures_total": communication_failures_total,
                    "consecutive_failures": consecutive_failures,
                }
                last_success = (
                    str(row[1]) if row and row[1] is not None else None
                )
                if not result.communication_failed:
                    if consecutive_failures > 0:
                        payload["last_recovered_at"] = record.captured_at
                    payload.update(
                        value=record.value,
                        captured_at=record.captured_at,
                        last_success_at=record.captured_at,
                        alarm=record.alarm,
                        raw_value=record.raw_value,
                        raw_status=record.raw_status,
                        consecutive_failures=0,
                    )
                    last_success = record.captured_at
                payload_json = json.dumps(
                    payload,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                self._connection.execute(
                    """
                    INSERT INTO acquisition_latest_values(
                        target_id, payload, last_attempt_at, last_success_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(target_id) DO UPDATE SET
                        payload = excluded.payload,
                        last_attempt_at = excluded.last_attempt_at,
                        last_success_at = excluded.last_success_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        target.target_id,
                        payload_json,
                        record.captured_at,
                        last_success,
                        record.captured_at,
                    ),
                )

        with self._lock:
            self._retry_busy("record_attempt", operation)

    def last_attempts(self) -> dict[str, str]:
        def operation() -> dict[str, str]:
            rows = self._connection.execute(
                """
                SELECT target_id, last_attempt_at
                FROM acquisition_latest_values
                """
            ).fetchall()
            return {
                str(target_id): str(last_attempt)
                for target_id, last_attempt in rows
            }

        with self._lock:
            return self._retry_busy("last_attempts", operation)

    def payloads_for(
        self,
        target_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not target_ids:
            return {}

        def operation() -> dict[str, dict[str, Any]]:
            result: dict[str, dict[str, Any]] = {}
            for offset in range(0, len(target_ids), 500):
                batch = target_ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = self._connection.execute(
                    f"""
                    SELECT target_id, payload
                    FROM acquisition_latest_values
                    WHERE target_id IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
                for target_id, payload in rows:
                    result[str(target_id)] = json.loads(str(payload))
            return result

        with self._lock:
            return self._retry_busy("payloads_for", operation)

    @staticmethod
    def _summary_from_connection(connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT
                COUNT(*),
                MAX(last_attempt_at),
                MAX(last_success_at)
            FROM acquisition_latest_values
            """
        ).fetchone()
        return {
            "schema_version": 1,
            "count": int(row[0] if row else 0),
            "last_attempt_at": str(row[1]) if row and row[1] else None,
            "last_success_at": str(row[2]) if row and row[2] else None,
        }

    def summary(self) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            result = self._summary_from_connection(self._connection)
            with self._state_lock:
                self._health_summary_cache = dict(result)
            return result

        with self._lock:
            return self._retry_busy("summary", operation)

    def _read_health_summary(self) -> dict[str, Any]:
        connection = sqlite3.connect(
            f"{self._database_uri}?mode=ro",
            uri=True,
            timeout=self._health_busy_timeout_ms / 1000,
        )
        try:
            connection.execute(
                f"PRAGMA busy_timeout = {self._health_busy_timeout_ms}"
            )
            return self._summary_from_connection(connection)
        finally:
            connection.close()

    def health_summary(self) -> tuple[dict[str, Any], bool]:
        """Return latest-value summary without waiting behind persistence work."""
        try:
            result = self._read_health_summary()
        except sqlite3.OperationalError as error:
            if not self._is_busy_error(error):
                raise
            with self._state_lock:
                self._health_stale_total += 1
                return dict(self._health_summary_cache), True
        with self._state_lock:
            self._health_summary_cache = dict(result)
        return result, False

    def snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        bounded = min(2000, max(1, limit))

        def operation() -> dict[str, Any]:
            rows = self._connection.execute(
                """
                SELECT payload
                FROM acquisition_latest_values
                ORDER BY target_id
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            count = self._connection.execute(
                "SELECT COUNT(*) FROM acquisition_latest_values"
            ).fetchone()
            return {
                "schema_version": 1,
                "count": int(count[0] if count else 0),
                "items": [json.loads(str(row[0])) for row in rows],
            }

        with self._lock:
            return self._retry_busy("snapshot", operation)
