from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from main import Settings
from managed_main import AcquisitionMetrics
from modbus_rtu import ModbusRequestMeasurement


class FakeTime:
    def __init__(self) -> None:
        self.monotonic = 100.0
        self.wall = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)

    def clock(self) -> float:
        return self.monotonic

    def wall_clock(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)


class AcquisitionMetricsTests(unittest.TestCase):
    @staticmethod
    def _settings() -> Settings:
        environment = {
            "DEVICE_MODE": "modbus",
            "XJP60D_POINTS": "106:3",
            "LE01MP_UNIT_IDS": "200",
            "SERIAL_DEVICE": "/dev/serial/by-id/test-bus",
            "SAMPLE_INTERVAL_SECONDS": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            return Settings.from_env()

    @staticmethod
    def _measurement(
        *,
        unit_id: int,
        address: int,
        attempt: int,
        outcome: str,
        duration: float,
        operation: str = "normal",
        device_family: str = "unclassified",
        target_id: str = "unclassified",
    ) -> ModbusRequestMeasurement:
        return ModbusRequestMeasurement(
            bus="/dev/serial/by-id/test-bus",
            device_family=device_family,
            target_id=target_id,
            operation=operation,
            unit_id=unit_id,
            function=3,
            address=address,
            count=1,
            attempt=attempt,
            outcome=outcome,
            duration_seconds=duration,
        )

    def test_normal_requests_are_classified_and_retries_remain_physical(self) -> None:
        fake_time = FakeTime()
        metrics = AcquisitionMetrics(
            self._settings(),
            clock=fake_time.clock,
            wall_clock=fake_time.wall_clock,
        )

        metrics.observe(
            self._measurement(
                unit_id=106,
                address=260,
                attempt=1,
                outcome="timeout",
                duration=0.3,
            )
        )
        fake_time.advance(0.1)
        metrics.observe(
            self._measurement(
                unit_id=106,
                address=260,
                attempt=2,
                outcome="success",
                duration=0.05,
            )
        )
        metrics.observe(
            self._measurement(
                unit_id=200,
                address=3,
                attempt=1,
                outcome="success",
                duration=0.02,
            )
        )

        snapshot = metrics.snapshot(configured_logical_targets=9)
        normal = snapshot["normal"]
        self.assertEqual(normal["physical_requests_total"], 3)
        self.assertEqual(normal["retry_attempts_total"], 1)
        self.assertEqual(normal["outcomes"], {"success": 2, "timeout": 1})
        self.assertAlmostEqual(normal["bus_busy_seconds_total"], 0.37)

        targets = {item["target_id"]: item for item in snapshot["targets"]}
        self.assertEqual(targets["106-03"]["device_family"], "xjp60d")
        self.assertEqual(targets["106-03"]["requests_total"], 2)
        self.assertEqual(targets["106-03"]["retry_attempts_total"], 1)
        self.assertEqual(targets["200-active-power"]["device_family"], "le01mp")
        self.assertIsNotNone(targets["106-03"]["last_success_at"])
        self.assertEqual(snapshot["configured_logical_targets"], 9)

        series = snapshot["request_series"]
        self.assertTrue(
            any(
                item["device_family"] == "xjp60d"
                and item["unit_id"] == 106
                and item["function"] == 3
                and item["outcome"] == "timeout"
                and item["requests_total"] == 1
                for item in series
            )
        )

    def test_discovery_is_separate_from_normal_acquisition(self) -> None:
        metrics = AcquisitionMetrics(self._settings())
        metrics.observe(
            self._measurement(
                unit_id=106,
                address=256,
                attempt=1,
                outcome="success",
                duration=0.01,
                operation="discovery",
                device_family="xjp60d",
                target_id="catalog-discovery",
            )
        )

        snapshot = metrics.snapshot(configured_logical_targets=9)
        self.assertEqual(snapshot["normal"]["physical_requests_total"], 0)
        self.assertEqual(
            snapshot["service_operations"]["discovery"]["physical_requests_total"],
            1,
        )
        self.assertEqual(snapshot["targets"][0]["operation"], "discovery")

    def test_cycle_metrics_report_request_delta_overrun_and_utilization(self) -> None:
        fake_time = FakeTime()
        metrics = AcquisitionMetrics(
            self._settings(),
            clock=fake_time.clock,
            wall_clock=fake_time.wall_clock,
        )

        metrics.begin_cycle()
        fake_time.advance(0.25)
        metrics.observe(
            self._measurement(
                unit_id=106,
                address=260,
                attempt=1,
                outcome="success",
                duration=0.2,
            )
        )
        fake_time.advance(0.95)
        metrics.complete_cycle(interval_seconds=1.0, failed=False)

        cycle = metrics.snapshot(configured_logical_targets=9)["cycle"]
        self.assertEqual(cycle["started_total"], 1)
        self.assertEqual(cycle["completed_total"], 1)
        self.assertEqual(cycle["failed_total"], 0)
        self.assertEqual(cycle["overrun_total"], 1)
        self.assertEqual(cycle["skipped_total"], 0)
        self.assertEqual(cycle["last_requests"], 1)
        self.assertAlmostEqual(cycle["last_duration_seconds"], 1.2)
        self.assertAlmostEqual(cycle["last_bus_busy_seconds"], 0.2)
        self.assertAlmostEqual(cycle["last_bus_utilization_percent"], 16.667)
        self.assertIsNone(cycle["current_duration_seconds"])
        self.assertIsNotNone(cycle["last_completed_at"])

    def test_current_cycle_duration_is_visible_without_completing_cycle(self) -> None:
        fake_time = FakeTime()
        metrics = AcquisitionMetrics(
            self._settings(),
            clock=fake_time.clock,
            wall_clock=fake_time.wall_clock,
        )
        metrics.begin_cycle()
        fake_time.advance(0.4)

        cycle = metrics.snapshot(configured_logical_targets=9)["cycle"]
        self.assertAlmostEqual(cycle["current_duration_seconds"], 0.4)
        self.assertEqual(cycle["started_total"], 1)
        self.assertEqual(cycle["completed_total"], 0)


if __name__ == "__main__":
    unittest.main()
