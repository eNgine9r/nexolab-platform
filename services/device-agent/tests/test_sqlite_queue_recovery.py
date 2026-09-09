from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from main import OfflineQueue


class OfflineQueueLockRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.queue = OfflineQueue(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=8,
            busy_retry_delay_seconds=0.01,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

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

        release_thread = threading.Thread(target=release)
        release_thread.start()
        try:
            return operation()
        finally:
            release_thread.join(timeout=1)
            self.assertFalse(release_thread.is_alive())

    def test_transient_initialization_lock_recovers(self) -> None:
        blocker = sqlite3.connect(
            self.database_path, timeout=0, check_same_thread=False
        )
        blocker.execute("BEGIN EXCLUSIVE")

        def release() -> None:
            time.sleep(0.06)
            blocker.rollback()
            blocker.close()

        thread = threading.Thread(target=release)
        thread.start()
        try:
            queue = OfflineQueue(
                self.database_path,
                busy_timeout_ms=10,
                busy_retry_attempts=8,
                busy_retry_delay_seconds=0.01,
            )
        finally:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

        contention = queue.contention_snapshot()
        self.assertEqual(contention["last_operation"], "initialize")
        self.assertGreater(contention["busy_retries_total"], 0)
        self.assertEqual(contention["busy_exhausted_total"], 0)
        self.assertEqual(queue.size(), 0)

    def test_persistent_initialization_lock_fails_boundedly(self) -> None:
        blocker = sqlite3.connect(
            self.database_path, timeout=0, check_same_thread=False
        )
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                OfflineQueue(
                    self.database_path,
                    busy_timeout_ms=10,
                    busy_retry_attempts=2,
                    busy_retry_delay_seconds=0.01,
                )
        finally:
            blocker.rollback()
            blocker.close()
        self.assertLess(time.monotonic() - started, 0.5)

    def test_transient_lock_recovers_across_all_queue_operations(self) -> None:
        self.queue.enqueue("topic", "payload-1", "event-1")

        self.assertEqual(
            self._run_during_exclusive_lock(self.queue.size),
            1,
        )
        oldest = self._run_during_exclusive_lock(self.queue.oldest)
        self.assertEqual(len(oldest), 1)
        first_id = oldest[0][0]

        self._run_during_exclusive_lock(
            lambda: self.queue.enqueue("topic", "payload-2", "event-2")
        )
        self.assertEqual(self.queue.size(), 2)

        sequence = self._run_during_exclusive_lock(
            lambda: self.queue.next_sequence("telemetry")
        )
        self.assertEqual(sequence, 1)
        self.assertEqual(self.queue.next_sequence("telemetry"), 2)

        self._run_during_exclusive_lock(lambda: self.queue.delete(first_id))
        rows = self.queue.oldest()
        self.assertEqual(len(rows), 1)
        self.assertIn("payload-2", rows[0][2])
        contention = self.queue.contention_snapshot()
        self.assertGreaterEqual(contention["busy_events_total"], 5)
        self.assertGreaterEqual(contention["busy_retries_total"], 5)
        self.assertGreaterEqual(contention["busy_recoveries_total"], 5)
        self.assertEqual(contention["busy_exhausted_total"], 0)
        self.assertEqual(contention["consecutive_exhaustions"], 0)

    def test_atomic_sequenced_enqueue_recovers_without_sequence_gap(self) -> None:
        first_payload = {"event_id": "event-seq-1", "value": 4.2}
        second_payload = {"event_id": "event-seq-2", "value": 4.3}

        self._run_during_exclusive_lock(
            lambda: self.queue.enqueue_with_sequence(
                "topic", first_payload, "event-seq-1", stream="telemetry"
            )
        )
        self.queue.enqueue_with_sequence(
            "topic", second_payload, "event-seq-2", stream="telemetry"
        )

        rows = self.queue.oldest()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [json.loads(payload)["node_sequence"] for _, _, payload in rows],
            [1, 2],
        )
        contention = self.queue.contention_snapshot()
        self.assertGreater(contention["busy_retries_total"], 0)
        self.assertEqual(contention["busy_exhausted_total"], 0)

    def test_persistent_lock_fails_boundedly_without_data_loss(self) -> None:
        queue = OfflineQueue(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=2,
            busy_retry_delay_seconds=0.01,
        )
        queue.enqueue("topic", "payload", "event-1")
        blocker = sqlite3.connect(
            self.database_path,
            timeout=0,
            check_same_thread=False,
        )
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                queue.size()
        finally:
            blocker.rollback()
            blocker.close()

        self.assertLess(time.monotonic() - started, 0.5)
        exhausted = queue.contention_snapshot()
        self.assertEqual(exhausted["busy_exhausted_total"], 1)
        self.assertEqual(exhausted["consecutive_exhaustions"], 1)
        self.assertEqual(exhausted["last_operation"], "size")
        self.assertEqual(queue.size(), 1)
        self.assertEqual(queue.oldest()[0][2], "payload")
        recovered = queue.contention_snapshot()
        self.assertEqual(recovered["consecutive_exhaustions"], 0)

    def test_health_depth_returns_cached_value_within_probe_budget(self) -> None:
        queue = OfflineQueue(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=2,
            busy_retry_delay_seconds=0.01,
            health_busy_timeout_ms=20,
        )
        queue.enqueue("topic", "payload", "event-health")
        self.assertEqual(queue.size(), 1)
        blocker = sqlite3.connect(
            self.database_path,
            timeout=0,
            check_same_thread=False,
        )
        blocker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        try:
            depth, stale = queue.health_depth()
        finally:
            blocker.rollback()
            blocker.close()

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(depth, 1)
        self.assertTrue(stale)
        self.assertEqual(queue.contention_snapshot()["health_stale_total"], 1)
        self.assertEqual(queue.health_depth(), (1, False))

    def test_health_state_does_not_wait_for_contended_operation_mutex(self) -> None:
        queue = OfflineQueue(
            self.database_path,
            busy_timeout_ms=500,
            busy_retry_attempts=3,
            busy_retry_delay_seconds=0.01,
            health_busy_timeout_ms=20,
        )
        queue.enqueue("topic", "payload", "event-health-concurrent")
        self.assertEqual(queue.health_depth(), (1, False))
        blocker = sqlite3.connect(
            self.database_path, timeout=0, check_same_thread=False
        )
        blocker.execute("BEGIN EXCLUSIVE")
        errors: list[Exception] = []

        def blocked_size() -> None:
            try:
                queue.size()
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        worker = threading.Thread(target=blocked_size)
        worker.start()
        deadline = time.monotonic() + 0.5
        while not queue._lock.locked() and time.monotonic() < deadline:  # noqa: SLF001
            time.sleep(0.005)
        self.assertTrue(queue._lock.locked())  # noqa: SLF001

        started = time.monotonic()
        try:
            depth, stale = queue.health_depth()
            contention = queue.contention_snapshot()
            elapsed = time.monotonic() - started
        finally:
            blocker.rollback()
            blocker.close()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertLess(elapsed, 0.5)
        self.assertEqual(depth, 1)
        self.assertTrue(stale)
        self.assertGreaterEqual(contention["health_stale_total"], 1)

    def test_reserved_write_lock_allows_health_read_but_blocks_enqueue(self) -> None:
        queue = OfflineQueue(
            self.database_path,
            busy_timeout_ms=10,
            busy_retry_attempts=2,
            busy_retry_delay_seconds=0.01,
            health_busy_timeout_ms=20,
        )
        blocker = sqlite3.connect(
            self.database_path, timeout=0, check_same_thread=False
        )
        blocker.execute("BEGIN IMMEDIATE")
        try:
            self.assertEqual(queue.health_depth(), (0, False))
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                queue.enqueue("topic", "payload", "event-blocked")
        finally:
            blocker.rollback()
            blocker.close()
        self.assertEqual(queue.size(), 0)

    def test_health_depth_does_not_hide_structural_sqlite_failure(self) -> None:
        with patch.object(
            self.queue,
            "_read_health_depth",
            side_effect=sqlite3.OperationalError("disk I/O error"),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
                self.queue.health_depth()


if __name__ == "__main__":
    unittest.main()
