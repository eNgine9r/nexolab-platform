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


class ProjectStateValidationTests(unittest.TestCase):
    def test_active_state_accepts_required_execution_policy(self) -> None:
        document = {
            "schema_version": 1,
            "project": "NEXOLAB",
            "profile": "LOCAL_LAN",
            "sprint": {"id": "TEST", "status": "in_progress"},
            "execution_policy": {
                "verification_policy": "proportional_to_changed_product_surface"
            },
            "tasks": [{"issue": 1}, {"issue": 2}],
        }
        MODULE.validate_active(document)

    def test_active_state_rejects_duplicate_issue_entries(self) -> None:
        document = {
            "schema_version": 1,
            "project": "NEXOLAB",
            "profile": "LOCAL_LAN",
            "sprint": {"id": "TEST", "status": "in_progress"},
            "execution_policy": {
                "verification_policy": "proportional_to_changed_product_surface"
            },
            "tasks": [{"issue": 7}, {"issue": 7}],
        }
        with self.assertRaisesRegex(ValueError, "duplicate issue"):
            MODULE.validate_active(document)

    def test_active_state_rejects_weakened_verification_policy(self) -> None:
        document = {
            "schema_version": 1,
            "project": "NEXOLAB",
            "profile": "LOCAL_LAN",
            "sprint": {"id": "TEST", "status": "in_progress"},
            "execution_policy": {"verification_policy": "skip_ci"},
            "tasks": [],
        }
        with self.assertRaisesRegex(ValueError, "proportional"):
            MODULE.validate_active(document)

    def test_checkpoint_rejects_hardware_or_modbus_write_boundary(self) -> None:
        document = {
            "schema_version": 1,
            "project": "NEXOLAB",
            "profile": "LOCAL_LAN",
            "timestamp": "2026-08-22T10:00:00Z",
            "event": "test",
            "safety": {"modbus_write": "none", "hardware_write": "performed"},
        }
        with self.assertRaisesRegex(ValueError, "Modbus/hardware write"):
            MODULE.validate_checkpoint(document)

    def test_checkpoint_accepts_read_only_boundary(self) -> None:
        document = {
            "schema_version": 1,
            "project": "NEXOLAB",
            "profile": "LOCAL_LAN",
            "timestamp": "2026-08-22T10:00:00Z",
            "event": "test",
            "safety": {"modbus_write": "none", "hardware_write": "none"},
        }
        MODULE.validate_checkpoint(document)


if __name__ == "__main__":
    unittest.main()
