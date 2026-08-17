from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from acquisition_registry import (
    LE01MP_PROFILE_VERSION,
    AcquisitionRegistryStore,
    RegistryBus,
    RegistryDevice,
    RegistryDocument,
    RegistryTarget,
    _le_target,
    _reconcile_le01mp_profile,
    document_to_json,
)


class LE01MPEnergyRegistryTests(unittest.TestCase):
    def _legacy_document(self) -> RegistryDocument:
        legacy_profile = "f-and-f-le01mp-fc03-v1"
        return RegistryDocument(
            schema_version=1,
            revision=4,
            buses=(RegistryBus("rs485-main", "modbus_rtu", True),),
            devices=(
                RegistryDevice(
                    device_id="le01mp-201",
                    bus_id="rs485-main",
                    device_family="le01mp",
                    unit_id=201,
                    profile_version=legacy_profile,
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
            ),
            updated_at="2026-08-17T00:00:00+00:00",
        )

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

    def test_reconciles_persisted_v1_profile_without_losing_lifecycle(self) -> None:
        reconciled, changes = _reconcile_le01mp_profile(self._legacy_document())

        self.assertEqual(reconciled.revision, 5)
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

    def test_store_persists_profile_upgrade_and_audit_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            store = AcquisitionRegistryStore(database)
            legacy = self._legacy_document()
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    INSERT INTO acquisition_registry_state(
                        singleton, schema_version, revision, document, updated_at
                    ) VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        legacy.schema_version,
                        legacy.revision,
                        document_to_json(legacy),
                        legacy.updated_at,
                    ),
                )

            migrated = store.load_or_migrate(
                None,  # Existing registry path does not read Settings.
                discovery_units=(),
                legacy_active_points=(),
            )

            self.assertEqual(migrated.revision, 5)
            self.assertIn(
                (201, "active_energy"),
                migrated.eligible_le01mp_metrics(),
            )
            audit = store.recent_audit()
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0]["revision"], 5)
            self.assertEqual(audit[0]["actor"], "system:migration")

            restarted = AcquisitionRegistryStore(database).load_or_migrate(
                None,
                discovery_units=(),
                legacy_active_points=(),
            )
            self.assertEqual(restarted.revision, 5)
            self.assertEqual(len(AcquisitionRegistryStore(database).recent_audit()), 1)

    def test_unknown_profile_is_not_rewritten(self) -> None:
        document = RegistryDocument(
            schema_version=1,
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
            updated_at="2026-08-17T00:00:00+00:00",
        )

        unchanged, changes = _reconcile_le01mp_profile(document)

        self.assertEqual(unchanged, document)
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
