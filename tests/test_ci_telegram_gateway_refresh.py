from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-telegram-gateway-refresh.sh"
RUNBOOK = ROOT / "docs" / "operations" / "telegram-gateway.md"
PROBE = ROOT / "scripts" / "telegram-gateway-boundary-runtime-proof.sh"


class TelegramGatewayRefreshPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.runbook = RUNBOOK.read_text(encoding="utf-8")
        self.probe = PROBE.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self) -> None:
        for path in (SCRIPT, PROBE):
            result = subprocess.run(
                ["bash", "-n", str(path)],
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
                "--expected-target-image-id",
                "sha256:" + "1" * 64,
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
        self.assertIn("--expected-target-image-id", self.text)
        self.assertIn("--approve-gateway-refresh", self.text)
        self.assertIn('[[ "$EUID" -eq 0 ]]', self.text)
        self.assertIn("source SHA mismatch", self.text)
        fetch = self.text.index('"${GIT[@]}" fetch --quiet origin main')
        remote = self.text.index("REMOTE_MAIN=")
        self.assertLess(fetch, remote)
        self.assertIn("expected source is not current origin/main", self.text)
        self.assertIn("source worktree is not clean", self.text)
        self.assertIn("--untracked-files=all", self.text)
        self.assertIn("current Gateway image changed since approval preparation", self.text)
        self.assertIn("pre-approved target Gateway image is unavailable locally", self.text)
        self.assertIn("target Gateway image source revision mismatch", self.text)


    def test_approval_candidate_build_uses_immutable_git_tree_context(self) -> None:
        self.assertIn('git archive --format=tar "$SOURCE_SHA:services/telegram-gateway"', self.runbook)
        self.assertIn('SOURCE_GATEWAY_TREE="$(git rev-parse "$SOURCE_SHA:services/telegram-gateway")"', self.runbook)
        self.assertIn('--label "io.nexolab.source-tree=$SOURCE_GATEWAY_TREE"', self.runbook)
        self.assertNotIn('docker build \\n  --label "org.opencontainers.image.revision=$SOURCE_SHA" \\n  --tag "$TARGET_TAG" \\n  services/telegram-gateway', self.runbook)
        self.assertIn('EXPECTED_GATEWAY_TREE="$(git rev-parse "${EXPECTED_SOURCE}:services/telegram-gateway")"', self.text)
        self.assertIn('target Gateway image source tree mismatch', self.text)
        revision_check = self.text.index('target Gateway image source revision mismatch')
        tree_check = self.text.index('target Gateway image source tree mismatch')
        capability = self.text.index('show "${EXPECTED_SOURCE}:${BOUNDARY_PROBE_PATH}"')
        mutation = self.text.index('MUTATED="1"', capability)
        self.assertLess(revision_check, capability)
        self.assertLess(tree_check, capability)
        self.assertLess(capability, mutation)


    def test_post_merge_runbook_refreshes_remote_before_pinning_and_runs_probe(self) -> None:
        fetch = self.runbook.index("git fetch --quiet origin main")
        source = self.runbook.index('SOURCE_SHA="$(git rev-parse HEAD)"')
        self.assertLess(fetch, source)
        self.assertIn("git switch main", self.runbook)
        self.assertIn("git merge --ff-only origin/main", self.runbook)
        self.assertIn('git show "$SOURCE_SHA:scripts/telegram-gateway-boundary-runtime-proof.sh"', self.runbook)
        self.assertIn('NEXOLAB_REPO_ROOT="$PWD" bash -s --', self.runbook)
        self.assertIn('--expected-source-sha "$SOURCE_SHA"', self.runbook)
        self.assertIn('--image-id "$TARGET_GATEWAY_IMAGE_ID"', self.runbook)
        self.assertNotIn("TELEGRAM_ENV", self.probe)
        self.assertNotIn("--approve-gateway-refresh", self.probe)

    def test_target_image_is_immutable_behaviorally_proved_before_mutation(self) -> None:
        for token in (
            'TARGET_REVISION=',
            'TARGET_GATEWAY_TREE=',
            'org.opencontainers.image.revision',
            'io.nexolab.source-tree',
            'show "${EXPECTED_SOURCE}:${BOUNDARY_PROBE_PATH}"',
            'docker tag "$EXPECTED_TARGET_IMAGE_ID" "$IMAGE_TAG"',
            '[[ "$IMAGE_ID" == "$EXPECTED_TARGET_IMAGE_ID" ]]',
        ):
            self.assertIn(token, self.text)
        for token in (
            'docker run --pull never --rm --network none --read-only',
            'assert outbox.ids == [approved_id, post_cutoff_id], outbox.ids',
            'org.opencontainers.image.revision',
            'io.nexolab.source-tree',
        ):
            self.assertIn(token, self.probe)
        capability = self.text.index('show "${EXPECTED_SOURCE}:${BOUNDARY_PROBE_PATH}"')
        mutation = self.text.index('MUTATED="1"', capability)
        self.assertLess(capability, mutation)
        self.assertNotIn("inspect.getsource", self.probe)
        self.assertIn('NEXOLAB_REPO_ROOT="$REPO_ROOT" bash -s --', self.text)
        self.assertIn('NEXOLAB_REPO_ROOT="$PWD" bash -s --', self.runbook)
        self.assertIn('if [[ -n "${NEXOLAB_REPO_ROOT:-}" ]]', self.probe)
        self.assertNotIn('bash "$BOUNDARY_PROBE"', self.text)
        self.assertNotIn('docker build \\', self.text)

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
