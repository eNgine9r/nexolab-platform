from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable

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
        self.assertEqual(queue.size(), 1)
        self.assertEqual(queue.oldest()[0][2], "payload")


if __name__ == "__main__":
    unittest.main()
