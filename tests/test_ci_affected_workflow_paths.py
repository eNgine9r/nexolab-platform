from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

DOMAIN_BROWSER_WORKFLOWS = (
    "alerts-browser-acceptance.yml",
    "nodes-browser-acceptance.yml",
    "rendered-reports-browser-acceptance.yml",
    "reports-browser-acceptance.yml",
    "test-sessions-browser-acceptance.yml",
)

HEAVY_BACKEND_WORKFLOWS = (
    "broker-control-acceptance.yml",
    "capacity-release-gate.yml",
    "device-agent-fleet-acceptance.yml",
    "disaster-recovery-browser.yml",
    "disaster-recovery-tls-fleet.yml",
    "mqtt-tls-fleet-acceptance.yml",
)

CACHED_NODE_WORKFLOWS = (
    "acquisition-scale-acceptance.yml",
    "alerts-browser-acceptance.yml",
    "authenticated-dashboard-acceptance.yml",
    "broker-control-acceptance.yml",
    "device-agent-fleet-acceptance.yml",
    "disaster-recovery-browser.yml",
    "mqtt-tls-fleet-acceptance.yml",
    "nodes-browser-acceptance.yml",
    "observability.yml",
    "offline-auth-acceptance.yml",
    "refrigeration-browser-acceptance.yml",
    "rendered-reports-browser-acceptance.yml",
    "reports-browser-acceptance.yml",
    "security-browser-acceptance.yml",
    "test-sessions-browser-acceptance.yml",
)


def _event_block(text: str, event: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(event)}:\n(?P<body>.*?)(?=^  [a-zA-Z_]+:|^permissions:|^concurrency:|^jobs:)",
        text,
    )
    if not match:
        raise AssertionError(f"{event} block not found")
    return match.group("body")


class AffectedWorkflowRoutingTests(unittest.TestCase):
    def test_domain_browser_lanes_do_not_fan_out_on_generic_security_changes(self) -> None:
        for name in DOMAIN_BROWSER_WORKFLOWS:
            with self.subTest(workflow=name):
                pull_request = _event_block((WORKFLOWS / name).read_text(encoding="utf-8"), "pull_request")
                self.assertNotIn('"src/features/security/**"', pull_request)
                self.assertNotIn('"services/telemetry-service/app/security/**"', pull_request)

    def test_heavy_backend_lanes_are_affected_on_pr_but_remain_deep_on_main(self) -> None:
        for name in HEAVY_BACKEND_WORKFLOWS:
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                pull_request = _event_block(text, "pull_request")
                push = _event_block(text, "push")
                self.assertNotIn('"services/telemetry-service/**"', pull_request)
                self.assertIn('"services/telemetry-service/**"', push)

    def test_container_supply_chain_pr_uses_dependency_image_boundaries(self) -> None:
        text = (WORKFLOWS / "container-supply-chain.yml").read_text(encoding="utf-8")
        pull_request = _event_block(text, "pull_request")
        push = _event_block(text, "push")
        self.assertNotIn('"services/device-agent/**"', pull_request)
        self.assertNotIn('"services/telemetry-service/**"', pull_request)
        self.assertIn('"services/device-agent/Dockerfile"', pull_request)
        self.assertIn('"services/device-agent/requirements.txt"', pull_request)
        self.assertIn('"services/telemetry-service/Dockerfile"', pull_request)
        self.assertIn('"services/telemetry-service/requirements.txt"', pull_request)
        self.assertIn('"services/device-agent/**"', push)
        self.assertIn('"services/telemetry-service/**"', push)

    def test_node_workflows_use_setup_node_cache(self) -> None:
        for name in CACHED_NODE_WORKFLOWS:
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertNotIn("package-manager-cache: false", text)
                self.assertIn("cache: npm", text)
                self.assertIn("cache-dependency-path: package-lock.json", text)

    def test_legacy_browser_install_steps_use_npm_ci(self) -> None:
        for name in (
            "alerts-browser-acceptance.yml",
            "nodes-browser-acceptance.yml",
            "rendered-reports-browser-acceptance.yml",
            "reports-browser-acceptance.yml",
            "observability.yml",
            "test-sessions-browser-acceptance.yml",
        ):
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertNotIn("npm install --no-audit", text)
                self.assertIn("npm ci", text)

    def test_browser_workflows_reuse_preinstalled_chrome(self) -> None:
        workflows = (
            "alerts-browser-acceptance.yml",
            "broker-control-acceptance.yml",
            "device-agent-fleet-acceptance.yml",
            "disaster-recovery-browser.yml",
            "mqtt-tls-fleet-acceptance.yml",
            "nodes-browser-acceptance.yml",
            "observability.yml",
            "rendered-reports-browser-acceptance.yml",
            "reports-browser-acceptance.yml",
            "test-sessions-browser-acceptance.yml",
        )
        for name in workflows:
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn("resolve-playwright-browser.sh", text)
                self.assertNotIn("npx playwright install --with-deps chromium", text)

        configs = (
            "playwright.alerts.config.ts",
            "playwright.broker-control.config.ts",
            "playwright.device-agent-fleet.config.ts",
            "playwright.disaster-recovery.config.ts",
            "playwright.nodes.config.ts",
            "playwright.observability.config.ts",
            "playwright.rendered-reports.config.ts",
            "playwright.reports.config.ts",
            "playwright.sessions.config.ts",
        )
        for name in configs:
            with self.subTest(config=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", text)
                self.assertIn("executablePath", text)


if __name__ == "__main__":
    unittest.main()
