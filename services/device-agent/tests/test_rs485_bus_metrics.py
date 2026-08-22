from __future__ import annotations

import unittest

from modbus_rtu import ModbusRequestMeasurement
from rs485_bus_metrics import RS485BusRequestMetrics


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def measurement(
    bus: str,
    *,
    outcome: str,
    attempt: int,
    duration_seconds: float,
) -> ModbusRequestMeasurement:
    return ModbusRequestMeasurement(
        bus=bus,
        device_family="xjp60d",
        target_id="xjp60d:106-03",
        operation="normal",
        unit_id=106,
        function=3,
        address=260,
        count=1,
        attempt=attempt,
        outcome=outcome,
        duration_seconds=duration_seconds,
    )


class RS485BusRequestMetricsTests(unittest.TestCase):
    def test_request_windows_remain_isolated_by_logical_bus(self) -> None:
        clock = FakeClock()
        metrics = RS485BusRequestMetrics(clock=clock, window_seconds=60)

        metrics.observe(
            measurement(
                "rs485-kk1",
                outcome="success",
                attempt=1,
                duration_seconds=0.010,
            )
        )
        clock.advance(1)
        metrics.observe(
            measurement(
                "rs485-kk1",
                outcome="timeout",
                attempt=2,
                duration_seconds=0.030,
            )
        )
        metrics.observe(
            measurement(
                "rs485-kk2",
                outcome="success",
                attempt=1,
                duration_seconds=0.020,
            )
        )

        kk1 = metrics.snapshot("rs485-kk1")
        kk2 = metrics.snapshot("rs485-kk2")

        self.assertEqual(kk1["physical_requests_total"], 2)
        self.assertEqual(kk1["retry_attempts_total"], 1)
        self.assertEqual(kk1["timeouts_total"], 1)
        self.assertEqual(kk1["latency_ms"]["average"], 20.0)
        self.assertEqual(kk1["latency_ms"]["p95"], 30.0)
        self.assertEqual(kk1["request_rate_per_minute"], 2.0)

        self.assertEqual(kk2["physical_requests_total"], 1)
        self.assertEqual(kk2["retry_attempts_total"], 0)
        self.assertEqual(kk2["timeouts_total"], 0)
        self.assertEqual(kk2["latency_ms"]["average"], 20.0)
        self.assertEqual(kk2["request_rate_per_minute"], 1.0)

    def test_recent_latency_window_expires_without_losing_totals(self) -> None:
        clock = FakeClock()
        metrics = RS485BusRequestMetrics(clock=clock, window_seconds=60)
        metrics.observe(
            measurement(
                "rs485-kk1",
                outcome="success",
                attempt=1,
                duration_seconds=0.010,
            )
        )

        clock.advance(61)
        snapshot = metrics.snapshot("rs485-kk1")

        self.assertEqual(snapshot["physical_requests_total"], 1)
        self.assertEqual(snapshot["latency_ms"]["sample_count"], 0)
        self.assertEqual(snapshot["request_rate_per_minute"], 0.0)


if __name__ == "__main__":
    unittest.main()
