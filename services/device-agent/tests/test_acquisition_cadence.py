from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acquisition_cadence import (
    CadenceMutation,
    DeviceCadenceMutation,
    FamilyCadenceMutation,
    parse_cadence_mutation,
)
from acquisition_capacity import (
    BusCapacityProfile,
    CapacityValidationError,
    MIN_MEASURED_P95_SAMPLES,
    evaluate_capacity,
    physical_requests_per_target,
    validate_capacity,
)
from acquisition_registry import (
    AcquisitionRegistry,
    AcquisitionRegistryStore,
    LifecycleMutation,
    RegistryRevisionConflict,
    build_initial_document,
)
from main import Settings
from registry_main import RegistryManagedDeviceAgent


def settings(
    database_path: Path,
    *,
    sample_interval_seconds: float = 5,
) -> Settings:
    return Settings(
        node_id="edge-cadence-test",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=sample_interval_seconds,
        database_path=database_path,
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


def registry(database_path: Path) -> AcquisitionRegistry:
    return AcquisitionRegistry(
        build_initial_document(
            settings(database_path),
            discovery_units=(106,),
            legacy_active_points=((106, 3), (106, 4)),
        )
    )


def profile(
    *,
    timeout_seconds: float = 0.3,
    observed_p95_seconds: float | None = None,
    observed_sample_count: int = 0,
) -> BusCapacityProfile:
    return BusCapacityProfile(
        bus_id="rs485-main",
        baudrate=9600,
        parity="N",
        stopbits=1,
        timeout_seconds=timeout_seconds,
        retries=1,
        observed_p95_seconds=observed_p95_seconds,
        observed_sample_count=observed_sample_count,
    )


class CadencePolicyTests(unittest.TestCase):
    def test_bootstrap_enforces_product_floor_without_accelerating_legacy_le(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = registry(Path(directory) / "edge.db")

        self.assertEqual(
            current.effective_cadence_for_device("xjp60d-106"),
            (10.0, "family_default"),
        )
        self.assertEqual(
            current.effective_cadence_for_device("le01mp-200"),
            (30.0, "family_default"),
        )
        payload = current.sanitized()["cadence"]
        self.assertEqual(payload["presets_seconds"], [10, 30, 60])
        self.assertEqual(payload["custom_min_seconds"], 10)
        self.assertEqual(payload["maximum_seconds"], 3600)

    def test_family_default_then_device_override_precedence_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = registry(Path(directory) / "edge.db")

        document, changes, affected = current.with_cadence_mutation(
            CadenceMutation(
                family_defaults=(
                    FamilyCadenceMutation("rs485-main", "xjp60d", 30),
                ),
                device_overrides=(
                    DeviceCadenceMutation("xjp60d-106", 60),
                ),
            )
        )
        updated = AcquisitionRegistry(document)
        self.assertEqual(
            updated.effective_cadence_for_device("xjp60d-106"),
            (60.0, "device_override"),
        )
        self.assertIn("xjp60d-106", affected)
        self.assertEqual(len(changes), 2)

        cleared_document, _, cleared_affected = updated.with_cadence_mutation(
            CadenceMutation(
                family_defaults=(),
                device_overrides=(
                    DeviceCadenceMutation("xjp60d-106", None),
                ),
            )
        )
        cleared = AcquisitionRegistry(cleared_document)
        self.assertEqual(
            cleared.effective_cadence_for_device("xjp60d-106"),
            (30.0, "family_default"),
        )
        self.assertEqual(cleared_affected, {"xjp60d-106"})

    def test_custom_below_ten_seconds_is_rejected_before_application(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 10 and 3600"):
            parse_cadence_mutation(
                {
                    "expected_revision": 1,
                    "reason": "Unsafe fast request",
                    "device_overrides": [
                        {
                            "device_id": "xjp60d-106",
                            "interval_seconds": 9,
                        }
                    ],
                }
            )

    def test_parser_requires_revision_reason_and_real_change(self) -> None:
        revision, reason, mutation = parse_cadence_mutation(
            {
                "expected_revision": 3,
                "reason": "Set standard cadence",
                "family_defaults": [
                    {
                        "bus_id": "rs485-main",
                        "device_family": "xjp60d",
                        "interval_seconds": 30,
                    }
                ],
            }
        )
        self.assertEqual(revision, 3)
        self.assertEqual(reason, "Set standard cadence")
        self.assertEqual(mutation.family_defaults[0].interval_seconds, 30)

        with self.assertRaisesRegex(ValueError, "at least one change"):
            parse_cadence_mutation(
                {"expected_revision": 1, "reason": "No-op"}
            )


class CadencePersistenceTests(unittest.TestCase):
    def test_store_persists_override_revision_actor_reason_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database)
            store = AcquisitionRegistryStore(database)
            current = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )

            updated = store.update_cadence(
                current,
                expected_revision=current.revision,
                actor="organization:test:equipment.manage",
                reason="Slow controller 106 for maintenance",
                mutation=CadenceMutation(
                    family_defaults=(),
                    device_overrides=(
                        DeviceCadenceMutation("xjp60d-106", 60),
                    ),
                ),
            )

            self.assertEqual(updated.revision, current.revision + 1)
            self.assertEqual(
                updated.effective_cadence_for_device("xjp60d-106"),
                (60.0, "device_override"),
            )
            audit = store.recent_audit()[0]
            self.assertEqual(audit["revision"], updated.revision)
            self.assertEqual(
                audit["actor"],
                "organization:test:equipment.manage",
            )
            self.assertEqual(audit["reason"], "Slow controller 106 for maintenance")

            restarted = AcquisitionRegistryStore(database).load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )
            self.assertEqual(restarted.revision, updated.revision)
            self.assertEqual(
                restarted.effective_cadence_for_device("xjp60d-106"),
                (60.0, "device_override"),
            )

    def test_stale_revision_is_rejected_without_extra_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            current_settings = settings(database)
            store = AcquisitionRegistryStore(database)
            current = store.load_or_migrate(
                current_settings,
                discovery_units=(106,),
                legacy_active_points=((106, 3), (106, 4)),
            )
            before = len(store.recent_audit())

            with self.assertRaises(RegistryRevisionConflict):
                store.update_cadence(
                    current,
                    expected_revision=current.revision + 1,
                    actor="operator:test",
                    reason="Stale cadence update",
                    mutation=CadenceMutation(
                        family_defaults=(),
                        device_overrides=(
                            DeviceCadenceMutation("xjp60d-106", 60),
                        ),
                    ),
                )
            self.assertEqual(len(store.recent_audit()), before)


class CapacityModelTests(unittest.TestCase):
    def test_physical_request_accounting_matches_driver_request_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = registry(Path(directory) / "edge.db")
        xjp = next(
            item
            for item in current.document.targets
            if item.target_id == "xjp60d:106-03"
        )
        le = next(
            item
            for item in current.document.targets
            if item.target_id == "le01mp:200-active-energy"
        )
        self.assertEqual(physical_requests_per_target(xjp), 2)
        self.assertEqual(physical_requests_per_target(le), 1)

    def test_measured_p95_requires_bounded_sample_count(self) -> None:
        sparse = profile(
            observed_p95_seconds=0.02,
            observed_sample_count=MIN_MEASURED_P95_SAMPLES - 1,
        )
        enough = profile(
            observed_p95_seconds=0.02,
            observed_sample_count=MIN_MEASURED_P95_SAMPLES,
        )

        sparse_budget, sparse_source = sparse.request_budget_seconds()
        measured_budget, measured_source = enough.request_budget_seconds()
        self.assertEqual(sparse_source, "serial_timeout_fallback")
        self.assertEqual(measured_source, "measured_p95")
        self.assertGreater(sparse_budget, measured_budget)

    def test_unsafe_capacity_returns_machine_readable_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = registry(Path(directory) / "edge.db")

        slow_profile = profile(timeout_seconds=2.0)
        summary = evaluate_capacity(
            current,
            {"rs485-main": slow_profile},
            changed_device_ids={"xjp60d-106", "le01mp-200"},
        )
        self.assertFalse(summary["safe"])
        bus = summary["buses"][0]
        self.assertFalse(bus["safe"])
        self.assertIsNotNone(bus["recommended_minimum_interval_seconds"])
        self.assertFalse(bus["cooldown_capacity_credit"])

        with self.assertRaises(CapacityValidationError) as context:
            validate_capacity(
                current,
                {"rs485-main": slow_profile},
                changed_device_ids={"xjp60d-106", "le01mp-200"},
            )
        payload = context.exception.payload()
        self.assertEqual(payload["code"], "acquisition_capacity_exceeded")
        self.assertFalse(payload["capacity"]["safe"])

    def test_safe_capacity_reports_effective_device_intervals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = registry(Path(directory) / "edge.db")

        summary = validate_capacity(
            current,
            {"rs485-main": profile(timeout_seconds=0.05)},
        )
        self.assertTrue(summary["safe"])
        devices = {
            item["device_id"]: item
            for item in summary["buses"][0]["devices"]
        }
        self.assertEqual(devices["xjp60d-106"]["effective_interval_seconds"], 10)
        self.assertEqual(devices["le01mp-200"]["effective_interval_seconds"], 30)
        self.assertEqual(devices["xjp60d-106"]["cadence_source"], "family_default")


class ControlPlaneAtomicityTests(unittest.TestCase):
    class SlowCapacityAgent(RegistryManagedDeviceAgent):
        def capacity_profiles(
            self,
            registry: AcquisitionRegistry | None = None,
        ) -> dict[str, BusCapacityProfile]:
            del registry
            return {"rs485-main": profile(timeout_seconds=2.0)}

    def test_unsafe_cadence_rejection_preserves_revision_policy_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            agent = self.SlowCapacityAgent(settings(database))
            before = agent.registry_configuration()
            before_audit_count = len(before["recent_audit"])

            with self.assertRaises(CapacityValidationError):
                agent.update_cadence(
                    {
                        "expected_revision": before["revision"],
                        "reason": "Try unsafe faster meter cadence",
                        "device_overrides": [
                            {
                                "device_id": "le01mp-200",
                                "interval_seconds": 10,
                            }
                        ],
                    },
                    actor="operator:test",
                )

            after = agent.registry_configuration()
            self.assertEqual(after["revision"], before["revision"])
            self.assertEqual(after["cadence"], before["cadence"])
            self.assertEqual(len(after["recent_audit"]), before_audit_count)

    def test_deactivation_is_not_blocked_by_already_unsafe_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            agent = self.SlowCapacityAgent(settings(database))
            before = agent.registry_configuration()

            updated = agent.update_registry(
                {
                    "expected_revision": before["revision"],
                    "reason": "Disable one active temperature target",
                    "targets": [
                        {
                            "target_id": "xjp60d:106-04",
                            "lifecycle": "disabled",
                        }
                    ],
                },
                actor="operator:test",
            )

            self.assertEqual(updated["revision"], before["revision"] + 1)
            target = next(
                item
                for item in updated["targets"]
                if item["target_id"] == "xjp60d:106-04"
            )
            self.assertFalse(target["poll_eligible"])


if __name__ == "__main__":
    unittest.main()
