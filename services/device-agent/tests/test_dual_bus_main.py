from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from adaptive_scheduler import ScheduledResult, SchedulerTarget
from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent
from main import Settings, TelemetryRecord
from rs485_buses import BUS_CONFIG_ENV


def settings(database_path: Path) -> Settings:
    return Settings(
        node_id="edge-01",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=5,
        database_path=database_path,
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="xjp60d",
        serial_device="/dev/serial/by-id/legacy-test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (126, 3)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(),
    )


def bus_payload() -> list[dict[str, object]]:
    return [
        {
            "bus_id": "rs485-kk1",
            "serial_device": "/host/dev/serial/by-id/usb-kk1",
            "unit_ids": [126],
        },
        {
            "bus_id": "rs485-kk2",
            "serial_device": "/host/dev/serial/by-id/usb-kk2",
            "unit_ids": [106],
        },
    ]


def success_result(target: SchedulerTarget) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"event-{target.target_id}",
            node_id="edge-01",
            captured_at=datetime.now(timezone.utc).isoformat(),
            metric=target.metric,
            value=4.2,
            unit=target.unit,
            quality="valid",
            source="test",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=False,
    )


class DualBusAdaptiveRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.environment = patch.dict(
            os.environ,
            {
                BUS_CONFIG_ENV: json.dumps(bus_payload()),
                "XJP60D_DISCOVERY_UNITS": "106,126",
            },
            clear=False,
        )
        self.environment.start()
        self.agent = DualBusAdaptiveRegistryDeviceAgent(
            settings(self.database_path)
        )

    def tearDown(self) -> None:
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.close()
        self.environment.stop()
        self.temporary.cleanup()

    def test_composition_uses_distinct_clients_locks_and_registry_bus_ids(self) -> None:
        self.assertIsNone(self.agent.modbus_client)
        self.assertEqual(
            set(self.agent._bus_clients),  # noqa: SLF001
            {"rs485-kk1", "rs485-kk2"},
        )
        self.assertIsNot(
            self.agent._bus_operation_locks["rs485-kk1"],  # noqa: SLF001
            self.agent._bus_operation_locks["rs485-kk2"],  # noqa: SLF001
        )
        self.assertEqual(
            self.agent._bus_clients["rs485-kk1"].port,  # noqa: SLF001
            "/host/dev/serial/by-id/usb-kk1",
        )
        self.assertEqual(
            self.agent._bus_clients["rs485-kk2"].port,  # noqa: SLF001
            "/host/dev/serial/by-id/usb-kk2",
        )
        devices = {
            item.device_id: item
            for item in self.agent._registry_snapshot().document.devices  # noqa: SLF001
        }
        self.assertEqual(devices["xjp60d-126"].bus_id, "rs485-kk1")
        self.assertEqual(devices["xjp60d-106"].bus_id, "rs485-kk2")
        targets = {
            item["target_id"]: item
            for item in self.agent.scheduler.snapshot()["targets"]
        }
        self.assertEqual(targets["xjp60d:126-03"]["bus_id"], "rs485-kk1")
        self.assertEqual(targets["xjp60d:106-03"]["bus_id"], "rs485-kk2")

    def test_scheduler_executes_two_due_buses_concurrently(self) -> None:
        barrier = threading.Barrier(2)
        barrier_passed: list[str] = []

        def read_target(target: SchedulerTarget) -> ScheduledResult:
            barrier.wait(timeout=1)
            barrier_passed.append(target.bus_id)
            return success_result(target)

        self.agent.scheduler._read_target = read_target  # noqa: SLF001
        self.agent.scheduler._record_result = lambda target, result: None  # noqa: SLF001
        self.agent.scheduler._latest_store = Mock()  # noqa: SLF001
        for job in self.agent.scheduler._jobs.values():  # noqa: SLF001
            job.next_deadline = 0

        results: list[bool] = []
        workers = [
            threading.Thread(
                target=lambda bus_id=bus_id: results.append(
                    self.agent.scheduler.run_once(bus_id)
                )
            )
            for bus_id in ("rs485-kk1", "rs485-kk2")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(sorted(barrier_passed), ["rs485-kk1", "rs485-kk2"])
        self.assertEqual(results, [True, True])

    def test_scheduled_target_dispatches_to_its_bus_reader(self) -> None:
        kk1_reader = Mock()
        kk2_reader = Mock()
        reading = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        kk1_reader.read_channel.return_value = reading
        kk2_reader.read_channel.return_value = reading
        self.agent._bus_xjp60d_readers = {  # noqa: SLF001
            "rs485-kk1": kk1_reader,
            "rs485-kk2": kk2_reader,
        }
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.instrumentation_scope = Mock(return_value=nullcontext())  # type: ignore[method-assign]

        targets = {
            job.target.target_id: job.target
            for job in self.agent.scheduler._jobs.values()  # noqa: SLF001
        }
        kk1 = self.agent._read_scheduled_target(targets["xjp60d:126-03"])
        kk2 = self.agent._read_scheduled_target(targets["xjp60d:106-03"])

        self.assertFalse(kk1.communication_failed)
        self.assertFalse(kk2.communication_failed)
        kk1_reader.read_channel.assert_called_once_with(126, 3)
        kk2_reader.read_channel.assert_called_once_with(106, 3)

    def test_explicit_discovery_scans_only_units_owned_by_each_bus(self) -> None:
        kk1_reader = Mock()
        kk2_reader = Mock()
        reading = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        kk1_reader.read_channel.return_value = reading
        kk2_reader.read_channel.return_value = reading
        self.agent._bus_xjp60d_readers = {  # noqa: SLF001
            "rs485-kk1": kk1_reader,
            "rs485-kk2": kk2_reader,
        }
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.instrumentation_scope = Mock(return_value=nullcontext())  # type: ignore[method-assign]

        result = self.agent.discover_xjp60d()["last_discovery"]

        self.assertEqual(kk1_reader.read_channel.call_count, 6)
        self.assertEqual(kk2_reader.read_channel.call_count, 6)
        self.assertTrue(
            all(call.args[0] == 126 for call in kk1_reader.read_channel.call_args_list)
        )
        self.assertTrue(
            all(call.args[0] == 106 for call in kk2_reader.read_channel.call_args_list)
        )
        self.assertEqual(
            {item["bus_id"] for item in result["buses"]},
            {"rs485-kk1", "rs485-kk2"},
        )
        self.assertEqual(result["controller_count"], 2)

    def test_bus_diagnostics_never_claim_hardware_acceptance(self) -> None:
        payload = self.agent.acquisition_snapshot()
        buses = {item["bus_id"]: item for item in payload["rs485_buses"]}

        self.assertEqual(buses["rs485-kk1"]["acceptance_state"], "hardware_unverified")
        self.assertEqual(buses["rs485-kk2"]["acceptance_state"], "hardware_unverified")
        self.assertIn(
            buses["rs485-kk1"]["hardware_state"],
            {"present_unverified", "configured_unavailable"},
        )
        self.assertIsNotNone(buses["rs485-kk1"]["scheduler"])
        self.assertIsNotNone(buses["rs485-kk2"]["scheduler"])


if __name__ == "__main__":
    unittest.main()
