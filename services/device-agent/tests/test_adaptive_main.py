from __future__ import annotations

import sqlite3
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

from acquisition_registry import (
    AcquisitionRegistry,
    build_initial_document,
)
from adaptive_main import AdaptiveRegistryDeviceAgent
from adaptive_scheduler import SchedulerTarget
from main import Settings
from modbus_rtu import ModbusError


def settings() -> Settings:
    return Settings(
        node_id="edge-01",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=5,
        database_path=Path("edge.db"),
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="modbus",
        serial_device="/dev/serial/by-id/test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (106, 4)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(200,),
    )


def registry() -> AcquisitionRegistry:
    return AcquisitionRegistry(
        build_initial_document(
            settings(),
            discovery_units=(106,),
            legacy_active_points=((106, 3), (106, 4)),
        )
    )


def agent() -> AdaptiveRegistryDeviceAgent:
    value = object.__new__(AdaptiveRegistryDeviceAgent)
    value._registry = registry()
    value._registry_lock = threading.Lock()
    value._bus_operation_lock = threading.Lock()
    value.settings = settings()
    return value


class AdaptiveRegistryReadTests(unittest.TestCase):
    def test_scheduled_xjp_target_uses_instrumented_target_scope(
        self,
    ) -> None:
        value = agent()
        value.modbus_client = Mock()
        value.modbus_client.instrumentation_scope.return_value = (
            nullcontext()
        )
        value.xjp60d_reader = Mock()
        value.xjp60d_reader.read_channel.return_value = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        target = SchedulerTarget(
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

        result = value._read_scheduled_target(target)

        self.assertFalse(result.communication_failed)
        self.assertEqual(result.record.value, 4.2)
        self.assertEqual(result.record.channel_id, "106-03")
        value.xjp60d_reader.read_channel.assert_called_once_with(106, 3)
        value.modbus_client.instrumentation_scope.assert_called_once_with(
            device_family="xjp60d",
            target_id="xjp60d:106-03",
            operation="normal",
        )

    def test_scheduled_failure_is_truthful_communication_error(self) -> None:
        value = agent()
        value.modbus_client = Mock()
        value.modbus_client.instrumentation_scope.return_value = (
            nullcontext()
        )
        value.le01mp_reader = Mock()
        value.le01mp_reader.read_metric.side_effect = ModbusError(
            "timeout"
        )
        target = SchedulerTarget(
            target_id="le01mp:200-voltage",
            bus_id="rs485-main",
            device_id="le01mp-200",
            device_family="le01mp",
            unit_id=200,
            key="voltage",
            telemetry_channel_id="200-voltage",
            metric="electrical.voltage",
            unit="V",
            priority="medium",
            interval_seconds=10,
        )

        result = value._read_scheduled_target(target)

        self.assertTrue(result.communication_failed)
        self.assertEqual(result.record.quality, "communication_error")
        self.assertIsNone(result.record.value)
        self.assertIn("timeout", result.error or "")

    def test_hardware_run_uses_scheduler_not_global_sample_batch(
        self,
    ) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value.stop_event.set()
        value.connect = Mock()
        value.scheduler = Mock()
        value.sample_batch = Mock(
            side_effect=AssertionError("global sample_batch must not run")
        )
        value.modbus_client = None
        value.operational = None
        value.client = Mock()

        value.run()

        value.connect.assert_called_once_with()
        value.scheduler.start.assert_called_once_with()
        value.scheduler.stop.assert_called_once_with()
        value.sample_batch.assert_not_called()
        value.client.disconnect.assert_called_once_with()
        value.client.loop_stop.assert_called_once_with()



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

    def test_health_fails_closed_when_eligible_bus_worker_is_dead(
        self,
    ) -> None:
        value = agent()
        value.state = Mock()
        value.state.snapshot.return_value = {
            "status": "ok",
            "last_error": None,
        }
        value.queue = Mock()
        value.queue.size.return_value = 0
        value.registry_summary = Mock(
            return_value={
                "poll_eligible_targets": 1,
            }
        )
        value.acquisition_snapshot = Mock(
            return_value={
                "polling_policy": "priority_adaptive_v1",
                "scheduler": {
                    "expected_bus_workers": 1,
                    "active_bus_workers": 0,
                    "workers_healthy": False,
                },
            }
        )
        value.scheduler = Mock()
        value.scheduler.latest_summary.return_value = {}
        value.scheduler.current_error.return_value = (
            "adaptive acquisition worker unavailable: "
            "1 bus worker(s) inactive"
        )

        payload = value.health_snapshot()

        self.assertEqual(payload["status"], "error")
        self.assertIn("worker unavailable", payload["last_error"])
        self.assertEqual(
            payload["acquisition"]["scheduler"][
                "active_bus_workers"
            ],
            0,
        )


if __name__ == "__main__":
    unittest.main()
