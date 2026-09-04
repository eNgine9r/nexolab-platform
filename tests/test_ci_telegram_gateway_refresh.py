from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-telegram-gateway-refresh.sh"


class TelegramGatewayRefreshPolicyTests(unittest.TestCase):
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

    def test_missing_approval_fails_before_any_runtime_access(self) -> None:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--expected-source-sha",
                "0" * 40,
                "--expected-current-image-id",
                "sha256:" + "0" * 64,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("explicit --approve-gateway-refresh is required", result.stderr)

    def test_refresh_requires_exact_source_image_root_and_approval(self) -> None:
        self.assertIn("--expected-source-sha", self.text)
        self.assertIn("--expected-current-image-id", self.text)
        self.assertIn("--approve-gateway-refresh", self.text)
        self.assertIn('[[ "$EUID" -eq 0 ]]', self.text)
        self.assertIn("source SHA mismatch", self.text)
        self.assertIn("expected source is not current origin/main", self.text)
        self.assertIn("source worktree is not clean", self.text)
        self.assertIn("--untracked-files=all", self.text)
        self.assertIn("current Gateway image changed since approval preparation", self.text)

    def test_protected_topic_env_is_fail_closed_and_not_printed(self) -> None:
        self.assertIn('counts.get("TELEGRAM_ENABLED") == 1', self.text)
        self.assertIn('values.get("TELEGRAM_ENABLED") == "false"', self.text)
        self.assertIn('counts.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID") == 1', self.text)
        self.assertIn("thread.isdigit() and int(thread) > 0", self.text)
        self.assertNotIn('cat "$TELEGRAM_ENV"', self.text)
        self.assertNotIn("print(thread)", self.text)
        self.assertIn('runtime_secret_permissions --secret-dir "$SECRET_DIR"', self.text)
        self.assertGreaterEqual(self.text.count("TELEGRAM_GATEWAY_SECRETS_DIR=$SECRET_DIR"), 2)

    def test_existing_gateway_and_scheduler_are_safe_before_mutation(self) -> None:
        self.assertIn("persistent Telegram Gateway is missing", self.text)
        self.assertIn("existing Gateway safety boundary is not closed", self.text)
        self.assertIn("gateway_safety_ready", self.text)
        self.assertIn("DAILY_REPORTS_SCHEDULER_ENABLED=false", self.text)
        self.assertIn("weekday scheduler must remain disabled", self.text)
        self.assertIn("p.get(\"delivery_enabled\") is False", self.text)
        self.assertIn("p.get(\"running\") is False", self.text)
        self.assertIn("p.get(\"last_send_at\") is None", self.text)

    def test_refresh_recreates_only_gateway_without_volume_deletion(self) -> None:
        self.assertIn("up -d --no-deps --no-build --force-recreate telegram-gateway", self.text)
        self.assertIn("Gateway delivery volume identity changed", self.text)
        self.assertNotIn("docker compose down", self.text)
        self.assertNotIn("docker volume rm", self.text)
        self.assertNotIn("down -v", self.text)

    def test_rollback_pins_previous_image_and_rechecks_safety(self) -> None:
        self.assertIn('docker tag "$OLD_IMAGE_ID" "$ROLLBACK_IMAGE_TAG"', self.text)
        self.assertIn("Refresh failed; restoring previous Telegram Gateway image", self.text)
        self.assertIn("Rollback verification: PASS", self.text)
        self.assertIn("$OLD_IMAGE_ID", self.text)
        self.assertIn("$OUTBOX_VOLUME", self.text)
        self.assertIn("gateway_safety_ready", self.text)

    def test_post_refresh_proves_exact_image_topic_and_worker_off(self) -> None:
        self.assertIn("refreshed Gateway image mismatch", self.text)
        self.assertIn('env.get("TELEGRAM_ENABLED") == "false"', self.text)
        self.assertIn('env.get("TELEGRAM_MINIAPP_ENABLED") == "true"', self.text)
        self.assertIn("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID", self.text)
        self.assertIn("p.get('delivery_enabled') is False", self.text)
        self.assertIn("p.get('running') is False", self.text)
        self.assertIn("p.get('last_send_at') is None", self.text)

    def test_core_and_tailscale_identity_are_preserved(self) -> None:
        self.assertIn("core container identity changed", self.text)
        self.assertIn("Tailscale Serve topology changed", self.text)
        self.assertIn("Core container identities unchanged: PASS", self.text)
        self.assertIn("Dashboard/Telemetry/Mini App remained healthy: PASS", self.text)

    def test_refresh_never_enables_delivery_or_scheduler_or_sends(self) -> None:
        self.assertNotIn("TELEGRAM_ENABLED=true", self.text)
        self.assertNotIn("DAILY_REPORTS_SCHEDULER_ENABLED=true", self.text)
        self.assertNotIn("SEND_EXACT_SNAPSHOT_ONCE", self.text)
        self.assertNotIn("app.controlled_send", self.text)
        self.assertIn("No Telegram delivery worker started and no report send was requested", self.text)


if __name__ == "__main__":
    unittest.main()
