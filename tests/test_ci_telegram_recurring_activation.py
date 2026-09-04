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

    def test_runtime_reads_are_bounded_and_timeout_fails_closed(self):
        with patch.object(
            plan.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["docker", "exec"],
                timeout=plan.RUNTIME_READ_TIMEOUT_SECONDS,
            ),
        ):
            with self.assertRaisesRegex(plan.PlanError, "runtime_read_timeout"):
                plan._run(["docker", "exec"])

    def test_missing_due_snapshot_predicts_one_generation_and_one_delivery(self):
        snapshots = [snapshot(SNAPSHOT_1, "2026-09-03", "2026-09-03T04:50:00+00:00")]
        outbox = [delivery(1, SNAPSHOT_1, "general"), delivery(2, SNAPSHOT_1, "topic")]
        result = self.compute(snapshots, outbox)
        self.assertEqual(result["due_local_report_date"], "2026-09-04")
        self.assertEqual(result["predicted_snapshot_generation_count"], 1)
        self.assertEqual(result["predicted_immediate_delivery_count"], 1)
        self.assertEqual(result["pending_topic_snapshot_ids"], [])
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
        self.assertEqual(result["pending_topic_snapshot_ids"], [SNAPSHOT_1])
        self.assertEqual(result["predicted_immediate_delivery_count"], 2)

    def test_pending_topic_snapshot_identity_must_be_uuid(self):
        snapshots = [snapshot("not-a-uuid", "2026-09-03", "2026-09-03T04:50:00+00:00")]
        with self.assertRaisesRegex(plan.PlanError, "snapshot_identity_invalid"):
            self.compute(snapshots, [])

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
        self.assertIn('set_env_values "$TELEGRAM_ENV" \\', self.text)
        self.assertIn('TELEGRAM_ENABLED true \\', self.text)
        self.assertIn('TELEGRAM_MINIAPP_ENABLED true \\', self.text)
        self.assertIn("scheduler snapshot delta did not converge to the approved plan", self.text)

    def test_phase_two_blocks_snapshot_writes_and_rechecks_plan_under_fence(self):
        for token in (
            "LOCK TABLE refrigeration_daily_report_snapshots IN SHARE MODE",
            "acquire_snapshot_write_fence",
            "snapshot_write_fence_held",
            "FENCED_PLAN",
            "activation plan changed before the snapshot mutation fence became authoritative",
            "snapshot_write_fence=held",
            "report snapshot mutation fence was lost before delivery mutation",
            "report snapshot mutation fence was lost during delivery convergence",
            "release_snapshot_write_fence",
            "SNAPSHOT_FENCE_HOLD_SECONDS=600",
            "DELIVERY_CONVERGENCE_SECONDS=120",
            "DELIVERY_DEADLINE=$((SECONDS + DELIVERY_CONVERGENCE_SECONDS))",
        ):
            self.assertIn(token, self.text)
        acquire = self.text.index("acquire_snapshot_write_fence ||")
        fenced_plan = self.text.index('FENCED_PLAN="$($PLAN_SCRIPT')
        delivery_enable = self.text.index('set_env_values "$TELEGRAM_ENV" \\')
        self.assertLess(acquire, fenced_plan)
        self.assertLess(fenced_plan, delivery_enable)

    def test_phase_two_pins_exact_bootstrap_snapshot_set_before_releasing_fence(self):
        for token in (
            "pending_topic_snapshot_ids",
            "BOOTSTRAP_CUTOFF_UTC",
            "BOOTSTRAP_SNAPSHOT_IDS_CSV",
            "BOOTSTRAP_SNAPSHOT_COUNT",
            'TELEGRAM_DELIVERY_ACTIVATION_CUTOFF_UTC "$BOOTSTRAP_CUTOFF_UTC"',
            'TELEGRAM_DELIVERY_BOOTSTRAP_SNAPSHOT_IDS "$BOOTSTRAP_SNAPSHOT_IDS_CSV"',
            'telegram.get("TELEGRAM_DELIVERY_ACTIVATION_CUTOFF_UTC")==sys.argv[3]',
            'telegram.get("TELEGRAM_DELIVERY_BOOTSTRAP_SNAPSHOT_IDS","")==sys.argv[4]',
        ):
            self.assertIn(token, self.text)
        fenced_plan = self.text.index('FENCED_PLAN="$($PLAN_SCRIPT')
        bootstrap_ids = self.text.index('BOOTSTRAP_SNAPSHOT_IDS_CSV=')
        delivery_enable = self.text.index('set_env_values "$TELEGRAM_ENV" \\')
        fence_release = self.text.index('release_snapshot_write_fence ||')
        self.assertLess(fenced_plan, bootstrap_ids)
        self.assertLess(bootstrap_ids, delivery_enable)
        self.assertLess(delivery_enable, fence_release)

    def test_rollback_quiesces_gateway_before_telemetry_wait(self):
        quiesce_call = self.text.index("if quiesce_gateway_for_rollback; then")
        telemetry_recreate = self.text.index(
            'if "${COMPOSE[@]}" --env-file "$ROLLBACK_OVERRIDE_ENV" up -d --no-deps --no-build --force-recreate telemetry-service'
        )
        self.assertLess(quiesce_call, telemetry_recreate)
        for token in (
            'timeout 12s docker stop --time 5 "$GATEWAY_NAME"',
            'timeout 8s docker kill "$GATEWAY_NAME"',
            'timeout 30s "${COMPOSE[@]}" --env-file "$ROLLBACK_OVERRIDE_ENV" up -d --no-deps --no-build --force-recreate telegram-gateway',
            'Gateway stopped before Telemetry rollback wait',
            'Gateway force-stopped before Telemetry rollback wait',
            'Gateway recreated delivery-disabled before Telemetry rollback wait',
            'GATEWAY_QUIESCE_OK="1"',
            'if [[ "$GATEWAY_QUIESCE_OK" == "1" ]]; then',
            'Telemetry rollback is aborted',
        ):
            self.assertIn(token, self.text)
        gate = self.text.index('if [[ "$GATEWAY_QUIESCE_OK" == "1" ]]; then')
        self.assertLess(gate, telemetry_recreate)

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
        self.assertIn('Mini App, local auth and observability retained', self.text)

    def test_active_observability_overlay_is_preserved_for_forward_and_rollback(self):
        self.assertIn('OBSERVABILITY_OVERLAY="$COMPOSE_DIR/compose.observability.yaml"', self.text)
        self.assertIn('-f "$OBSERVABILITY_OVERLAY"', self.text)
        self.assertIn('CURRENT_TELEMETRY_VERSION', self.text)
        self.assertIn('TARGET_TELEMETRY_VERSION', self.text)
        self.assertIn('active Telemetry observability version contract would change during recreation', self.text)
        self.assertGreaterEqual(self.text.count('telemetry_observability_ready'), 3)
        self.assertIn('nexolab_telemetry_build_info', self.text)
        self.assertIn('Telemetry observability overlay was not preserved', self.text)

    def test_rollback_requires_scheduler_disabled_runtime_proof(self):
        self.assertIn('TELEMETRY_ROLLBACK_OK="0"', self.text)
        self.assertIn('telemetry_scheduler_disabled_ready', self.text)
        self.assertIn("grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false'", self.text)
        self.assertIn('TELEMETRY_ROLLBACK_OK="1"', self.text)
        self.assertIn('Rollback safety boundary: PASS (persistent scheduler=false delivery=false', self.text)
        self.assertIn('rollback could not prove persistent scheduler=false/delivery=false', self.text)

    def test_mutation_locks_cover_other_production_deployment_paths_before_baseline(self):
        for token in (
            'GATEWAY_REFRESH_LOCK_FILE',
            'STAGE1_LOCK_FILE',
            'CURRENT_HEAD_LOCK_NAME="nexolab-current-head-launch.lock"',
            'acquire_mutation_lock "$GATEWAY_REFRESH_LOCK_FILE"',
            'acquire_mutation_lock "$STAGE1_LOCK_FILE"',
            'USER_TMP_CURRENT_HEAD_LOCK="/tmp/$CURRENT_HEAD_LOCK_NAME"',
            'USER_RUNTIME_CURRENT_HEAD_LOCK="/run/user/$SUDO_UID/$CURRENT_HEAD_LOCK_NAME"',
            'acquire_invoking_user_mutation_locks "$SUDO_UID" "$SUDO_GID"',
            'SUDO_UID',
            'source SHA changed before locked baseline',
        ):
            self.assertIn(token, self.text)
        self.assertNotIn('acquire_mutation_lock "$USER_TMP_CURRENT_HEAD_LOCK"', self.text)
        self.assertNotIn('acquire_mutation_lock "$USER_RUNTIME_CURRENT_HEAD_LOCK"', self.text)
        lock_index = self.text.index('acquire_mutation_lock "$LOCK_FILE"')
        user_lock_index = self.text.index('acquire_invoking_user_mutation_locks "$SUDO_UID"')
        baseline_index = self.text.index('for name in "$TELEMETRY_NAME" "$GATEWAY_NAME"')
        self.assertLess(lock_index, user_lock_index)
        self.assertLess(user_lock_index, baseline_index)

    def test_current_head_lock_holder_uses_nofollow_same_descriptor_and_user_privileges(self):
        for token in (
            'coproc NEXOLAB_USER_LOCK_HOLDER',
            'python3 /dev/fd/3',
            'os.O_NOFOLLOW',
            'os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW',
            'os.setgroups([])',
            'os.setgid(gid)',
            'os.setuid(uid)',
            'os.fstat(fd)',
            'fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)',
            'os.stat(raw, follow_symlinks=False)',
            'current_head_lock_replaced_during_acquire',
            'sys.stdin.buffer.read()',
            'invoking sudo user identity is required for shared deployment locks',
            'unexpected_current_head_lock_ownership',
        ):
            self.assertIn(token, self.text)
        self.assertGreaterEqual(self.text.count('user_lock_holder_alive'), 4)
        self.assertNotIn('ensure_invoking_user_lock_file', self.text)
        self.assertNotIn('exec {fd}>"$USER_TMP_CURRENT_HEAD_LOCK"', self.text)
        self.assertNotIn('exec {fd}>"$USER_RUNTIME_CURRENT_HEAD_LOCK"', self.text)

    def test_root_owned_mutation_lock_paths_are_prepared_without_following_symlinks(self):
        for token in (
            'prepare_root_owned_mutation_lock_file',
            'pst.st_uid != 0',
            'stat.S_ISVTX',
            'os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW',
            'os.O_CREAT | os.O_EXCL',
            'os.fstat(fd)',
            'st.st_uid != 0 or st.st_gid != 0',
            'stat.S_IMODE(st.st_mode) != 0o600',
            'root_mutation_lock_replaced_during_prepare',
            'unsafe root-owned mutation lock',
        ):
            self.assertIn(token, self.text)
        prepare_index = self.text.index('prepare_root_owned_mutation_lock_file "$path"')
        shell_open_index = self.text.index('exec {fd}>"$path"')
        self.assertLess(prepare_index, shell_open_index)

    def test_user_lock_holder_liveness_rejects_zombie_process(self):
        self.assertIn('/proc/$USER_LOCK_HOLDER_PROCESS_PID/stat', self.text)
        self.assertIn("awk '{print $3}'", self.text)
        self.assertIn('[[ -n "$state" && "$state" != "Z" ]]', self.text)

    def test_rollback_requires_persistent_env_restore_proof_and_retains_failed_backup(self):
        for token in (
            'CENTRAL_RESTORE_OK="0"',
            'TELEGRAM_RESTORE_OK="0"',
            'PERSISTENT_ROLLBACK_OK="0"',
            'cmp -s "$ROLLBACK_ROOT/central.env" "$CENTRAL_ENV"',
            'cmp -s "$ROLLBACK_ROOT/telegram.env" "$TELEGRAM_ENV"',
            'persistent_flags_disabled_ready',
            'PERSISTENT_ROLLBACK_OK="1"',
            'ROLLBACK_PROVEN="1"',
            'rollback backup retained for manual recovery',
        ):
            self.assertIn(token, self.text)
        self.assertNotIn('restore_file "$ROLLBACK_ROOT/central.env" "$CENTRAL_ENV" || true', self.text)
        self.assertNotIn('restore_file "$ROLLBACK_ROOT/telegram.env" "$TELEGRAM_ENV" || true', self.text)

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
