from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "classify-ci-impact.py"
SPEC = importlib.util.spec_from_file_location("classify_ci_impact", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
classify = MODULE.classify


class ChangeImpactClassifierTests(unittest.TestCase):
    def test_state_only_is_lightweight(self) -> None:
        result = classify(
            [
                ".project/CURRENT_STATE.md",
                ".project/ACTIVE_SPRINT.json",
                ".project/BLOCKERS.md",
                ".project/LAST_CHECKPOINT.json",
            ]
        )
        self.assertEqual(result["classes"], ["state_only"])
        self.assertTrue(result["state_only"])
        self.assertFalse(result["needs_full_quality"])
        self.assertFalse(result["fail_closed"])

    def test_docs_only_keeps_full_formatting_quality(self) -> None:
        result = classify(["docs/operations/runbook.md", "README.md"])
        self.assertEqual(result["classes"], ["docs_only"])
        self.assertTrue(result["docs_only"])
        self.assertTrue(result["needs_full_quality"])
        self.assertFalse(result["fail_closed"])

    def test_frontend_requires_full_quality(self) -> None:
        result = classify(["src/features/live/export.ts"])
        self.assertIn("frontend", result["classes"])
        self.assertTrue(result["needs_full_quality"])

    def test_backend_and_migration_are_multi_class(self) -> None:
        result = classify(
            [
                "services/telemetry-service/app/main.py",
                "services/telemetry-service/migrations/versions/example.py",
            ]
        )
        self.assertIn("backend", result["classes"])
        self.assertIn("database_migration", result["classes"])
        self.assertIn("cross_surface_or_unknown", result["classes"])
        self.assertTrue(result["needs_full_quality"])
        self.assertFalse(result["fail_closed"])

    def test_device_agent_and_deployment_are_multi_class(self) -> None:
        result = classify(
            [
                "services/device-agent/adaptive_scheduler.py",
                "infrastructure/compose/compose.central.yaml",
            ]
        )
        self.assertIn("device_agent", result["classes"])
        self.assertIn("deployment_runtime", result["classes"])
        self.assertTrue(result["needs_full_quality"])

    def test_dependency_and_ci_governance_require_full_quality(self) -> None:
        result = classify(["package-lock.json", ".github/workflows/ci.yml"])
        self.assertIn("dependency_toolchain", result["classes"])
        self.assertIn("ci_governance", result["classes"])
        self.assertTrue(result["needs_full_quality"])

    def test_unknown_path_fails_closed(self) -> None:
        result = classify(["new-area/unknown.file"])
        self.assertEqual(result["classes"], ["cross_surface_or_unknown"])
        self.assertTrue(result["needs_full_quality"])
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["unknown_files"], ["new-area/unknown.file"])

    def test_state_files_can_accompany_product_change_without_extra_class(self) -> None:
        result = classify(["src/app/page.tsx", ".project/CURRENT_STATE.md"])
        self.assertIn("frontend", result["classes"])
        self.assertNotIn("state_only", result["classes"])
        self.assertTrue(result["needs_full_quality"])

    def test_empty_change_set_fails_closed(self) -> None:
        result = classify([])
        self.assertEqual(result["classes"], ["cross_surface_or_unknown"])
        self.assertTrue(result["fail_closed"])
        self.assertTrue(result["needs_full_quality"])


if __name__ == "__main__":
    unittest.main()
