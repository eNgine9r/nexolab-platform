from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acquisition_cadence import build_bootstrap_policy
from acquisition_registry import (
    LE01MP_PROFILE_VERSION,
    AcquisitionRegistryStore,
    RegistryBus,
    RegistryDevice,
    RegistryDocument,
    RegistryTarget,
    _le_target,
    _reconcile_le01mp_profile,
)
from main import Settings


class LE01MPEnergyRegistryTests(unittest.TestCase):
    @staticmethod
    def _settings(database: Path) -> Settings:
        return Settings(
            node_id="edge-01",
            organization_id=None,
            mqtt_host="mqtt",
            mqtt_port=1883,
            mqtt_topic="nexolab/telemetry",
            health_interval_seconds=30,
            software_version="test",
            sample_interval_seconds=5,
            database_path=database,
            health_host="127.0.0.1",
            health_port=8081,
            device_mode="le01mp",
            serial_device="/dev/serial/by-id/test",
            serial_baudrate=9600,
            serial_parity="N",
            serial_stopbits=1,
            serial_timeout_seconds=0.3,
            serial_retries=1,
            xjp60d_points=(),
            xjp60d_scale=0.1,
            le01mp_unit_ids=(201,),
        )

    @staticmethod
    def _legacy_profile_rows() -> tuple[
        tuple[RegistryBus, ...],
        tuple[RegistryDevice, ...],
        tuple[RegistryTarget, ...],
    ]:
        legacy_profile = "f-and-f-le01mp-fc03-v1"
        buses = (RegistryBus("rs485-main", "modbus_rtu", True),)
        devices = (
            RegistryDevice(
                device_id="le01mp-201",
                bus_id="rs485-main",
                device_family="le01mp",
                unit_id=201,
                profile_version=legacy_profile,
                lifecycle="active",
            ),
        )
        targets = (
            RegistryTarget(
                target_id="le01mp:201-voltage",
                device_id="le01mp-201",
                kind="metric",
                key="voltage",
                telemetry_channel_id="201-voltage",
                metric="electrical.voltage",
                unit="V",
                profile_version=legacy_profile,
                lifecycle="active",
                function=3,
                addresses=(0,),
            ),
            RegistryTarget(
                target_id="le01mp:201-active-power",
                device_id="le01mp-201",
                kind="metric",
                key="active_power",
                telemetry_channel_id="201-active-power",
                metric="electrical.power.active",
                unit="W",
                profile_version=legacy_profile,
                lifecycle="disabled",
                function=3,
                addresses=(3,),
            ),
        )
        return buses, devices, targets

    def _legacy_profile_v2_document(self) -> RegistryDocument:
        buses, devices, targets = self._legacy_profile_rows()
        cadence = build_bootstrap_policy(
            legacy_interval_seconds=5,
            bus_family_keys=(("rs485-main", "le01mp"),),
            environ={},
        )
        return RegistryDocument(
            schema_version=2,
            revision=4,
            buses=buses,
            devices=devices,
            targets=targets,
            cadence=cadence,
            updated_at="2026-08-17T00:00:00+00:00",
        )

    def _persisted_v1_json(self) -> str:
        buses, devices, targets = self._legacy_profile_rows()
        payload = {
            "schema_version": 1,
            "revision": 4,
            "buses": [
                {
                    "bus_id": item.bus_id,
                    "protocol": item.protocol,
                    "read_only": item.read_only,
                }
                for item in buses
            ],
            "devices": [
                {
                    "device_id": item.device_id,
                    "bus_id": item.bus_id,
                    "device_family": item.device_family,
                    "unit_id": item.unit_id,
                    "profile_version": item.profile_version,
                    "lifecycle": item.lifecycle,
                }
                for item in devices
            ],
            "targets": [
                {
                    "target_id": item.target_id,
                    "device_id": item.device_id,
                    "kind": item.kind,
                    "key": item.key,
                    "telemetry_channel_id": item.telemetry_channel_id,
                    "metric": item.metric,
                    "unit": item.unit,
                    "profile_version": item.profile_version,
                    "lifecycle": item.lifecycle,
                    "function": item.function,
                    "addresses": list(item.addresses),
                }
                for item in targets
            ],
            "updated_at": "2026-08-17T00:00:00+00:00",
        }
        return json.dumps(payload, separators=(",", ":"))

    def test_cumulative_energy_target_records_both_atomic_addresses(self) -> None:
        target = _le_target(201, "active_energy", "active")

        self.assertEqual(target.target_id, "le01mp:201-active-energy")
        self.assertEqual(target.telemetry_channel_id, "201-active-energy")
        self.assertEqual(target.metric, "electrical.energy.active")
        self.assertEqual(target.unit, "kWh")
        self.assertEqual(target.function, 3)
        self.assertEqual(target.addresses, (7, 8))
        self.assertEqual(target.profile_version, LE01MP_PROFILE_VERSION)

    def test_scalar_target_stays_single_register(self) -> None:
        target = _le_target(201, "voltage", "active")

        self.assertEqual(target.addresses, (0,))
        self.assertEqual(target.function, 3)

    def test_reconciles_persisted_profile_without_losing_cadence_or_lifecycle(self) -> None:
        source = self._legacy_profile_v2_document()
        reconciled, changes = _reconcile_le01mp_profile(source)

        self.assertEqual(reconciled.revision, 5)
        self.assertEqual(reconciled.cadence, source.cadence)
        device = reconciled.devices[0]
        self.assertEqual(device.profile_version, LE01MP_PROFILE_VERSION)
        by_key = {
            target.key: target
            for target in reconciled.targets
            if target.device_id == "le01mp-201"
        }
        self.assertEqual(by_key["active_power"].lifecycle, "disabled")
        self.assertEqual(by_key["active_energy"].lifecycle, "active")
        self.assertEqual(by_key["active_energy"].addresses, (7, 8))
        self.assertEqual(
            by_key["active_energy"].metric,
            "electrical.energy.active",
        )
        self.assertTrue(changes)

        unchanged, second_changes = _reconcile_le01mp_profile(reconciled)
        self.assertEqual(unchanged, reconciled)
        self.assertEqual(second_changes, [])

    def test_store_migrates_v1_then_profile_and_audits_each_revision_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            store = AcquisitionRegistryStore(database)
            raw_v1 = self._persisted_v1_json()
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    INSERT INTO acquisition_registry_state(
                        singleton, schema_version, revision, document, updated_at
                    ) VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        4,
                        raw_v1,
                        "2026-08-17T00:00:00+00:00",
                    ),
                )

            current_settings = self._settings(database)
            migrated = store.load_or_migrate(
                current_settings,
                discovery_units=(),
                legacy_active_points=(),
            )

            # v1 -> v2 is revision 5; LE profile reconciliation is revision 6.
            self.assertEqual(migrated.revision, 6)
            self.assertEqual(migrated.document.schema_version, 2)
            self.assertEqual(
                migrated.effective_cadence_for_device("le01mp-201"),
                (30.0, "family_default"),
            )
            self.assertIn(
                (201, "active_energy"),
                migrated.eligible_le01mp_metrics(),
            )
            audit = store.recent_audit()
            self.assertEqual(len(audit), 2)
            self.assertEqual([item["revision"] for item in audit], [6, 5])
            self.assertTrue(all(item["actor"] == "system:migration" for item in audit))

            restarted_store = AcquisitionRegistryStore(database)
            restarted = restarted_store.load_or_migrate(
                current_settings,
                discovery_units=(),
                legacy_active_points=(),
            )
            self.assertEqual(restarted.revision, 6)
            self.assertEqual(restarted.document.cadence, migrated.document.cadence)
            self.assertEqual(len(restarted_store.recent_audit()), 2)

    def test_unknown_profile_is_not_rewritten(self) -> None:
        cadence = build_bootstrap_policy(
            legacy_interval_seconds=5,
            bus_family_keys=(("rs485-main", "le01mp"),),
            environ={},
        )
        document = RegistryDocument(
            schema_version=2,
            revision=2,
            buses=(RegistryBus("rs485-main", "modbus_rtu", True),),
            devices=(
                RegistryDevice(
                    device_id="le01mp-201",
                    bus_id="rs485-main",
                    device_family="le01mp",
                    unit_id=201,
                    profile_version="site-custom-profile",
                    lifecycle="active",
                ),
            ),
            targets=(
                RegistryTarget(
                    target_id="le01mp:201-voltage",
                    device_id="le01mp-201",
                    kind="metric",
                    key="voltage",
                    telemetry_channel_id="201-voltage",
                    metric="electrical.voltage",
                    unit="V",
                    profile_version="site-custom-profile",
                    lifecycle="active",
                    function=3,
                    addresses=(0,),
                ),
            ),
            cadence=cadence,
            updated_at="2026-08-17T00:00:00+00:00",
        )

        unchanged, changes = _reconcile_le01mp_profile(document)

        self.assertEqual(unchanged, document)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
