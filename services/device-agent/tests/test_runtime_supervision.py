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
