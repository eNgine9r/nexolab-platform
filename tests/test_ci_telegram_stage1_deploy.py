from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-telegram-miniapp-stage1.sh"


class TelegramStage1DeployPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stage1_is_miniapp_only_and_explicitly_approved(self) -> None:
        self.assertIn("--approve-miniapp-only", self.text)
        self.assertIn('[[ "$EUID" -eq 0 ]]', self.text)
        self.assertIn("TELEGRAM_ENABLED=false", self.text)
        self.assertIn("TELEGRAM_MINIAPP_ENABLED=true", self.text)
        self.assertNotIn("TELEGRAM_ENABLED=true", self.text)

    def test_stage1_targets_only_gateway_without_dependency_restart(self) -> None:
        self.assertIn('up -d --no-deps --no-build telegram-gateway', self.text)
        self.assertIn('python3 -m app.runtime_secret_permissions', self.text)
        self.assertIn('nexolab-central-telegram-gateway-1', self.text)
        self.assertIn('core container identity changed', self.text)
        self.assertIn('Tailscale Serve topology changed', self.text)

    def test_failure_rollback_is_bounded_to_new_gateway_container(self) -> None:
        self.assertIn('rm -sf telegram-gateway', self.text)
        self.assertNotIn('docker compose down', self.text)
        self.assertNotIn('docker volume rm', self.text)
        self.assertNotIn('down -v', self.text)

    def test_telemetry_health_uses_controlled_central_bind_contract(self) -> None:
        self.assertIn('CENTRAL_BIND="$(env_value "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS 127.0.0.1)"', self.text)
        self.assertIn('CENTRAL_API_PORT="$(env_value "$CENTRAL_ENV" CENTRAL_API_PORT 8082)"', self.text)
        self.assertIn('TELEMETRY_READY_URL="http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/health/ready"', self.text)
        self.assertNotIn('http://127.0.0.1:8082/health/ready', self.text)

    def test_health_contract_proves_delivery_worker_is_off(self) -> None:
        self.assertIn("p.get('delivery_enabled') is False", self.text)
        self.assertIn("p.get('miniapp_enabled') is True", self.text)
        self.assertIn("p.get('running') is False", self.text)
        self.assertIn('127.0.0.1:8090/health/ready', self.text)


if __name__ == "__main__":
    unittest.main()
