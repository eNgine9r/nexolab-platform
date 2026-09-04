from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-telegram-recurring-activation.sh"
PLANNER = ROOT / "scripts" / "tg04-recurring-activation-runtime-plan.py"

spec = importlib.util.spec_from_file_location("tg04_recurring_activation_plan", PLANNER)
assert spec and spec.loader
plan = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plan
spec.loader.exec_module(plan)

PROFILE_ID = "11111111-1111-1111-1111-111111111111"
ORG_ID = "00000000-0000-0000-0000-000000000001"
SNAPSHOT_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SNAPSHOT_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def profile():
    return plan.Profile(
        id=PROFILE_ID,
        organization_id=ORG_ID,
        name=plan.EXPECTED_PROFILE_NAME,
        timezone="Europe/Kyiv",
        report_hour=7,
        report_minute=50,
        weekdays=(0, 1, 2, 3, 4),
        analysis_window_minutes=720,
        created_at=datetime(2026, 9, 3, 19, 46, tzinfo=UTC),
    )


def snapshot(snapshot_id: str, local_date: str, scheduled_for: str):
    return {
        "id": snapshot_id,
        "profile_id": PROFILE_ID,
        "local_report_date": local_date,
        "scheduled_for": scheduled_for,
        "payload_sha256": "c" * 64,
    }


def delivery(row_id: int, snapshot_id: str, destination: str = "topic"):
    return {
        "id": row_id,
        "snapshot_id": snapshot_id,
        "snapshot_sha256": "c" * 64,
        "destination": destination,
        "state": "sent",
        "attempts": 1,
        "last_error_code": None,
        "telegram_message_id_present": True,
        "sent_at": "2026-09-04T10:00:00+00:00",
        "duplicate_risk": False,
        "created_at": "2026-09-04T10:00:00+00:00",
        "updated_at": "2026-09-04T10:00:00+00:00",
    }


class RecurringActivationPlannerTests(unittest.TestCase):
    NOW = datetime(2026, 9, 4, 13, 0, tzinfo=UTC)

    def compute(self, snapshots, outbox):
        with (
            patch.object(plan, "_load_profile", return_value=profile()),
            patch.object(plan, "_load_snapshots", return_value=snapshots),
            patch.object(plan, "_load_outbox", return_value=(outbox, 36, True)),
        ):
            return plan.compute_plan(self.NOW)

    def test_missing_due_snapshot_predicts_one_generation_and_one_delivery(self):
        snapshots = [snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00")]
        outbox = [delivery(1, SNAPSHOT_1, "general"), delivery(2, SNAPSHOT_1, "topic")]
        result = self.compute(snapshots, outbox)
        self.assertEqual(result["due_local_report_date"], "2026-09-04")
        self.assertEqual(result["predicted_snapshot_generation_count"], 1)
        self.assertEqual(result["predicted_immediate_delivery_count"], 1)
        self.assertEqual(result["outbox_non_sent_rows"], 0)
        self.assertEqual(result["outbox_duplicate_risk_rows"], 0)

    def test_existing_due_snapshot_already_sent_to_topic_predicts_zero(self):
        snapshots = [
            snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00"),
            snapshot(SNAPSHOT_2, "2026-09-04", "2026-09-04T04:50:00+00:00"),
        ]
        outbox = [
            delivery(1, SNAPSHOT_1, "general"),
            delivery(2, SNAPSHOT_1, "topic"),
            delivery(3, SNAPSHOT_2, "topic"),
        ]
        result = self.compute(snapshots, outbox)
        self.assertTrue(result["due_snapshot_exists"])
        self.assertEqual(result["predicted_snapshot_generation_count"], 0)
        self.assertEqual(result["predicted_immediate_delivery_count"], 0)

    def test_existing_eligible_snapshot_missing_topic_delivery_is_explicit(self):
        snapshots = [snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00")]
        outbox = [delivery(1, SNAPSHOT_1, "general")]
        result = self.compute(snapshots, outbox)
        self.assertEqual(result["missing_existing_topic_delivery_count"], 1)
        self.assertEqual(result["predicted_immediate_delivery_count"], 2)

    def test_duplicate_topic_identity_fails_closed(self):
        snapshots = [snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00")]
        outbox = [delivery(1, SNAPSHOT_1, "topic"), delivery(2, SNAPSHOT_1, "topic")]
        with self.assertRaisesRegex(plan.PlanError, "duplicate_topic_outbox_identity"):
            self.compute(snapshots, outbox)

    def test_foreign_outbox_destination_fails_closed(self):
        snapshots = [snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00")]
        outbox = [delivery(1, SNAPSHOT_1, "general"), delivery(2, SNAPSHOT_1, "foreign")]
        with self.assertRaisesRegex(plan.PlanError, "foreign_outbox_destination"):
            self.compute(snapshots, outbox)


class RecurringActivationGuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_is_valid(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_approval_fails_before_runtime_access(self):
        result = subprocess.run(
            [
                str(SCRIPT),
                "--expected-source-sha", "0" * 40,
                "--expected-current-telemetry-image-id", "sha256:" + "0" * 64,
                "--expected-current-gateway-image-id", "sha256:" + "0" * 64,
                "--approve-immediate-deliveries", "1",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("explicit --approve-recurring-activation is required", result.stderr)

    def test_exact_source_images_and_delivery_count_are_pinned(self):
        for token in (
            "--expected-source-sha",
            "--expected-current-telemetry-image-id",
            "--expected-current-gateway-image-id",
            "--approve-immediate-deliveries",
            "--approve-recurring-activation",
            "expected source is not current origin/main",
            "source worktree is not clean",
            "approved immediate delivery count does not match current plan",
        ):
            self.assertIn(token, self.text)

    def test_initial_persistent_flags_and_outbox_fail_closed(self):
        self.assertIn('central.get("DAILY_REPORTS_SCHEDULER_ENABLED","false") == "false"', self.text)
        self.assertIn('telegram.get("TELEGRAM_ENABLED") == "false"', self.text)
        self.assertIn("historical outbox baseline is not the accepted two-row state", self.text)
        self.assertIn('[[ "$SNAPSHOTS_BEFORE" == "1" ]]', self.text)

    def test_scheduler_phase_precedes_gateway_delivery_phase(self):
        scheduler = self.text.index("Phase 1: enable scheduler only")
        delivery = self.text.index("Phase 2: persist topic delivery enablement")
        self.assertLess(scheduler, delivery)
        self.assertIn('set_env_values "$CENTRAL_ENV" DAILY_REPORTS_SCHEDULER_ENABLED true', self.text)
        self.assertIn('set_env_values "$TELEGRAM_ENV" TELEGRAM_ENABLED true TELEGRAM_MINIAPP_ENABLED true', self.text)
        self.assertIn("scheduler snapshot delta did not converge to the approved plan", self.text)

    def test_active_local_auth_overlay_is_preserved_for_forward_and_rollback(self):
        self.assertIn('LOCAL_AUTH_OVERLAY="$COMPOSE_DIR/compose.local-auth.yaml"', self.text)
        self.assertIn('CURRENT_AUTH_LOCAL_ENABLED', self.text)
        self.assertIn('LOCAL_AUTH_COMPOSE_ARGS=( -f "$LOCAL_AUTH_OVERLAY" )', self.text)
        self.assertIn('"${LOCAL_AUTH_COMPOSE_ARGS[@]}"', self.text)
        self.assertIn('AUTH_LOCAL_PRIVATE_KEY_HOST_FILE', self.text)
        self.assertIn('AUTH_LOCAL_PUBLIC_KEY_HOST_FILE', self.text)
        self.assertGreaterEqual(self.text.count('telemetry_local_auth_ready'), 3)
        self.assertIn('current Telemetry local-auth runtime contract is incomplete', self.text)
        self.assertIn('/run/secrets/nexolab_local_auth_private_key', self.text)
        self.assertIn('/run/secrets/nexolab_local_auth_public_key', self.text)
        self.assertIn('Mini App and local auth retained', self.text)

    def test_only_telemetry_and_gateway_are_recreated(self):
        self.assertIn("--force-recreate telemetry-service", self.text)
        self.assertIn("--force-recreate telegram-gateway", self.text)
        self.assertNotIn("docker compose down", self.text)
        self.assertNotIn("docker volume rm", self.text)
        self.assertNotIn("down -v", self.text)

    def test_historical_rows_are_fingerprinted_and_exact_delivery_delta_is_proved(self):
        self.assertIn("OUTBOX_FINGERPRINT_BEFORE", self.text)
        self.assertIn("--fingerprint-through-id", self.text)
        self.assertIn('"$((OUTBOX_ROWS_BEFORE + EXPECTED_IMMEDIATE))"', self.text)
        self.assertIn('"$((TOPIC_SENT_BEFORE + EXPECTED_IMMEDIATE))"', self.text)
        self.assertIn("Post-activation outbox has no non-sent or duplicate-risk rows", self.text)

    def test_rollback_restores_exact_files_and_disables_both_paths(self):
        self.assertIn('restore_file "$ROLLBACK_ROOT/central.env" "$CENTRAL_ENV"', self.text)
        self.assertIn('restore_file "$ROLLBACK_ROOT/telegram.env" "$TELEGRAM_ENV"', self.text)
        self.assertIn("DAILY_REPORTS_SCHEDULER_ENABLED=false", self.text)
        self.assertIn("TELEGRAM_ENABLED=false", self.text)
        self.assertIn("Rollback never deletes generated snapshots, Telegram outbox rows or named volumes", self.text)

    def test_core_tailscale_and_offline_boundaries_are_preserved(self):
        self.assertIn("core container identity changed", self.text)
        self.assertIn("Tailscale Serve topology changed", self.text)
        self.assertIn("No Modbus/hardware write", self.text)
        self.assertNotIn("SEND_EXACT_SNAPSHOT_ONCE", self.text)


if __name__ == "__main__":
    unittest.main()
