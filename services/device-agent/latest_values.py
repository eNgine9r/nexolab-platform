from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adaptive_scheduler import ScheduledResult, SchedulerTarget


class LatestValueStore:
    """Atomic latest-value read model stored in the existing edge SQLite file."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.Lock()
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

    def record_attempt(
        self,
        target: SchedulerTarget,
        result: ScheduledResult,
    ) -> None:
        record = result.record
        with self._lock, self._connection:
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

    def last_attempts(self) -> dict[str, str]:
        with self._lock:
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

    def payloads_for(
        self,
        target_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not target_ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
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

    def summary(self) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
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

    def snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        bounded = min(2000, max(1, limit))
        with self._lock:
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
