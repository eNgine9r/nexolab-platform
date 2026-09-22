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

    def test_repository_recovery_tooling_is_known_deployment_runtime(self) -> None:
        result = classify(["scripts/rebaseline-device-agent-recovery.py"])
        self.assertEqual(result["classes"], ["deployment_runtime"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_ssd_migration_regression_is_known_deployment_runtime(self) -> None:
        result = classify(
            [
                "scripts/migrate-raspberry-pi-root-to-ssd.sh",
                "scripts/tests/test_ssd_root_mountpoint_contract.py",
                "scripts/tests/standalone-offline-runtime-contract.sh",
                "docs/operations/issue-968-ssd-root-migration.md",
                ".project/CURRENT_STATE.md",
            ]
        )
        self.assertIn("deployment_runtime", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_remote_admin_reliability_is_known_deployment_runtime(self) -> None:
        result = classify(
            [
                "scripts/diagnose-raspberry-pi-remote-admin.sh",
                "scripts/install-raspberry-pi-persistent-journal.sh",
                "scripts/install-raspberry-pi-remote-admin.sh",
                "scripts/tests/standalone-offline-runtime-contract.sh",
                "scripts/tests/test_remote_admin_reliability.py",
                "infrastructure/systemd/journald/60-nexolab-persistent.conf",
                "infrastructure/systemd/user/nexolab-remote-desktop-commander.service",
                "docs/operations/raspberry-pi-remote-admin-reliability.md",
                ".project/CURRENT_STATE.md",
            ]
        )
        self.assertEqual(result["classes"], ["deployment_runtime"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_disaster_recovery_acceptance_tooling_is_known_deployment_runtime(self) -> None:
        for path in (
            "scripts/run-disaster-recovery-acceptance.sh",
            "tests/test_disaster_recovery_assets.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertEqual(result["classes"], ["deployment_runtime"])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [])
                self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_disaster_recovery_combined_fixture_routes_only_offline_external_lane(self) -> None:
        result = classify(
            [
                "infrastructure/compose/compose.disaster-recovery.yaml",
                "scripts/run-disaster-recovery-acceptance.sh",
                "tests/test_disaster_recovery_assets.py",
            ]
        )
        verification = result["verification"]
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(verification["dashboard_mode"], "none")
        self.assertFalse(verification["refrigeration_browser"])
        self.assertTrue(verification["offline_bundle"])
        self.assertEqual(verification["required_external_workflows"], ["Offline Bundle"])

    def test_unregistered_recovery_tooling_remains_fail_closed(self) -> None:
        path = "scripts/run-disaster-recovery-unregistered.sh"
        result = classify([path])
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [path])
        self.assertEqual(
            set(result["verification"]["required_external_workflows"]),
            {
                "Authenticated Dashboard Acceptance",
                "Offline Bundle",
                "Refrigeration Browser Acceptance",
            },
        )

    def test_issue_768_representative_file_set_does_not_broaden_as_unknown(self) -> None:
        result = classify(
            [
                ".project/ACTIVE_SPRINT.json",
                ".project/BLOCKERS.md",
                ".project/CURRENT_STATE.md",
                ".project/LAST_CHECKPOINT.json",
                "docs/operations/device-agent-recovery-rebaseline.md",
                "docs/operations/edge-sqlite-cutover-recovery.md",
                "scripts/deploy-current-head-raspberry-pi.sh",
                "scripts/rebaseline-device-agent-recovery.py",
                "scripts/tests/test_rebaseline_device_agent_recovery.py",
            ]
        )
        self.assertIn("deployment_runtime", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_edge_image_workflow_registers_and_validates_rs485_config_changes(self) -> None:
        workflow = Path('.github/workflows/edge-image.yml').read_text(encoding='utf-8')
        self.assertGreaterEqual(workflow.count('config/edge/*-register-map.yaml'), 2)
        self.assertGreaterEqual(workflow.count('config/edge/rs485-device-registry.yaml'), 2)
        self.assertIn('Validate RS-485 registry and register maps', workflow)
        self.assertIn('yaml.safe_load', workflow)
        self.assertIn("missing referenced register map", workflow)

    def test_rs485_acquisition_surfaces_are_known_device_agent_paths(self) -> None:
        for path in (
            "config/edge/eastron-sdm120m-v2.4-register-map.yaml",
            "config/edge/rs485-device-registry.yaml",
            "scripts/run-acquisition-scale-acceptance.py",
            "tools/rs485_discovery/scan_rs485.py",
            "tools/rs485_discovery/test_scan_rs485.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertIn("device_agent", result["classes"])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [])

    def test_unknown_neighboring_acquisition_paths_still_fail_closed(self) -> None:
        for path in (
            "config/edge/unclassified-device-profile.json",
            "scripts/run-unclassified-acquisition-tool.py",
            "tools/other_discovery/scan.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertTrue(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [path])

    def test_issue_1105_path_set_avoids_impossible_refrigeration_route(self) -> None:
        result = classify(
            [
                "config/edge/eastron-sdm120m-v2.4-register-map.yaml",
                "config/edge/rs485-device-registry.yaml",
                "scripts/run-acquisition-scale-acceptance.py",
                "tools/rs485_discovery/scan_rs485.py",
                "tools/rs485_discovery/test_scan_rs485.py",
                "services/device-agent/sdm120.py",
                "services/device-agent/modbus_rtu.py",
                "src/components/energy/energy-workspace.tsx",
                "src/features/acquisition/cadence-client.ts",
                "e2e/energy.production.e2e.ts",
                "infrastructure/compose/compose.hardware.yaml",
                ".project/CURRENT_STATE.md",
            ]
        )
        verification = result["verification"]
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(verification["dashboard_mode"], "full")
        self.assertTrue(verification["offline_bundle"])
        self.assertFalse(verification["refrigeration_browser"])
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {"Authenticated Dashboard Acceptance", "Offline Bundle"},
        )

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

    def test_settings_only_routes_focused_dashboard_without_expensive_unrelated_lanes(self) -> None:
        result = classify(["src/components/settings/settings-workspace.tsx"])
        verification = result["verification"]
        self.assertEqual(verification["dashboard_mode"], "focused")
        self.assertEqual(verification["dashboard_test_match"], "settings.production.e2e.ts")
        self.assertFalse(verification["offline_bundle"])
        self.assertFalse(verification["refrigeration_browser"])
        self.assertEqual(
            verification["required_external_workflows"],
            ["Authenticated Dashboard Acceptance"],
        )

    def test_refrigeration_change_requires_refrigeration_browser_without_offline_bundle(self) -> None:
        result = classify(["src/features/refrigeration/layout.ts"])
        verification = result["verification"]
        self.assertTrue(verification["refrigeration_browser"])
        self.assertFalse(verification["offline_bundle"])
        self.assertIn(
            "Refrigeration Browser Acceptance",
            verification["required_external_workflows"],
        )

    def test_shared_security_and_telemetry_require_full_dashboard_acceptance(self) -> None:
        for path in (
            "src/features/security/session.ts",
            "src/lib/telemetry/websocket-client.ts",
            "src/features/acquisition/cadence.ts",
        ):
            with self.subTest(path=path):
                verification = classify([path])["verification"]
                self.assertEqual(verification["dashboard_mode"], "full")
                self.assertIsNone(verification["dashboard_test_match"])
                self.assertIn(
                    "Authenticated Dashboard Acceptance",
                    verification["required_external_workflows"],
                )

    def test_offline_contract_change_requires_offline_bundle(self) -> None:
        result = classify(["infrastructure/compose/compose.central.yaml"])
        verification = result["verification"]
        self.assertTrue(verification["offline_bundle"])
        self.assertIn("Offline Bundle", verification["required_external_workflows"])

    def test_device_agent_runtime_surface_requires_offline_and_full_dashboard(self) -> None:
        verification = classify(["services/device-agent/modbus_reader.py"])["verification"]
        self.assertTrue(verification["offline_bundle"])
        self.assertEqual(verification["dashboard_mode"], "full")
        self.assertFalse(verification["refrigeration_browser"])
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {"Authenticated Dashboard Acceptance", "Offline Bundle"},
        )

    def test_container_policy_test_family_is_known_security_supply_chain(self) -> None:
        for path in (
            "tests/test_container_supply_chain_policy.py",
            "tests/test_container_vulnerability_policy.py",
            "tests/test_container_release_manifest.py",
            "tests/test_container_release_aggregate.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertIn("security_supply_chain", result["classes"])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [])
                self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_unregistered_container_test_still_fails_closed(self) -> None:
        result = classify(["tests/test_container_unregistered.py"])
        self.assertEqual(result["classes"], ["cross_surface_or_unknown"])
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["unknown_files"], ["tests/test_container_unregistered.py"])

    def test_inspection_tooling_is_known_security_without_product_external_lanes(self) -> None:
        result = classify(
            [
                "scripts/inspection/opera_tailscale_login.py",
                "scripts/inspection/systemd/nexolab-opera-inspection-login.socket",
                "tests/test_opera_tailscale_inspection.py",
                "docs/operations/opera-tailscale-inspection.md",
                ".project/CURRENT_STATE.md",
            ]
        )
        self.assertEqual(result["classes"], ["security_tooling"])
        self.assertTrue(result["needs_full_quality"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_security_policy_pr_does_not_force_unrelated_external_acceptance(self) -> None:
        result = classify(
            [
                "security/vulnerability-exceptions.json",
                "tests/test_container_supply_chain_policy.py",
                "docs/operations/device-agent-security-note.md",
                ".project/CURRENT_STATE.md",
            ]
        )
        self.assertEqual(result["classes"], ["security_supply_chain"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_core_ci_governance_does_not_force_unrelated_external_acceptance(self) -> None:
        result = classify([".github/workflows/ci.yml"])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_core_only_toolchain_changes_do_not_require_unrelated_external_lanes(self) -> None:
        for path in (
            "eslint.config.mjs",
            "tsconfig.json",
            "vitest.config.ts",
            "playwright.security.config.ts",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_formatter_tooling_changes_require_core_quality_without_product_external_lanes(self) -> None:
        result = classify(
            [
                ".prettierignore",
                "scripts/tests/lint-staged-v17.mjs",
                ".project/ACTIVE_SPRINT.json",
                ".project/LAST_CHECKPOINT.json",
            ]
        )
        self.assertEqual(result["classes"], ["dependency_toolchain"])
        self.assertTrue(result["needs_full_quality"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_dashboard_playwright_config_requires_dashboard_only(self) -> None:
        verification = classify(["playwright.dashboard.config.ts"])["verification"]
        self.assertEqual(
            verification["required_external_workflows"],
            ["Authenticated Dashboard Acceptance"],
        )

    def test_refrigeration_playwright_config_requires_refrigeration_only(self) -> None:
        verification = classify(["playwright.production.config.ts"])["verification"]
        self.assertEqual(
            verification["required_external_workflows"],
            ["Refrigeration Browser Acceptance"],
        )

    def test_next_runtime_config_requires_dashboard_and_offline_only(self) -> None:
        verification = classify(["next.config.ts"])["verification"]
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {"Authenticated Dashboard Acceptance", "Offline Bundle"},
        )

    def test_package_lock_keeps_all_shared_external_lanes(self) -> None:
        verification = classify(["package-lock.json"])["verification"]
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {
                "Authenticated Dashboard Acceptance",
                "Offline Bundle",
                "Refrigeration Browser Acceptance",
            },
        )

    def test_routing_classifier_change_requires_all_routed_external_lanes(self) -> None:
        verification = classify(["scripts/classify-ci-impact.py"])["verification"]
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {
                "Authenticated Dashboard Acceptance",
                "Offline Bundle",
                "Refrigeration Browser Acceptance",
            },
        )

    def test_ci_policy_tests_are_known_governance_without_expensive_external_lanes(self) -> None:
        result = classify(["tests/test_ci_risk_aware_verification.py"])
        self.assertIn("ci_governance", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_clean_candidate_helper_is_known_governance_without_expensive_external_lanes(self) -> None:
        result = classify(["scripts/prepare-clean-verification-worktree.sh"])
        self.assertIn("ci_governance", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_frontend_release_tooling_is_known_deployment_runtime(self) -> None:
        for path in (
            "scripts/build-frontend-release-artifact.sh",
            "scripts/tests/test_raspberry_pi_frontend_release.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertEqual(result["classes"], ["deployment_runtime"])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [])
                self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_version_manager_tooling_is_known_deployment_runtime(self) -> None:
        for path in (
            "scripts/nexolab-version-manager.py",
            "scripts/tests/test_nexolab_version_manager.py",
        ):
            with self.subTest(path=path):
                result = classify([path])
                self.assertEqual(result["classes"], ["deployment_runtime"])
                self.assertFalse(result["fail_closed"])
                self.assertEqual(result["unknown_files"], [])
                self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_version_manager_with_offline_installer_routes_only_offline_bundle(self) -> None:
        result = classify(
            [
                "scripts/nexolab-version-manager.py",
                "scripts/tests/test_nexolab_version_manager.py",
                "scripts/install-offline-bundle.sh",
            ]
        )
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(
            result["verification"]["required_external_workflows"],
            ["Offline Bundle"],
        )

    def test_frontend_release_tooling_with_dashboard_dockerfile_requires_offline_only(self) -> None:
        result = classify(
            [
                "scripts/build-frontend-release-artifact.sh",
                "scripts/tests/test_raspberry_pi_frontend_release.py",
                "infrastructure/offline/Dockerfile.dashboard",
            ]
        )
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(
            result["verification"]["required_external_workflows"],
            ["Offline Bundle"],
        )

    def test_unknown_path_broadens_external_verification_fail_closed(self) -> None:
        result = classify(["new-area/unknown.file"])
        verification = result["verification"]
        self.assertTrue(result["fail_closed"])
        self.assertTrue(verification["offline_bundle"])
        self.assertTrue(verification["refrigeration_browser"])
        self.assertEqual(verification["dashboard_mode"], "full")
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {
                "Authenticated Dashboard Acceptance",
                "Offline Bundle",
                "Refrigeration Browser Acceptance",
            },
        )

    def test_state_only_requires_no_external_product_workflows(self) -> None:
        result = classify([".project/CURRENT_STATE.md"])
        self.assertEqual(result["verification"]["required_external_workflows"], [])

    def test_empty_change_set_fails_closed(self) -> None:
        result = classify([])
        self.assertEqual(result["classes"], ["cross_surface_or_unknown"])
        self.assertTrue(result["fail_closed"])
        self.assertTrue(result["needs_full_quality"])


    def test_telegram_cross_contract_test_is_known_without_unrelated_browser_lanes(self) -> None:
        result = classify(["tests/telegram-daily-report-schema-contract.test.ts"])
        verification = result["verification"]
        self.assertIn("backend", result["classes"])
        self.assertIn("frontend", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertFalse(verification["offline_bundle"])
        self.assertFalse(verification["refrigeration_browser"])
        self.assertEqual(verification["dashboard_mode"], "none")
        self.assertEqual(
            verification["required_external_workflows"],
            ["Telegram Gateway"],
        )

    def test_issue_855_path_set_routes_only_required_telegram_external_lanes(self) -> None:
        result = classify(
            [
                ".project/ACTIVE_SPRINT.json",
                ".project/BLOCKERS.md",
                ".project/CURRENT_STATE.md",
                ".project/LAST_CHECKPOINT.json",
                "services/telegram-gateway/tests/support.py",
                "services/telegram-gateway/tests/test_miniapp.py",
                "src/components/telegram/telegram-miniapp-report.test.tsx",
                "src/components/telegram/telegram-miniapp-report.tsx",
                "tests/telegram-daily-report-schema-contract.test.ts",
            ]
        )
        verification = result["verification"]
        self.assertFalse(result["fail_closed"])
        self.assertEqual(result["unknown_files"], [])
        self.assertEqual(verification["dashboard_mode"], "none")
        self.assertFalse(verification["refrigeration_browser"])
        self.assertTrue(verification["offline_bundle"])
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {"Offline Bundle", "Telegram Gateway", "Container Supply Chain"},
        )

    def test_unregistered_telegram_root_test_still_fails_closed(self) -> None:
        result = classify(["tests/telegram_contract.py"])
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["unknown_files"], ["tests/telegram_contract.py"])

    def test_telegram_gateway_requires_service_ci_and_offline_bundle(self) -> None:
        result = classify(["services/telegram-gateway/app/main.py"])
        verification = result["verification"]
        self.assertIn("backend", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertTrue(verification["offline_bundle"])
        self.assertFalse(verification["refrigeration_browser"])
        self.assertEqual(verification["dashboard_mode"], "none")
        self.assertEqual(
            set(verification["required_external_workflows"]),
            {"Offline Bundle", "Telegram Gateway", "Container Supply Chain"},
        )

    def test_telegram_compose_overlay_requires_gateway_and_offline_ci(self) -> None:
        result = classify(["infrastructure/compose/compose.telegram.yaml"])
        self.assertIn("deployment_runtime", result["classes"])
        self.assertFalse(result["fail_closed"])
        self.assertEqual(
            set(result["verification"]["required_external_workflows"]),
            {"Offline Bundle", "Telegram Gateway"},
        )

    def test_telegram_container_inventory_requires_supply_chain(self) -> None:
        result = classify(["security/container-images.json"])
        self.assertFalse(result["fail_closed"])
        self.assertIn(
            "Container Supply Chain",
            result["verification"]["required_external_workflows"],
        )


if __name__ == "__main__":
    unittest.main()
