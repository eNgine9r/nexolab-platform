from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from acquisition_registry import (
    AcquisitionRegistry,
    AcquisitionRegistryStore,
    DeviceLifecycleMutation,
    LifecycleMutation,
    RegistryRevisionConflict,
    build_initial_document,
    parse_registry_mutation,
)
from le01mp import REGISTERS as LE01MP_REGISTERS
from main import Settings


def settings(
    *,
    mode: str = "modbus",
    xjp60d_points: tuple[tuple[int, int], ...] = ((106, 3), (106, 4)),
    le01mp_unit_ids: tuple[int, ...] = (200,),
    database_path: Path = Path("edge.db"),
) -> Settings:
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
        device_mode=mode,
        serial_device="/dev/serial/by-id/test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=xjp60d_points,
        xjp60d_scale=0.1,
        le01mp_unit_ids=le01mp_unit_ids,
    )


class AcquisitionRegistryMigrationTests(unittest.TestCase):
    def test_migrates_legacy_xjp_points_and_all_configured_le_metrics(self) -> None:
        document = build_initial_document(
            settings(),
            discovery_units=(101, 106),
            legacy_active_points=((106, 3), (106, 4)),
        )
        registry = AcquisitionRegistry(document)

        self.assertEqual(registry.eligible_xjp60d_points(), ((106, 3), (106, 4)))
        self.assertEqual(
            registry.eligible_le01mp_metrics(),
            tuple((200, register.key) for register in LE01MP_REGISTERS),
        )
        payload = registry.sanitized()
        self.assertEqual(payload["summary"]["inventory_devices"], 3)
        self.assertEqual(
            payload["summary"]["poll_eligible_targets"],
            2 + len(LE01MP_REGISTERS),
        )
        discovery_only = next(
            item for item in payload["targets"] if item["target_id"] == "xjp60d:101-01"
        )
        self.assertFalse(discovery_only["poll_eligible"])
        self.assertEqual(discovery_only["lifecycle"], "discovery_only")

    def test_le_only_mode_does_not_create_xjp_inventory(self) -> None:
        document = build_initial_document(
            settings(mode="le01mp", xjp60d_points=(), le01mp_unit_ids=(200,)),
            discovery_units=(101, 106, 126),
            legacy_active_points=(),
        )

        self.assertEqual(
            {device.device_family for device in document.devices},
            {"le01mp"},
        )
        self.assertTrue(
            all(target.target_id.startswith("le01mp:") for target in document.targets)
        )

    def test_xjp_only_mode_does_not_create_le_inventory(self) -> None:
        document = build_initial_document(
            settings(mode="xjp60d", le01mp_unit_ids=()),
            discovery_units=(101, 106),
            legacy_active_points=((106, 3), (106, 4)),
        )

        self.assertEqual(
            {device.device_family for device in document.devices},
            {"xjp60d"},
        )

    def test_rejects_duplicate_bus_unit_identity_across_families(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate Modbus Unit IDs"):
            build_initial_document(
                settings(le01mp_unit_ids=(106,)),
                discovery_units=(106,),
                legacy_active_points=((106, 3),),
            )


class AcquisitionRegistryEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AcquisitionRegistry(
            build_initial_document(
                settings(),
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )
        )

    def test_each_non_active_target_lifecycle_emits_zero_eligible_target(self) -> None:
        for lifecycle in (
            "disabled",
            "reserve",
            "retired",
            "uninstalled",
            "discovery_only",
            "invalid",
        ):
            with self.subTest(lifecycle=lifecycle):
                document, _ = self.registry.with_mutations(
                    device_mutations=(),
                    target_mutations=(
                        LifecycleMutation("xjp60d:106-03", lifecycle),
                    ),
                )
                eligible = AcquisitionRegistry(document).eligible_xjp60d_points()
                self.assertNotIn((106, 3), eligible)
                self.assertIn((106, 4), eligible)

    def test_non_active_device_suppresses_all_child_targets(self) -> None:
        document, _ = self.registry.with_mutations(
            device_mutations=(DeviceLifecycleMutation("le01mp-200", "reserve"),),
            target_mutations=(),
        )

        self.assertEqual(AcquisitionRegistry(document).eligible_le01mp_metrics(), ())

    def test_individual_le_metric_can_be_disabled(self) -> None:
        document, _ = self.registry.with_mutations(
            device_mutations=(),
            target_mutations=(
                LifecycleMutation("le01mp:200-active-power", "disabled"),
            ),
        )
        eligible = AcquisitionRegistry(document).eligible_le01mp_metrics()

        self.assertNotIn((200, "active_power"), eligible)
        self.assertIn((200, "voltage"), eligible)

    def test_schema_rejects_write_capable_function(self) -> None:
        target = self.registry.document.targets[0]
        invalid = replace(
            self.registry.document,
            targets=(replace(target, function=6), *self.registry.document.targets[1:]),
        )

        with self.assertRaisesRegex(ValueError, "read-only FC03"):
            AcquisitionRegistry(invalid)

    def test_rejects_unknown_and_duplicate_mutations(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown registry targets"):
            self.registry.with_mutations(
                device_mutations=(),
                target_mutations=(LifecycleMutation("unknown", "disabled"),),
            )
        with self.assertRaisesRegex(ValueError, "Duplicate target mutation"):
            self.registry.with_mutations(
                device_mutations=(),
                target_mutations=(
                    LifecycleMutation("xjp60d:106-03", "disabled"),
                    LifecycleMutation("xjp60d:106-03", "reserve"),
                ),
            )


class AcquisitionRegistryStoreTests(unittest.TestCase):
    def test_late_discovery_enrolls_read_only_inventory_without_polling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database_path=database)
            store = AcquisitionRegistryStore(database)
            registry = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )

            enrolled = store.enroll_xjp60d(
                registry,
                expected_revision=1,
                unit_ids=(126,),
                actor="service:xjp60d-discovery",
                reason="Enroll responsive read-only controller",
            )

            self.assertEqual(enrolled.revision, 2)
            device = next(
                item
                for item in enrolled.document.devices
                if item.device_id == "xjp60d-126"
            )
            targets = [
                item
                for item in enrolled.document.targets
                if item.device_id == device.device_id
            ]
            self.assertEqual(device.lifecycle, "discovery_only")
            self.assertEqual(len(targets), 6)
            self.assertTrue(
                all(
                    target.lifecycle == "discovery_only"
                    and target.function == 3
                    for target in targets
                )
            )
            self.assertNotIn((126, 4), enrolled.eligible_xjp60d_points())
            self.assertEqual(
                store.recent_audit()[0]["changes"][0],
                {
                    "entity": "device",
                    "id": "xjp60d-126",
                    "from": "absent",
                    "to": "discovery_only",
                },
            )

            restarted = AcquisitionRegistryStore(database).load_or_migrate(
                current_settings,
                discovery_units=(106, 126),
                legacy_active_points=((106, 3), (106, 4)),
            )
            self.assertEqual(restarted.revision, 2)
            self.assertTrue(
                any(
                    item.device_id == "xjp60d-126"
                    for item in restarted.document.devices
                )
            )

    def test_late_enrollment_is_idempotent_and_rejects_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database_path=database)
            store = AcquisitionRegistryStore(database)
            registry = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )

            unchanged = store.enroll_xjp60d(
                registry,
                expected_revision=1,
                unit_ids=(106,),
                actor="service:xjp60d-discovery",
                reason="Idempotent discovery",
            )
            self.assertIs(unchanged, registry)
            self.assertEqual(len(store.recent_audit()), 1)

            with self.assertRaisesRegex(ValueError, "Conflicting Modbus"):
                store.enroll_xjp60d(
                    registry,
                    expected_revision=1,
                    unit_ids=(200,),
                    actor="service:xjp60d-discovery",
                    reason="Conflicting discovery",
                )
            with self.assertRaisesRegex(ValueError, "Unsupported XJP60D profile"):
                store.enroll_xjp60d(
                    registry,
                    expected_revision=1,
                    unit_ids=(126,),
                    actor="service:xjp60d-discovery",
                    reason="Unsupported profile",
                    profile_version="write-capable-profile",
                )
            with self.assertRaisesRegex(ValueError, "must be integers"):
                store.enroll_xjp60d(
                    registry,
                    expected_revision=1,
                    unit_ids=(126.5,),
                    actor="service:xjp60d-discovery",
                    reason="Invalid identity",
                )

    def test_atomic_update_audit_and_restart_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database_path=database)
            store = AcquisitionRegistryStore(database)
            registry = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )

            updated = store.update(
                registry,
                expected_revision=1,
                actor="organization:test:equipment.manage",
                reason="Reserve unused meter power metric",
                device_mutations=(),
                target_mutations=(
                    LifecycleMutation("le01mp:200-active-power", "reserve"),
                ),
            )

            self.assertEqual(updated.revision, 2)
            self.assertNotIn(
                (200, "active_power"),
                updated.eligible_le01mp_metrics(),
            )
            audit = store.recent_audit()
            self.assertEqual(audit[0]["revision"], 2)
            self.assertEqual(audit[0]["actor"], "organization:test:equipment.manage")
            self.assertEqual(audit[0]["changes"][0]["to"], "reserve")

            restarted = AcquisitionRegistryStore(database).load_or_migrate(
                current_settings,
                discovery_units=(101, 106),
                legacy_active_points=((106, 3), (106, 4)),
            )
            self.assertEqual(restarted.revision, 2)
            self.assertNotIn(
                (200, "active_power"),
                restarted.eligible_le01mp_metrics(),
            )

    def test_stale_revision_is_rejected_without_new_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database_path=database)
            store = AcquisitionRegistryStore(database)
            registry = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )

            with self.assertRaises(RegistryRevisionConflict):
                store.update(
                    registry,
                    expected_revision=2,
                    actor="operator:test",
                    reason="Stale update",
                    device_mutations=(),
                    target_mutations=(
                        LifecycleMutation("xjp60d:106-03", "disabled"),
                    ),
                )
            self.assertEqual(len(store.recent_audit()), 1)

    def test_mutation_parser_requires_reason_revision_and_bounded_entries(self) -> None:
        revision, reason, devices, targets = parse_registry_mutation(
            {
                "expected_revision": 3,
                "reason": "Disable reserve channel",
                "devices": [],
                "targets": [
                    {
                        "target_id": "xjp60d:106-03",
                        "lifecycle": "disabled",
                    }
                ],
            }
        )
        self.assertEqual(revision, 3)
        self.assertEqual(reason, "Disable reserve channel")
        self.assertEqual(devices, ())
        self.assertEqual(targets[0].target_id, "xjp60d:106-03")

        with self.assertRaisesRegex(ValueError, "at least one"):
            parse_registry_mutation(
                {"expected_revision": 1, "reason": "No-op", "targets": []}
            )


if __name__ == "__main__":
    unittest.main()
