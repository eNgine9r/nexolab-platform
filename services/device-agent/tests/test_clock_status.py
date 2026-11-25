from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clock_status import TIME_ERROR, ClockStatus  # noqa: E402


class ClockStatusTests(unittest.TestCase):
    def test_synchronized_states(self) -> None:
        for state in (0, 1, 2, 3, 4):
            self.assertTrue(ClockStatus(adjtimex=lambda _buf, s=state: s).snapshot()["synchronized"])

    def test_unsynchronized_kernel_state(self) -> None:
        status = ClockStatus(adjtimex=lambda _buf: TIME_ERROR).snapshot()
        self.assertEqual(status, {"synchronized": False, "kernel_state": 5, "source": "adjtimex"})

    def test_call_is_read_only_zeroed_buffer(self) -> None:
        seen = []

        def fake(buffer) -> int:
            seen.append(bytes(buffer.raw[:4]))
            return 0

        ClockStatus(adjtimex=fake).snapshot()
        self.assertEqual(seen, [b"\x00\x00\x00\x00"])  # modes = 0: never adjusts the clock

    def test_unavailable_never_claims_synchronized(self) -> None:
        def failing(_buffer) -> int:
            raise OSError("seccomp")

        for status in (ClockStatus(adjtimex=None).snapshot(), ClockStatus(adjtimex=failing).snapshot(),
                       ClockStatus(adjtimex=lambda _b: -1).snapshot()):
            self.assertIsNone(status["synchronized"])

    def test_result_is_cached_for_thirty_seconds(self) -> None:
        calls = []
        now = [100.0]
        status = ClockStatus(adjtimex=lambda _b: calls.append(1) or 0, monotonic=lambda: now[0])
        status.snapshot()
        now[0] += 10
        status.snapshot()
        self.assertEqual(len(calls), 1)
        now[0] += 25
        status.snapshot()
        self.assertEqual(len(calls), 2)

    def test_real_host_call_does_not_fail(self) -> None:
        status = ClockStatus().snapshot()
        self.assertIn(status["synchronized"], (True, False, None))


if __name__ == "__main__":
    unittest.main()
