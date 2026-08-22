from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acquisition_registry import AcquisitionRegistryStore
from dual_bus_registry import TopologyAwareEnrollmentStore
from main import Settings
from rs485_buses import BUS_CONFIG_ENV, RS485BusTopology


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


def explicit_payload() -> list[dict[str, object]]:
    return [
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


class TopologyAwareEnrollmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.settings = settings(self.database_path)
        base_store = AcquisitionRegistryStore(self.database_path)
        self.legacy_registry = base_store.load_or_migrate(
            self.settings,
            discovery_units=(106, 126),
            legacy_active_points=self.settings.xjp60d_points,
        )
        self.topology = RS485BusTopology.from_environment(
            self.settings,
            self.legacy_registry,
            environ={BUS_CONFIG_ENV: json.dumps(explicit_payload())},
        )
        self.bound_registry = self.topology.bind_registry(self.legacy_registry)
        self.store = TopologyAwareEnrollmentStore(
            self.database_path,
            bus_for_unit=self.topology.bus_for_unit,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_new_responsive_unit_is_persisted_on_its_explicit_bus(self) -> None:
        enrolled = self.store.enroll_xjp60d(
            self.bound_registry,
            expected_revision=self.bound_registry.revision,
            unit_ids=(115,),
            actor="test:discovery",
            reason="prove explicit-bus discovery enrollment",
        )

        devices = {item.device_id: item for item in enrolled.document.devices}
        self.assertEqual(devices["xjp60d-115"].bus_id, "rs485-kk2")
        self.assertEqual(devices["xjp60d-115"].lifecycle, "discovery_only")
        targets = [
            item
            for item in enrolled.document.targets
            if item.device_id == "xjp60d-115"
        ]
        self.assertEqual(len(targets), 6)
        self.assertTrue(all(item.lifecycle == "discovery_only" for item in targets))
        self.assertEqual(enrolled.revision, self.bound_registry.revision + 1)

        reloaded = AcquisitionRegistryStore(self.database_path).load_or_migrate(
            self.settings,
            discovery_units=(106, 126),
            legacy_active_points=self.settings.xjp60d_points,
        )
        persisted = {item.device_id: item for item in reloaded.document.devices}
        self.assertEqual(persisted["xjp60d-115"].bus_id, "rs485-kk2")
        self.assertEqual(
            {item.bus_id for item in reloaded.document.buses},
            {"rs485-kk1", "rs485-kk2"},
        )

    def test_existing_unit_on_wrong_bus_fails_closed(self) -> None:
        wrong_bus_store = TopologyAwareEnrollmentStore(
            self.database_path,
            bus_for_unit=lambda unit_id: (
                "rs485-kk1" if unit_id == 106 else self.topology.bus_for_unit(unit_id)
            ),
        )

        with self.assertRaisesRegex(ValueError, "Conflicting Modbus Unit ownership"):
            wrong_bus_store.enroll_xjp60d(
                self.bound_registry,
                expected_revision=self.bound_registry.revision,
                unit_ids=(106,),
                actor="test:discovery",
                reason="prove conflicting assignment rejection",
            )


if __name__ == "__main__":
    unittest.main()
