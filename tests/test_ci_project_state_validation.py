from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-project-state.py"
SPEC = importlib.util.spec_from_file_location("validate_project_state", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA_A = "a" * 40
SHA_B = "b" * 40


def active_document() -> dict:
    return {
        "schema_version": 2,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": {"id": "TEST", "status": "in_progress"},
        "execution_policy": {
            "verification_policy": "proportional_to_changed_product_surface"
        },
        "baselines": {
            "accepted_product_sha": SHA_A,
            "deployed_product_sha": SHA_B,
        },
        "selection": {
            "active_work_package": {
                "issue": 7,
                "title": "Active",
                "branch": "chore/7",
            },
            "next_work_package": None,
        },
        "work_packages": [
            {
                "issue": 7,
                "title": "Active",
                "priority": "high",
                "lifecycle": "in_progress",
                "evidence": {},
            }
        ],
        "maintenance_actions": [],
        "observations": [],
        "safety": {
            "modbus_write": "none",
            "hardware_write": "none",
            "production_cutover_authorized": False,
        },
    }


def checkpoint_document() -> dict:
    return {
        "schema_version": 2,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": "TEST",
        "timestamp": "2026-08-22T11:00:00Z",
        "actor": "ChatGPT",
        "event": "test",
        "baselines": {
            "accepted_product_sha": SHA_A,
            "deployed_product_sha": SHA_B,
        },
        "active_work": {"issue": 7, "title": "Active", "branch": "chore/7"},
        "evidence_snapshot": {},
        "observations": [],
        "next_action": "Continue",
        "safety": {
            "modbus_write": "none",
            "hardware_write": "none",
            "production_cutover_authorized": False,
        },
    }


class ProjectStateValidationTests(unittest.TestCase):
    def test_active_state_accepts_v2_contract(self) -> None:
        MODULE.validate_active(active_document())

    def test_active_state_accepts_ready_and_review_lifecycles(self) -> None:
        ready = active_document()
        ready["selection"]["active_work_package"] = None
        ready["work_packages"][0]["lifecycle"] = "ready"
        MODULE.validate_active(ready)

        review = active_document()
        review["work_packages"][0]["lifecycle"] = "review"
        MODULE.validate_active(review)

    def test_active_state_rejects_v1_schema(self) -> None:
        document = active_document()
        document["schema_version"] = 1
        with self.assertRaisesRegex(ValueError, "schema_version must be 2"):
            MODULE.validate_active(document)

    def test_active_state_rejects_duplicate_issue_entries(self) -> None:
        document = active_document()
        document["work_packages"].append(dict(document["work_packages"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate issue"):
            MODULE.validate_active(document)

    def test_active_state_rejects_weakened_verification_policy(self) -> None:
        document = active_document()
        document["execution_policy"]["verification_policy"] = "skip_ci"
        with self.assertRaisesRegex(ValueError, "proportional"):
            MODULE.validate_active(document)

    def test_active_state_rejects_invalid_sha(self) -> None:
        document = active_document()
        document["baselines"]["accepted_product_sha"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "40-character git SHA"):
            MODULE.validate_active(document)

    def test_active_state_rejects_volatile_main_sha_invariant(self) -> None:
        document = active_document()
        document["repository_main_sha"] = SHA_A
        with self.assertRaisesRegex(ValueError, "volatile GitHub/repository observation"):
            MODULE.validate_active(document)

    def test_active_state_rejects_equivalent_main_head_invariant(self) -> None:
        document = active_document()
        document["main_head_sha"] = SHA_A
        with self.assertRaisesRegex(ValueError, "volatile GitHub/repository observation"):
            MODULE.validate_active(document)

    def test_active_state_rejects_durable_merge_sha(self) -> None:
        document = active_document()
        document["work_packages"][0]["evidence"]["release_merge_sha"] = SHA_A
        with self.assertRaisesRegex(ValueError, "volatile GitHub/repository observation"):
            MODULE.validate_active(document)

    def test_observation_may_record_historical_merge_sha(self) -> None:
        document = active_document()
        document["observations"].append(
            {
                "source": "github",
                "observed_at": "2026-08-22T11:00:00Z",
                "kind": "historical_merge",
                "data": {"issue": 1, "merge_sha": SHA_A},
            }
        )
        MODULE.validate_active(document)

    def test_active_selection_must_reference_active_lifecycle(self) -> None:
        document = active_document()
        document["work_packages"][0]["lifecycle"] = "completed"
        with self.assertRaisesRegex(ValueError, "in_progress or review"):
            MODULE.validate_active(document)

    def test_dependencies_must_reference_other_known_issues(self) -> None:
        document = active_document()
        document["selection"]["active_work_package"] = None
        document["work_packages"][0]["lifecycle"] = "ready"
        document["work_packages"][0]["depends_on"] = [99]
        with self.assertRaisesRegex(ValueError, "invalid dependency 99"):
            MODULE.validate_active(document)

    def test_checkpoint_rejects_hardware_or_modbus_write_boundary(self) -> None:
        document = checkpoint_document()
        document["safety"]["hardware_write"] = "performed"
        with self.assertRaisesRegex(ValueError, "Modbus/hardware write"):
            MODULE.validate_checkpoint(document)

    def test_checkpoint_rejects_production_cutover_authorization(self) -> None:
        document = checkpoint_document()
        document["safety"]["production_cutover_authorized"] = True
        with self.assertRaisesRegex(ValueError, "production cutover"):
            MODULE.validate_checkpoint(document)

    def test_checkpoint_accepts_read_only_boundary(self) -> None:
        MODULE.validate_checkpoint(checkpoint_document())


if __name__ == "__main__":
    unittest.main()
