from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "infrastructure" / "compose" / "central-smoke.sh"


class CentralSmokeAuthContractTests(unittest.TestCase):
    def test_script_parses(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SMOKE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_smoke_reads_auth_mode_from_runtime_environment(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn('AUTH_MODE="$(read_env AUTH_MODE disabled)"', text)
        self.assertIn('authenticated_mode = auth_mode != "disabled"', text)
        self.assertIn('if authenticated_mode:', text)

    def test_authenticated_rest_smoke_expects_fail_closed_401(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn(
            'expect_http_status("/api/v1/telemetry/latest?limit=1", 401)',
            text,
        )
        self.assertIn(
            'expect_http_status(f"/api/v1/telemetry/history?{query}", 401)',
            text,
        )
        self.assertIn(
            "Central smoke protected REST: anonymous access rejected as expected",
            text,
        )

    def test_disabled_mode_keeps_positive_telemetry_smoke(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn('latest = load_json("/api/v1/telemetry/latest?limit=1")', text)
        self.assertIn('history = load_json(f"/api/v1/telemetry/history?{query}")', text)
        self.assertIn('if auth_mode == "disabled":', text)

    def test_authenticated_websocket_smoke_proves_missing_token_rejection(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn('"access_token": ""', text)
        self.assertIn('payload.get("code") != "missing_bearer_token"', text)
        self.assertIn(
            "Central smoke protected WebSocket: anonymous access rejected as expected",
            text,
        )

    def test_smoke_does_not_accept_operator_credentials(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        forbidden = (
            "AUTH_LOCAL_PRIVATE_KEY",
            "AUTH_LOCAL_PUBLIC_KEY",
            "NEXOLAB_LOCAL_AUTH_PASSWORD",
            "operator-password",
            "access_token_file",
        )
        for marker in forbidden:
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
