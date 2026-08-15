from __future__ import annotations

import textwrap
from pathlib import Path


MAIN_PATH = Path("services/device-agent/main.py")
ADAPTIVE_PATH = Path("services/device-agent/adaptive_main.py")
ADAPTIVE_TEST_PATH = Path("services/device-agent/tests/test_adaptive_main.py")
LOCK_TEST_PATH = Path("services/device-agent/tests/test_sqlite_queue_recovery.py")
SUPERVISION_TEST_PATH = Path("services/device-agent/tests/test_runtime_supervision.py")


main = MAIN_PATH.read_text()
if "from collections.abc import Callable\n" not in main:
    main = main.replace(
        "from __future__ import annotations\n\n",
        "from __future__ import annotations\n\nfrom collections.abc import Callable\n",
        1,
    )
main = main.replace("import threading\nimport uuid\n", "import threading\nimport time\nimport uuid\n", 1)

queue_start = main.index("class OfflineQueue:\n")
queue_end = main.index("\n\nclass AgentState:\n", queue_start)
offline_queue = textwrap.dedent(
    '''
    class OfflineQueue:
        def __init__(
            self,
            database_path: Path,
            *,
            busy_timeout_ms: int = 2000,
            busy_retry_attempts: int = 3,
            busy_retry_delay_seconds: float = 0.05,
        ) -> None:
            if busy_timeout_ms <= 0:
                raise ValueError("busy_timeout_ms must be positive")
            if busy_retry_attempts <= 0:
                raise ValueError("busy_retry_attempts must be positive")
            if busy_retry_delay_seconds < 0:
                raise ValueError("busy_retry_delay_seconds must be non-negative")
            database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                database_path,
                check_same_thread=False,
                timeout=busy_timeout_ms / 1000,
            )
            self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
            self._lock = threading.Lock()
            self._busy_retry_attempts = busy_retry_attempts
            self._busy_retry_delay_seconds = busy_retry_delay_seconds
            with self._connection:
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS outbound_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        topic TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS node_stream_sequences (
                        stream TEXT PRIMARY KEY,
                        last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0)
                    )
                    """
                )

        @staticmethod
        def _is_busy_error(error: sqlite3.OperationalError) -> bool:
            message = str(error).casefold()
            return "locked" in message or "busy" in message

        def _retry_busy(self, label: str, operation: Callable[[], Any]) -> Any:
            for attempt in range(1, self._busy_retry_attempts + 1):
                try:
                    return operation()
                except sqlite3.OperationalError as error:
                    if self._connection.in_transaction:
                        self._connection.rollback()
                    if (
                        not self._is_busy_error(error)
                        or attempt >= self._busy_retry_attempts
                    ):
                        raise
                    LOG.warning(
                        "SQLite queue %s deferred by lock contention; retry %s/%s",
                        label,
                        attempt,
                        self._busy_retry_attempts,
                    )
                    if self._busy_retry_delay_seconds:
                        time.sleep(self._busy_retry_delay_seconds * attempt)
            raise RuntimeError("SQLite busy retry loop exhausted unexpectedly")

        def enqueue(self, topic: str, payload: str, event_id: str) -> None:
            def operation() -> None:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT OR IGNORE INTO outbound_queue(event_id, topic, payload, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            topic,
                            payload,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )

            with self._lock:
                self._retry_busy("enqueue", operation)

        def oldest(self, limit: int = 100) -> list[tuple[int, str, str]]:
            def operation() -> list[tuple[int, str, str]]:
                rows = self._connection.execute(
                    "SELECT id, topic, payload FROM outbound_queue ORDER BY id LIMIT ?",
                    (limit,),
                ).fetchall()
                return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

            with self._lock:
                return self._retry_busy("oldest", operation)

        def delete(self, record_id: int) -> None:
            def operation() -> None:
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM outbound_queue WHERE id = ?",
                        (record_id,),
                    )

            with self._lock:
                self._retry_busy("delete", operation)

        def size(self) -> int:
            def operation() -> int:
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM outbound_queue"
                ).fetchone()
                return int(row[0] if row else 0)

            with self._lock:
                return int(self._retry_busy("size", operation))

        def next_sequence(self, stream: str) -> int:
            normalized = stream.strip().lower()
            if not normalized:
                raise ValueError("stream is required")

            def operation() -> int:
                with self._connection:
                    self._connection.execute(
                        """
                        INSERT INTO node_stream_sequences(stream, last_sequence)
                        VALUES (?, 0)
                        ON CONFLICT(stream) DO NOTHING
                        """,
                        (normalized,),
                    )
                    self._connection.execute(
                        """
                        UPDATE node_stream_sequences
                        SET last_sequence = last_sequence + 1
                        WHERE stream = ?
                        """,
                        (normalized,),
                    )
                    row = self._connection.execute(
                        "SELECT last_sequence FROM node_stream_sequences WHERE stream = ?",
                        (normalized,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("node stream sequence allocation failed")
                    return int(row[0])

            with self._lock:
                return int(self._retry_busy("next_sequence", operation))
    '''
).lstrip()
main = main[:queue_start] + offline_queue + main[queue_end:]

main_marker = "\n\ndef main() -> None:\n"
if main_marker not in main:
    raise SystemExit("main() marker not found")
helper = textwrap.dedent(
    '''

    def run_agent_with_health_server(
        agent: DeviceAgent,
        server: ThreadingHTTPServer,
        *,
        endpoint_label: str,
    ) -> None:
        """Tie HTTP availability to the top-level acquisition runtime lifetime."""

        server_errors: list[Exception] = []

        def serve() -> None:
            try:
                server.serve_forever(poll_interval=0.5)
            except Exception as error:  # noqa: BLE001
                server_errors.append(error)
                agent.state.update(last_error=f"health server failed: {error}")
                agent.stop_event.set()

        server_thread = threading.Thread(
            target=serve,
            name="device-agent-health",
            daemon=True,
        )
        server_thread.start()
        LOG.info(
            "%s listening on %s:%s",
            endpoint_label,
            agent.settings.health_host,
            agent.settings.health_port,
        )

        runtime_error: Exception | None = None
        try:
            agent.run()
            if not agent.stop_event.is_set():
                runtime_error = RuntimeError("device-agent runtime exited unexpectedly")
        except Exception as error:  # noqa: BLE001
            runtime_error = error
            agent.state.update(last_error=f"device-agent runtime failed: {error}")
            LOG.exception("Device-agent runtime failed closed")
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=10)

        if server_thread.is_alive():
            raise RuntimeError("device-agent health server failed to stop")
        if runtime_error is not None:
            raise RuntimeError("device-agent runtime failed") from runtime_error
        if server_errors:
            raise RuntimeError("device-agent health server failed") from server_errors[0]
    '''
)
main = main.replace(main_marker, helper + main_marker, 1)

main_function_start = main.index("def main() -> None:\n")
main_stop_start = main.index(
    "    def stop(signum: int, frame: Any) -> None:\n",
    main_function_start,
)
main_function_end = main.index('\n\nif __name__ == "__main__":', main_stop_start)
main_tail = textwrap.dedent(
    '''
        def stop(signum: int, frame: Any) -> None:
            del frame
            LOG.info("Received signal %s", signum)
            agent.stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        run_agent_with_health_server(
            agent,
            server,
            endpoint_label="Health endpoint",
        )
    '''
).lstrip("\n")
main = main[:main_stop_start] + main_tail + main[main_function_end:]
MAIN_PATH.write_text(main)

adaptive = ADAPTIVE_PATH.read_text()
old_import = "from main import Settings, TelemetryRecord\n"
new_import = textwrap.dedent(
    '''
    from main import (
        Settings,
        TelemetryRecord,
        run_agent_with_health_server,
    )
    '''
).lstrip()
if old_import not in adaptive:
    raise SystemExit("adaptive main import marker not found")
adaptive = adaptive.replace(old_import, new_import, 1)

adaptive_function_start = adaptive.index("def main() -> None:\n")
adaptive_stop_start = adaptive.index(
    "    def stop(signum: int, frame: Any) -> None:\n",
    adaptive_function_start,
)
adaptive_function_end = adaptive.index(
    '\n\nif __name__ == "__main__":',
    adaptive_stop_start,
)
adaptive_tail = textwrap.dedent(
    '''
        def stop(signum: int, frame: Any) -> None:
            del frame
            LOG.info("Received signal %s", signum)
            agent.stop_event.set()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        run_agent_with_health_server(
            agent,
            server,
            endpoint_label="Adaptive health endpoint",
        )
    '''
).lstrip("\n")
adaptive = adaptive[:adaptive_stop_start] + adaptive_tail + adaptive[adaptive_function_end:]
ADAPTIVE_PATH.write_text(adaptive)

LOCK_TEST_PATH.write_text(
    textwrap.dedent(
        '''
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
        '''
    ).lstrip()
)

SUPERVISION_TEST_PATH.write_text(
    textwrap.dedent(
        '''
        from __future__ import annotations

        import sqlite3
        import threading
        import unittest
        from unittest.mock import Mock

        from main import AgentState, run_agent_with_health_server


        class FakeHealthServer:
            def __init__(self) -> None:
                self._stopped = threading.Event()
                self.shutdown_calls = 0
                self.closed = False

            def serve_forever(self, poll_interval: float = 0.5) -> None:
                del poll_interval
                self._stopped.wait(timeout=2)

            def shutdown(self) -> None:
                self.shutdown_calls += 1
                self._stopped.set()

            def server_close(self) -> None:
                self.closed = True


        class RuntimeSupervisionTests(unittest.TestCase):
            @staticmethod
            def agent() -> Mock:
                value = Mock()
                value.stop_event = threading.Event()
                value.state = AgentState()
                value.settings = Mock(
                    health_host="127.0.0.1",
                    health_port=8081,
                )
                return value

            def test_runtime_exception_stops_health_server_and_fails_process(self) -> None:
                agent = self.agent()
                server = FakeHealthServer()
                agent.run.side_effect = sqlite3.OperationalError("database is locked")

                with self.assertRaisesRegex(
                    RuntimeError,
                    "device-agent runtime failed",
                ) as raised:
                    run_agent_with_health_server(
                        agent,
                        server,  # type: ignore[arg-type]
                        endpoint_label="test health",
                    )

                self.assertIsInstance(
                    raised.exception.__cause__,
                    sqlite3.OperationalError,
                )
                self.assertGreaterEqual(server.shutdown_calls, 1)
                self.assertTrue(server.closed)
                self.assertIn("database is locked", agent.state.last_error or "")

            def test_unexpected_clean_runtime_exit_is_fail_closed(self) -> None:
                agent = self.agent()
                server = FakeHealthServer()

                with self.assertRaisesRegex(
                    RuntimeError,
                    "device-agent runtime failed",
                ) as raised:
                    run_agent_with_health_server(
                        agent,
                        server,  # type: ignore[arg-type]
                        endpoint_label="test health",
                    )

                self.assertIsInstance(raised.exception.__cause__, RuntimeError)
                self.assertIn(
                    "exited unexpectedly",
                    str(raised.exception.__cause__),
                )
                self.assertTrue(server.closed)

            def test_requested_stop_returns_cleanly(self) -> None:
                agent = self.agent()
                server = FakeHealthServer()

                def requested_stop() -> None:
                    agent.stop_event.set()

                agent.run.side_effect = requested_stop
                run_agent_with_health_server(
                    agent,
                    server,  # type: ignore[arg-type]
                    endpoint_label="test health",
                )

                self.assertTrue(server.closed)
                self.assertGreaterEqual(server.shutdown_calls, 1)


        if __name__ == "__main__":
            unittest.main()
        '''
    ).lstrip()
)

adaptive_test = ADAPTIVE_TEST_PATH.read_text()
adaptive_test = adaptive_test.replace(
    "import threading\nimport unittest\n",
    "import sqlite3\nimport threading\nimport unittest\n",
    1,
)
health_marker = "    def test_health_fails_closed_when_eligible_bus_worker_is_dead(\n"
if health_marker not in adaptive_test:
    raise SystemExit("adaptive health test marker not found")
adaptive_failure_test = textwrap.dedent(
    '''
        def test_persistent_queue_failure_escapes_top_adaptive_runtime(self) -> None:
            value = agent()
            value.stop_event = threading.Event()
            value.connect = Mock()
            value.scheduler = Mock()
            value._publish_lock = threading.Lock()
            value.queue = Mock()
            value.queue.size.side_effect = sqlite3.OperationalError("database is locked")
            value.modbus_client = None
            value.operational = None
            value.client = Mock()

            with self.assertRaisesRegex(
                sqlite3.OperationalError,
                "database is locked",
            ):
                value.run()

            value.scheduler.start.assert_called_once_with()
            value.scheduler.stop.assert_called_once_with()
            value.client.disconnect.assert_called_once_with()
            value.client.loop_stop.assert_called_once_with()


    '''
)
adaptive_test = adaptive_test.replace(
    health_marker,
    adaptive_failure_test + health_marker,
    1,
)
ADAPTIVE_TEST_PATH.write_text(adaptive_test)
