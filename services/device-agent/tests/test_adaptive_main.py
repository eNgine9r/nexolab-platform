from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

from acquisition_registry import (
    AcquisitionRegistry,
    build_initial_document,
)
from adaptive_main import AdaptiveRegistryDeviceAgent
from adaptive_scheduler import ScheduledResult, SchedulerTarget
from main import OfflineQueue, Settings, TelemetryRecord
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


    def test_scheduled_enqueue_busy_retries_same_record_without_loss(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value._publish_lock = threading.Lock()
        value._sqlite_busy_supervisor_consecutive = 0
        value._sqlite_busy_supervisor_limit = 3
        value._sqlite_busy_supervisor_delay_seconds = 0.01
        value._fatal_persistence_error = None
        value.state = Mock(samples_total=0, mqtt_connected=False)
        value.scheduler = Mock()
        value.scheduler.current_error.return_value = None
        value.operational = None

        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "edge.db"
            value.queue = OfflineQueue(
                database_path,
                busy_timeout_ms=10,
                busy_retry_attempts=2,
                busy_retry_delay_seconds=0.01,
            )
            blocker = sqlite3.connect(
                database_path, timeout=0, check_same_thread=False
            )
            blocker.execute("BEGIN IMMEDIATE")

            def release() -> None:
                time.sleep(0.06)
                blocker.rollback()
                blocker.close()

            release_thread = threading.Thread(target=release)
            release_thread.start()
            record = TelemetryRecord(
                event_id="event-enqueue-recovery",
                node_id="edge-01",
                captured_at="2026-09-08T18:30:00+00:00",
                metric="temperature.probe",
                value=4.2,
                unit="degC",
                quality="valid",
                source="xjp60d",
                equipment_id="K106",
                channel_id="106-03",
            )
            result = ScheduledResult(
                record=record, communication_failed=False
            )
            try:
                value._record_scheduled_result(Mock(), result)
            finally:
                release_thread.join(timeout=1)
                self.assertFalse(release_thread.is_alive())

            rows = value.queue.oldest()
            self.assertEqual(len(rows), 1)
            self.assertIn(record.event_id, rows[0][2])
            self.assertEqual(value._sqlite_busy_supervisor_consecutive, 0)
            self.assertFalse(value.stop_event.is_set())

    def test_persistent_scheduled_enqueue_busy_sets_fatal_stop(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value._publish_lock = threading.Lock()
        value._sqlite_busy_supervisor_consecutive = 0
        value._sqlite_busy_supervisor_limit = 3
        value._sqlite_busy_supervisor_delay_seconds = 0
        value._fatal_persistence_error = None
        value.publish_or_queue = Mock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        value.state = Mock(samples_total=0, mqtt_connected=False)
        value.scheduler = Mock()
        value.scheduler.current_error.return_value = None
        value.operational = None
        record = Mock(captured_at="2026-09-08T18:31:00+00:00")
        result = Mock(record=record, error=None)

        with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
            value._record_scheduled_result(Mock(), result)

        self.assertEqual(value.publish_or_queue.call_count, 3)
        self.assertTrue(
            all(call.args[0] is record for call in value.publish_or_queue.call_args_list)
        )
        self.assertEqual(value._sqlite_busy_supervisor_consecutive, 3)
        self.assertTrue(value.stop_event.is_set())
        self.assertIsInstance(
            value._fatal_persistence_error, sqlite3.OperationalError
        )
        self.assertFalse(
            any("samples_total" in call.kwargs for call in value.state.update.call_args_list)
        )

    def test_latest_busy_exhaustion_stays_observable_without_immediate_fatal(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value._fatal_persistence_error = None
        value.state = Mock()

        value._handle_latest_persistence_error(
            sqlite3.OperationalError("database is locked")
        )

        self.assertFalse(value.stop_event.is_set())
        self.assertIsNone(value._fatal_persistence_error)

    def test_structural_latest_persistence_failure_sets_fatal_stop(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value._fatal_persistence_error = None
        value.state = Mock()
        error = sqlite3.OperationalError("disk I/O error")

        value._handle_latest_persistence_error(error)

        self.assertTrue(value.stop_event.is_set())
        self.assertIs(value._fatal_persistence_error, error)
        self.assertIn(
            "latest-value persistence failed",
            value.state.update.call_args.kwargs["last_error"],
        )

    def test_fatal_scheduled_persistence_error_makes_run_fail_closed(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value.stop_event.set()
        value._fatal_persistence_error = sqlite3.OperationalError(
            "database is locked"
        )
        value.connect = Mock()
        value.scheduler = Mock()
        value._publish_lock = threading.Lock()
        value.state = Mock(mqtt_connected=False)
        value.modbus_client = None
        value.operational = None
        value.client = Mock()

        with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
            value.run()

        value.scheduler.stop.assert_called_once_with()
        value.client.disconnect.assert_called_once_with()
        value.client.loop_stop.assert_called_once_with()

    def test_transient_queue_busy_exhaustion_keeps_adaptive_runtime_alive(self) -> None:
        value = agent()
        value.stop_event = threading.Event()
        value.connect = Mock()
        value.scheduler = Mock()
        value.scheduler.current_error.return_value = None
        value._publish_lock = threading.Lock()
        value.queue = Mock()
        calls = 0

        def queue_size() -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("database is locked")
            value.stop_event.set()
            return 0

        value.queue.size.side_effect = queue_size
        value.flush_queue = Mock(return_value=True)
        value.state = Mock()
        value._sqlite_busy_supervisor_consecutive = 0
        value._sqlite_busy_supervisor_limit = 3
        value.modbus_client = None
        value.operational = None
        value.client = Mock()

        value.run()

        self.assertEqual(value.queue.size.call_count, 2)
        self.assertEqual(value._sqlite_busy_supervisor_consecutive, 0)
        self.assertIn(
            "SQLite queue supervisor lock contention",
            value.state.update.call_args_list[0].kwargs["last_error"],
        )
        value.scheduler.stop.assert_called_once_with()
        value.client.disconnect.assert_called_once_with()
        value.client.loop_stop.assert_called_once_with()

    def test_persistent_queue_busy_exhaustion_fails_after_bounded_grace(self) -> None:
        value = agent()
        value.stop_event = Mock()
        value.stop_event.is_set.return_value = False
        value.stop_event.wait.return_value = False
        value.connect = Mock()
        value.scheduler = Mock()
        value._publish_lock = threading.Lock()
        value.queue = Mock()
        value.queue.size.side_effect = sqlite3.OperationalError("database is locked")
        value.state = Mock()
        value._sqlite_busy_supervisor_consecutive = 0
        value._sqlite_busy_supervisor_limit = 3
        value.modbus_client = None
        value.operational = None
        value.client = Mock()

        with self.assertRaisesRegex(
            sqlite3.OperationalError,
            "database is locked",
        ):
            value.run()

        self.assertEqual(value.queue.size.call_count, 3)
        self.assertEqual(value._sqlite_busy_supervisor_consecutive, 3)
        value.scheduler.stop.assert_called_once_with()
        value.client.disconnect.assert_called_once_with()
        value.client.loop_stop.assert_called_once_with()

    def test_non_busy_sqlite_failure_fails_adaptive_runtime_immediately(self) -> None:
        value = agent()
        value.stop_event = Mock()
        value.stop_event.is_set.return_value = False
        value.connect = Mock()
        value.scheduler = Mock()
        value._publish_lock = threading.Lock()
        value.queue = Mock()
        value.queue.size.side_effect = sqlite3.OperationalError("disk I/O error")
        value.state = Mock()
        value.modbus_client = None
        value.operational = None
        value.client = Mock()

        with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
            value.run()

        self.assertEqual(value.queue.size.call_count, 1)
        value.stop_event.wait.assert_not_called()

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
        value.queue.health_depth.return_value = (0, False)
        value.queue.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
        }
        value.latest_values = Mock()
        value.latest_values.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
        }
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

    def test_health_exposes_active_latest_value_sqlite_contention(self) -> None:
        value = agent()
        value.state = Mock()
        value.state.snapshot.return_value = {
            "status": "ok",
            "last_error": None,
        }
        value.queue = Mock()
        value.queue.health_depth.return_value = (0, False)
        value.queue.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
            "busy_exhausted_total": 0,
        }
        value.latest_values = Mock()
        value.latest_values.contention_snapshot.return_value = {
            "consecutive_exhaustions": 1,
            "busy_exhausted_total": 2,
        }
        value.acquisition_snapshot = Mock(
            return_value={
                "scheduler": {
                    "workers_healthy": True,
                },
            }
        )
        value.scheduler = Mock()
        value.scheduler.latest_summary.return_value = {}

        payload = value.health_snapshot()

        self.assertEqual(payload["status"], "degraded")
        self.assertIn("latest-value store", payload["last_error"] or "")
        self.assertEqual(
            payload["sqlite_contention"]["latest_values"][
                "busy_exhausted_total"
            ],
            2,
        )

    def test_health_uses_last_known_queue_depth_during_busy_contention(self) -> None:
        value = agent()
        value.state = Mock()
        value.state.snapshot.side_effect = lambda queue_depth, settings: {
            "status": "ok",
            "queue_depth": queue_depth,
            "last_error": None,
        }
        value.queue = Mock()
        value.queue.health_depth.return_value = (7, True)
        value.queue.contention_snapshot.return_value = {
            "consecutive_exhaustions": 1,
            "busy_exhausted_total": 1,
            "last_operation": "size",
        }
        value.latest_values = Mock()
        value.latest_values.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
        }
        value.acquisition_snapshot = Mock(
            return_value={
                "scheduler": {
                    "workers_healthy": True,
                },
            }
        )
        value.scheduler = Mock()
        value.scheduler.latest_summary.return_value = {
            "schema_version": 1,
            "count": 2,
        }

        payload = value.health_snapshot()

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["queue_depth"], 7)
        self.assertTrue(payload["sqlite_contention"]["queue_depth_stale"])
        self.assertIn("queue depth is lock-contended", payload["last_error"] or "")

    def test_health_uses_cached_latest_summary_during_busy_contention(self) -> None:
        value = agent()
        value.state = Mock()
        value.state.snapshot.return_value = {
            "status": "ok",
            "last_error": None,
        }
        value.queue = Mock()
        value.queue.health_depth.return_value = (0, False)
        value.queue.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
        }
        value.latest_values = Mock()
        value.latest_values.contention_snapshot.return_value = {
            "consecutive_exhaustions": 1,
            "busy_exhausted_total": 1,
            "last_operation": "summary",
        }
        value.acquisition_snapshot = Mock(
            return_value={
                "scheduler": {
                    "workers_healthy": True,
                },
            }
        )
        value.scheduler = Mock()
        value.scheduler.latest_summary.side_effect = sqlite3.OperationalError(
            "database is locked"
        )
        value._latest_summary_cache = {
            "schema_version": 1,
            "count": 4,
            "last_attempt_at": "2026-09-08T17:00:00+00:00",
            "last_success_at": "2026-09-08T17:00:00+00:00",
        }

        payload = value.health_snapshot()

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["latest_values"]["count"], 4)
        self.assertTrue(payload["sqlite_contention"]["latest_summary_stale"])
        self.assertIn("latest-value store is lock-contended", payload["last_error"] or "")

    def test_health_does_not_hide_structural_latest_value_failure(self) -> None:
        value = agent()
        value.state = Mock()
        value.state.snapshot.return_value = {
            "status": "ok",
            "last_error": None,
        }
        value.queue = Mock()
        value.queue.health_depth.return_value = (0, False)
        value.queue.contention_snapshot.return_value = {
            "consecutive_exhaustions": 0,
        }
        value.acquisition_snapshot = Mock(
            return_value={
                "scheduler": {
                    "workers_healthy": True,
                },
            }
        )
        value.scheduler = Mock()
        value.scheduler.latest_summary.side_effect = sqlite3.OperationalError(
            "disk I/O error"
        )

        with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
            value.health_snapshot()


if __name__ == "__main__":
    unittest.main()
