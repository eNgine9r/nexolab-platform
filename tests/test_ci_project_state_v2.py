from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "project-state.py"
SPEC = importlib.util.spec_from_file_location("project_state", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40


def v1_active() -> dict:
    return {
        "schema_version": 1,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": {"id": "TEST", "status": "in_progress"},
        "execution_policy": {
            "verification_policy": "proportional_to_changed_product_surface"
        },
        "repository_product_baseline_sha": SHA_A,
        "accepted_product_sha": SHA_A,
        "last_reconciled_repository_sha": SHA_C,
        "deployed_product_sha": SHA_B,
        "selection_state": {"selected_issue": 11},
        "tasks": [
            {
                "id": "NEXOLAB-10",
                "issue": 10,
                "title": "Completed",
                "status": "completed_green_merged",
                "priority": "high",
                "pull_request": 20,
                "final_pr_head_sha": SHA_C,
                "merge_sha": SHA_D,
                "exact_head_ci": "PASS_123",
                "hardware_accepted_head_sha": SHA_D,
                "fail_closed_classifier": "SOFTWARE_VERIFIED",
                "scope": ["scripts/**"],
                "verification": ["python3 -m unittest"],
            },
            {
                "id": "NEXOLAB-11",
                "issue": 11,
                "title": "Active",
                "status": "in_progress",
                "priority": "high",
                "branch": "chore/11",
                "depends_on": [10],
            },
        ],
        "active_work_package": {
            "issue": 11,
            "title": "Active",
            "branch": "chore/11",
        },
        "maintenance_actions": [
            {
                "source_issue": 598,
                "title": "CVE deadline",
                "status": "due",
                "due_on": "2026-08-26",
            }
        ],
        "safety": {
            "modbus_write": "none",
            "hardware_write": "none",
            "production_cutover_authorized": False,
        },
    }


def v1_checkpoint() -> dict:
    return {
        "schema_version": 1,
        "project": "NEXOLAB",
        "profile": "LOCAL_LAN",
        "sprint": "TEST",
        "timestamp": "2026-08-22T10:00:00Z",
        "actor": "ChatGPT",
        "event": "test",
        "repository_main_sha": SHA_D,
        "accepted_product_sha": SHA_A,
        "deployed_repository_sha": SHA_B,
        "active_work": {"issue": 11, "branch": "chore/11", "status": "IN_PROGRESS"},
        "completed_work": {
            "issue_10": {
                "issue": 10,
                "final_pr_head_sha": SHA_C,
                "merge_sha": SHA_D,
                "exact_head_ci": "PASS_123",
            }
        },
        "maintenance_actions": {
            "cve": {"source_issue": 598, "status": "DUE_BY_2026_08_26"}
        },
        "blocked_work": {"issue_99": "blocked"},
        "next_action": "Continue",
        "safety": {
            "modbus_write": "none",
            "hardware_write": "none",
            "production_cutover_authorized": False,
        },
    }


def ready_state() -> dict:
    active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
    item = MODULE.find_work_package(active, 11)
    item["lifecycle"] = "ready"
    active["selection"]["active_work_package"] = None
    MODULE._VALIDATOR.validate_active(active)
    return active


class StateModelV2Tests(unittest.TestCase):
    def test_migration_preserves_durable_evidence_without_merge_invariant(self) -> None:
        migrated = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["baselines"]["accepted_product_sha"], SHA_A)
        self.assertEqual(migrated["baselines"]["deployed_product_sha"], SHA_B)
        completed = next(item for item in migrated["work_packages"] if item["issue"] == 10)
        self.assertEqual(completed["evidence"]["verified_head_sha"], SHA_C)
        self.assertEqual(completed["evidence"]["hardware_evidence_sha"], SHA_D)
        self.assertEqual(completed["evidence"]["checks"]["fail_closed_classifier"], "SOFTWARE_VERIFIED")
        self.assertEqual(completed["scope"], ["scripts/**"])
        self.assertNotIn("merge_sha", completed["evidence"])
        self.assertEqual(migrated["observations"][0]["data"]["merge_sha"], SHA_D)
        self.assertEqual(migrated["maintenance_actions"][0]["due_on"], "2026-08-26")
        active = next(item for item in migrated["work_packages"] if item["issue"] == 11)
        self.assertEqual(active["depends_on"], [10])

    def test_checkpoint_migration_demotes_merge_sha_to_observation(self) -> None:
        migrated = MODULE.migrate_checkpoint_v1(
            v1_checkpoint(), observed_at="2026-08-22T11:00:00Z"
        )
        item = migrated["evidence_snapshot"]["completed_work"]["issue_10"]
        self.assertNotIn("merge_sha", item)
        self.assertEqual(migrated["observations"][0]["data"]["merge_sha"], SHA_D)

    def test_begin_requires_ready_for_existing_work_package(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        active["selection"]["active_work_package"] = None
        with self.assertRaisesRegex(ValueError, "must be lifecycle ready"):
            MODULE.begin_work(active, issue=10, title="Completed", branch="chore/10")

        started = MODULE.begin_work(ready_state(), issue=11, title="Active", branch="chore/11")
        self.assertEqual(MODULE.find_work_package(started, 11)["lifecycle"], "in_progress")
        self.assertEqual(started["selection"]["active_work_package"]["issue"], 11)

    def test_begin_refuses_to_replace_still_active_work(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        with self.assertRaisesRegex(ValueError, "still active"):
            MODULE.begin_work(active, issue=12, title="Next", branch="chore/12")

    def test_transition_matches_sprint_runner_lifecycle(self) -> None:
        active = MODULE.begin_work(ready_state(), issue=11, title="Active", branch="chore/11")
        review = MODULE.transition_work(active, issue=11, target="review")
        self.assertEqual(MODULE.find_work_package(review, 11)["lifecycle"], "review")
        self.assertEqual(review["selection"]["active_work_package"]["issue"], 11)

        resumed = MODULE.transition_work(review, issue=11, target="in_progress")
        blocked = MODULE.transition_work(resumed, issue=11, target="blocked")
        self.assertEqual(MODULE.find_work_package(blocked, 11)["lifecycle"], "blocked")
        self.assertIsNone(blocked["selection"]["active_work_package"])

    def test_record_evidence_is_idempotent_but_immutable(self) -> None:
        active = ready_state()
        first = MODULE.record_evidence(
            active,
            issue=11,
            verified_head_sha=SHA_C,
            pull_request=21,
            checks=["core_ci=PASS_999"],
            hardware_evidence_sha=None,
        )
        same = MODULE.record_evidence(
            first,
            issue=11,
            verified_head_sha=SHA_C,
            pull_request=21,
            checks=["core_ci=PASS_999"],
            hardware_evidence_sha=None,
        )
        self.assertEqual(first, same)
        with self.assertRaisesRegex(ValueError, "Immutable evidence verified_head_sha"):
            MODULE.record_evidence(
                first,
                issue=11,
                verified_head_sha=SHA_D,
                pull_request=21,
                checks=[],
                hardware_evidence_sha=None,
            )
        with self.assertRaisesRegex(ValueError, "Immutable evidence core_ci"):
            MODULE.record_evidence(
                first,
                issue=11,
                verified_head_sha=SHA_C,
                pull_request=21,
                checks=["core_ci=PASS_DIFFERENT"],
                hardware_evidence_sha=None,
            )

    def test_complete_requires_verified_head_and_check_evidence_not_merge_sha(self) -> None:
        active = MODULE.begin_work(ready_state(), issue=11, title="Active", branch="chore/11")
        no_checks = MODULE.record_evidence(
            active,
            issue=11,
            verified_head_sha=SHA_C,
            pull_request=21,
            checks=[],
            hardware_evidence_sha=None,
        )
        with self.assertRaisesRegex(ValueError, "exact-head check evidence"):
            MODULE.complete_work(no_checks, issue=11)

        with_checks = MODULE.record_evidence(
            active,
            issue=11,
            verified_head_sha=SHA_C,
            pull_request=21,
            checks=["core_ci=PASS_999", "merge_gate=PASS"],
            hardware_evidence_sha=None,
        )
        review = MODULE.transition_work(with_checks, issue=11, target="review")
        completed = MODULE.complete_work(review, issue=11)
        item = MODULE.find_work_package(completed, 11)
        self.assertEqual(item["lifecycle"], "completed")
        self.assertEqual(item["evidence"]["verified_head_sha"], SHA_C)
        self.assertNotIn("merge_sha", item["evidence"])
        self.assertIsNone(completed["selection"]["active_work_package"])

    def test_begin_next_work_requires_no_merge_observation(self) -> None:
        active = MODULE.begin_work(ready_state(), issue=11, title="Active", branch="chore/11")
        active = MODULE.record_evidence(
            active,
            issue=11,
            verified_head_sha=SHA_C,
            pull_request=21,
            checks=["core_ci=PASS"],
            hardware_evidence_sha=None,
        )
        active = MODULE.transition_work(active, issue=11, target="review")
        active = MODULE.complete_work(active, issue=11)
        next_state = MODULE.begin_work(active, issue=12, title="Next", branch="chore/12")
        self.assertEqual(next_state["selection"]["active_work_package"]["issue"], 12)
        self.assertNotIn("repository_main_sha", next_state)

    def test_dry_run_does_not_modify_file(self) -> None:
        active = ready_state()
        updated = MODULE.begin_work(active, issue=11, title="Active", branch="chore/11")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ACTIVE_SPRINT.json"
            path.write_text(MODULE.canonical(active), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                MODULE._write_or_preview(path, active, updated, dry_run=True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), active)
            self.assertIn("in_progress", output.getvalue())

    def test_non_dry_write_is_atomic_and_canonical(self) -> None:
        active = ready_state()
        updated = MODULE.begin_work(active, issue=11, title="Active", branch="chore/11")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ACTIVE_SPRINT.json"
            path.write_text(MODULE.canonical(active), encoding="utf-8")
            MODULE._write_or_preview(path, active, updated, dry_run=False)
            self.assertEqual(path.read_text(encoding="utf-8"), MODULE.canonical(updated))
            self.assertFalse(path.with_name(".ACTIVE_SPRINT.json.tmp").exists())

    def test_checkpoint_is_deterministic_from_explicit_timestamp(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        first = MODULE.make_checkpoint(
            active=active,
            current=active["selection"]["active_work_package"],
            event="checkpoint",
            next_action="Continue",
            timestamp="2026-08-22T11:05:00Z",
            actor="ChatGPT",
        )
        second = MODULE.make_checkpoint(
            active=active,
            current=active["selection"]["active_work_package"],
            event="checkpoint",
            next_action="Continue",
            timestamp="2026-08-22T11:05:00Z",
            actor="ChatGPT",
        )
        self.assertEqual(first, second)

    def test_sprint_runner_uses_state_model_v2_writer_contract(self) -> None:
        runner = (ROOT / "scripts" / "ai-sprint-run.ps1").read_text(encoding="utf-8")
        self.assertIn("$queue.work_packages", runner)
        self.assertIn('$_.lifecycle -eq "ready"', runner)
        self.assertIn('"transition"', runner)
        self.assertIn('"checkpoint"', runner)
        self.assertIn("project-state.py", runner)
        self.assertNotIn("$queue.tasks", runner)
        self.assertNotIn('schema_version = 1', runner)
        self.assertNotIn("Save-JsonFile", runner)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is not installed on this runner")
    def test_sprint_runner_real_dry_run_accepts_canonical_v2_state(self) -> None:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", "scripts/ai-sprint-run.ps1", "-DryRun"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ready Work Packages", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
