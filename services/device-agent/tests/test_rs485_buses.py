from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acquisition_registry import AcquisitionRegistry, build_initial_document
from main import Settings
from rs485_buses import BUS_CONFIG_ENV, LEGACY_BUS_ID, RS485BusTopology


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
        device_mode="modbus",
        serial_device="/dev/serial/by-id/legacy-test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (126, 3)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(200,),
    )


def registry(database_path: Path) -> AcquisitionRegistry:
    value = settings(database_path)
    return AcquisitionRegistry(
        build_initial_document(
            value,
            discovery_units=(106, 126),
            legacy_active_points=value.xjp60d_points,
        )
    )


def explicit_payload() -> list[dict[str, object]]:
    return [
        {
            "bus_id": "rs485-kk1",
            "serial_device": "/host/dev/serial/by-id/usb-kk1",
            "unit_ids": [126, 200],
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "timeout_seconds": 0.4,
            "retries": 2,
        },
        {
            "bus_id": "rs485-kk2",
            "serial_device": "/host/dev/serial/by-id/usb-kk2",
            "unit_ids": [106],
        },
    ]


class RS485BusTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.settings = settings(self.database_path)
        self.registry = registry(self.database_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def topology(self, payload: list[dict[str, object]]) -> RS485BusTopology:
        return RS485BusTopology.from_environment(
            self.settings,
            self.registry,
            environ={BUS_CONFIG_ENV: json.dumps(payload)},
        )

    def test_explicit_topology_rebinds_registry_devices_without_target_duplication(self) -> None:
        topology = self.topology(explicit_payload())
        rebound = topology.bind_registry(self.registry)

        self.assertTrue(topology.explicit)
        self.assertEqual(
            {item.bus_id for item in rebound.document.buses},
            {"rs485-kk1", "rs485-kk2"},
        )
        devices = {item.device_id: item for item in rebound.document.devices}
        self.assertEqual(devices["xjp60d-126"].bus_id, "rs485-kk1")
        self.assertEqual(devices["le01mp-200"].bus_id, "rs485-kk1")
        self.assertEqual(devices["xjp60d-106"].bus_id, "rs485-kk2")
        self.assertEqual(
            len(rebound.document.targets),
            len(self.registry.document.targets),
        )
        self.assertEqual(
            len({item.target_id for item in rebound.document.targets}),
            len(rebound.document.targets),
        )

    def test_same_explicit_config_rebinds_an_already_multi_bus_registry_after_restart(self) -> None:
        topology = self.topology(explicit_payload())
        first = topology.bind_registry(self.registry)
        restarted = RS485BusTopology.from_environment(
            self.settings,
            first,
            environ={BUS_CONFIG_ENV: json.dumps(explicit_payload())},
        ).bind_registry(first)

        self.assertEqual(restarted.document.buses, first.document.buses)
        self.assertEqual(restarted.document.devices, first.document.devices)

    def test_legacy_configuration_preserves_single_bus_contract(self) -> None:
        topology = RS485BusTopology.from_environment(
            self.settings,
            self.registry,
            environ={},
        )

        self.assertFalse(topology.explicit)
        self.assertEqual(topology.bindings[0].bus_id, LEGACY_BUS_ID)
        self.assertEqual(
            topology.bind_registry(self.registry).document,
            self.registry.document,
        )

    def test_missing_registry_device_assignment_fails_closed(self) -> None:
        payload = explicit_payload()
        payload[0]["unit_ids"] = [126]

        with self.assertRaisesRegex(ValueError, "missing Unit IDs: 200"):
            self.topology(payload)

    def test_duplicate_physical_path_fails_closed(self) -> None:
        payload = explicit_payload()
        payload[1]["serial_device"] = payload[0]["serial_device"]

        with self.assertRaisesRegex(ValueError, "same serial path"):
            self.topology(payload)

    def test_duplicate_unit_ownership_fails_closed(self) -> None:
        payload = explicit_payload()
        payload[1]["unit_ids"] = [106, 126]

        with self.assertRaisesRegex(ValueError, "assigned to both"):
            self.topology(payload)

    def test_unstable_ttyusb_path_is_rejected(self) -> None:
        payload = explicit_payload()
        payload[0]["serial_device"] = "/dev/ttyUSB0"

        with self.assertRaisesRegex(ValueError, "stable /dev/serial/by-id"):
            self.topology(payload)

    def test_persisted_multi_bus_registry_requires_explicit_runtime_bindings(self) -> None:
        topology = self.topology(explicit_payload())
        rebound = topology.bind_registry(self.registry)

        with self.assertRaisesRegex(ValueError, BUS_CONFIG_ENV):
            RS485BusTopology.from_environment(
                self.settings,
                rebound,
                environ={},
            )


if __name__ == "__main__":
    unittest.main()
