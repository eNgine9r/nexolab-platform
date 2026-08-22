from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from acquisition_registry import AcquisitionRegistryStore
from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent
from main import Settings
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


def bus_payload(*, include_unused: bool = False) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = [
        {
            "bus_id": "rs485-kk1",
            "serial_device": "/host/dev/serial/by-id/usb-kk1",
            "unit_ids": [126],
        },
        {
            "bus_id": "rs485-kk2",
            "serial_device": "/host/dev/serial/by-id/usb-kk2",
            "unit_ids": [106, 115],
        },
    ]
    if include_unused:
        payload.append(
            {
                "bus_id": "rs485-spare",
                "serial_device": "/host/dev/serial/by-id/usb-spare",
                "unit_ids": [],
            }
        )
    return payload


class DualBusSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.settings = settings(self.database_path)
        # Simulate an older persisted catalog that predates Unit 115 enrollment.
        AcquisitionRegistryStore(self.database_path).load_or_migrate(
            self.settings,
            discovery_units=(106, 126),
            legacy_active_points=self.settings.xjp60d_points,
        )
        self.environment = patch.dict(
            os.environ,
            {
                BUS_CONFIG_ENV: json.dumps(bus_payload()),
                "XJP60D_DISCOVERY_UNITS": "106,115,126",
            },
            clear=False,
        )
        self.environment.start()
        self.agent = DualBusAdaptiveRegistryDeviceAgent(self.settings)

    def tearDown(self) -> None:
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.close()
        self.environment.stop()
        self.temporary.cleanup()

    def test_global_registry_mutation_guard_waits_for_each_physical_bus(self) -> None:
        for bus_id in ("rs485-kk1", "rs485-kk2"):
            held = self.agent._bus_operation_locks[bus_id]  # noqa: SLF001
            held.acquire()
            entered = threading.Event()

            def mutate() -> None:
                with self.agent._bus_operation_lock:  # noqa: SLF001
                    entered.set()

            worker = threading.Thread(target=mutate)
            worker.start()
            time.sleep(0.05)
            self.assertFalse(entered.is_set())
            held.release()
            self.assertTrue(entered.wait(timeout=1))
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

    def test_active_missing_bus_paths_fail_health_closed(self) -> None:
        payload = self.agent.health_snapshot()

        self.assertEqual(payload["status"], "error")
        self.assertIn(
            "active RS-485 bus device unavailable",
            payload["last_error"] or "",
        )
        self.assertIn("rs485-kk1", payload["last_error"] or "")
        self.assertIn("rs485-kk2", payload["last_error"] or "")

    def test_configured_unused_missing_bus_is_not_reported_as_active_failure(self) -> None:
        other_database = Path(self.temporary.name) / "spare-edge.db"
        other_settings = settings(other_database)
        AcquisitionRegistryStore(other_database).load_or_migrate(
            other_settings,
            discovery_units=(106, 126),
            legacy_active_points=other_settings.xjp60d_points,
        )
        with patch.dict(
            os.environ,
            {
                BUS_CONFIG_ENV: json.dumps(bus_payload(include_unused=True)),
                "XJP60D_DISCOVERY_UNITS": "106,115,126",
            },
            clear=False,
        ):
            other = DualBusAdaptiveRegistryDeviceAgent(other_settings)
        try:
            payload = other.health_snapshot()
            self.assertNotIn("rs485-spare", payload["last_error"] or "")
            buses = {
                item["bus_id"]: item
                for item in payload["acquisition"]["rs485_buses"]
            }
            self.assertEqual(buses["rs485-spare"]["active_target_count"], 0)
            self.assertEqual(
                buses["rs485-spare"]["acceptance_state"],
                "hardware_unverified",
            )
        finally:
            for client in other._bus_clients.values():  # noqa: SLF001
                client.close()

    def test_discovery_enrolls_missing_unit_on_the_scanned_bus(self) -> None:
        reading = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        kk1_reader = Mock()
        kk2_reader = Mock()
        kk1_reader.read_channel.return_value = reading
        kk2_reader.read_channel.return_value = reading
        self.agent._bus_xjp60d_readers = {  # noqa: SLF001
            "rs485-kk1": kk1_reader,
            "rs485-kk2": kk2_reader,
        }
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.instrumentation_scope = Mock(return_value=nullcontext())  # type: ignore[method-assign]

        before = self.agent._registry_snapshot().revision  # noqa: SLF001
        result = self.agent.discover_xjp60d()["last_discovery"]
        after = self.agent._registry_snapshot()  # noqa: SLF001

        devices = {item.device_id: item for item in after.document.devices}
        self.assertEqual(devices["xjp60d-115"].bus_id, "rs485-kk2")
        self.assertEqual(devices["xjp60d-115"].lifecycle, "discovery_only")
        self.assertEqual(after.revision, before + 1)
        self.assertEqual(
            {item["bus_id"] for item in result["buses"]},
            {"rs485-kk1", "rs485-kk2"},
        )
        self.assertNotIn(
            "xjp60d:115-01",
            {
                item["target_id"]
                for item in self.agent.scheduler.snapshot()["targets"]
            },
        )

        persisted = AcquisitionRegistryStore(self.database_path).load_or_migrate(
            self.settings,
            discovery_units=(106, 126),
            legacy_active_points=self.settings.xjp60d_points,
        )
        persisted_devices = {
            item.device_id: item for item in persisted.document.devices
        }
        self.assertEqual(persisted_devices["xjp60d-115"].bus_id, "rs485-kk2")


if __name__ == "__main__":
    unittest.main()
