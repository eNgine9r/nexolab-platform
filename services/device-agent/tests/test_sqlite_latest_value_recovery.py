from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable

from adaptive_scheduler import ScheduledResult, SchedulerTarget
from latest_values import LatestValueStore
from main import TelemetryRecord


class LatestValueStoreLockRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def target() -> SchedulerTarget:
        return SchedulerTarget(
            target_id="xjp60d:106-03",
            bus_id="rs485-main",
            device_id="xjp60d-106",
            device_family="xjp60d",
            unit_id=106,
            key="channel-03",
            telemetry_channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            priority="high",
            interval_seconds=5,
        )

    @staticmethod
    def result(captured_at: str, value: float) -> ScheduledResult:
        return ScheduledResult(
            record=TelemetryRecord(
                event_id=f"event-{captured_at}",
                node_id="edge-01",
                captured_at=captured_at,
                metric="temperature.probe",
                value=value,
                unit="degC",
                quality="valid",
                source="xjp60d",
                equipment_id="xjp60d-106",
                channel_id="106-03",
            ),
            communication_failed=False,
        )

    def _run_during_exclusive_lock(
        self,
        operation: Callable[[], Any],
    ) -> Any:
        blocker = sqlite3.connect(
            self.database_path,
            timeout=0,
            check_same_thread=False,
        )
        blocker.execute("BEGIN EXCLUSIVE")

        def release() -> None:
            time.sleep(0.06)
            blocker.rollback()
            blocker.close()

        thread = threading.Thread(target=release)
        thread.start()
        try:
            return operation()
        finally:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

    def test_transient_lock_recovers_latest_value_atomically(self) -> None:
        store = LatestValueStore(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=8,
            busy_retry_delay_seconds=0.01,
        )
        self._run_during_exclusive_lock(
            lambda: store.record_attempt(
                self.target(),
                self.result("2026-09-08T06:00:00+00:00", 4.2),
            )
        )

        payload = store.payloads_for([self.target().target_id])[self.target().target_id]
        self.assertEqual(payload["value"], 4.2)
        self.assertEqual(payload["attempts_total"], 1)
        contention = store.contention_snapshot()
        self.assertGreater(contention["busy_events_total"], 0)
        self.assertGreater(contention["busy_retries_total"], 0)
        self.assertEqual(contention["busy_exhausted_total"], 0)
        self.assertEqual(contention["busy_recoveries_total"], 1)
        self.assertEqual(contention["consecutive_exhaustions"], 0)

    def test_persistent_lock_fails_boundedly_without_partial_latest_update(self) -> None:
        store = LatestValueStore(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=2,
            busy_retry_delay_seconds=0.01,
        )
        store.record_attempt(
            self.target(),
            self.result("2026-09-08T06:00:00+00:00", 4.2),
        )
        blocker = sqlite3.connect(
            self.database_path,
            timeout=0,
            check_same_thread=False,
        )
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                store.record_attempt(
                    self.target(),
                    self.result("2026-09-08T06:00:05+00:00", 4.3),
                )
        finally:
            blocker.rollback()
            blocker.close()

        self.assertLess(time.monotonic() - started, 0.5)
        exhausted = store.contention_snapshot()
        self.assertEqual(exhausted["busy_exhausted_total"], 1)
        self.assertEqual(exhausted["consecutive_exhaustions"], 1)
        self.assertEqual(exhausted["last_operation"], "record_attempt")
        payload = store.payloads_for([self.target().target_id])[self.target().target_id]
        self.assertEqual(payload["value"], 4.2)
        self.assertEqual(payload["attempts_total"], 1)
        store.record_attempt(
            self.target(),
            self.result("2026-09-08T06:00:05+00:00", 4.3),
        )
        recovered = store.payloads_for([self.target().target_id])[self.target().target_id]
        self.assertEqual(recovered["value"], 4.3)
        self.assertEqual(recovered["attempts_total"], 2)
        self.assertEqual(store.contention_snapshot()["consecutive_exhaustions"], 0)


if __name__ == "__main__":
    unittest.main()
