from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
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

    def _previous_checkpoint(self, active: dict) -> dict:
        previous = MODULE.make_checkpoint(
            active=active,
            current=active["selection"]["active_work_package"],
            event="older",
            next_action="Older action",
            timestamp="2026-08-22T10:00:00Z",
            actor="ChatGPT",
        )
        previous["baselines"]["historical_release_evidence"] = "runtime/evidence/older"
        previous["evidence_snapshot"]["issue_1388_recovery"] = {"result": "PASS", "checks": 12}
        previous["observations"].append(
            {
                "source": "github",
                "observed_at": "2026-08-22T09:00:00Z",
                "kind": "historical_merge",
                "data": {"issue": 606, "pull_request": 632, "merge_sha": SHA_D},
            }
        )
        previous["runtime_mutation"] = {"performed": False}
        previous["recovery_1384"] = {"status": "verified"}
        return previous

    def test_checkpoint_preserves_existing_evidence_and_updates_event_fields(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        snapshot = json.loads(json.dumps(previous))
        updated = MODULE.make_checkpoint(
            active=active,
            current=active["selection"]["active_work_package"],
            event="checkpoint",
            next_action="Continue",
            timestamp="2026-08-22T11:05:00Z",
            actor="Claude",
            previous=previous,
        )
        self.assertEqual(previous, snapshot, "previous checkpoint must not be mutated")
        self.assertEqual(updated["event"], "checkpoint")
        self.assertEqual(updated["next_action"], "Continue")
        self.assertEqual(updated["timestamp"], "2026-08-22T11:05:00Z")
        self.assertEqual(updated["actor"], "Claude")
        self.assertEqual(updated["evidence_snapshot"]["issue_1388_recovery"], {"result": "PASS", "checks": 12})
        self.assertIn("active_issue_evidence", updated["evidence_snapshot"])
        self.assertEqual(updated["observations"], previous["observations"])
        self.assertEqual(updated["baselines"]["historical_release_evidence"], "runtime/evidence/older")
        self.assertEqual(updated["runtime_mutation"], {"performed": False})
        self.assertEqual(updated["recovery_1384"], {"status": "verified"})
        self.assertEqual(list(updated), list(previous), "existing key order is kept for a reviewable diff")

    def test_checkpoint_without_active_work_keeps_previous_active_issue_evidence(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        idle = json.loads(json.dumps(active))
        idle["selection"]["active_work_package"] = None
        updated = MODULE.make_checkpoint(
            active=idle,
            current=None,
            event="idle",
            next_action="Wait",
            timestamp="2026-08-22T11:05:00Z",
            actor="Claude",
            previous=previous,
        )
        self.assertIsNone(updated["active_work"])
        self.assertEqual(
            updated["evidence_snapshot"]["active_issue_evidence"],
            previous["evidence_snapshot"]["active_issue_evidence"],
        )

    def test_checkpoint_archives_unique_replaced_active_issue_evidence(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        unique = {"native_storage_export_sha256": SHA_D, "owner_reissue_approval_at": "2026-10-11T19:58:12Z"}
        previous["evidence_snapshot"]["active_issue_evidence"] = unique
        arguments = dict(
            active=active,
            current=active["selection"]["active_work_package"],
            event="checkpoint",
            next_action="Continue",
            timestamp="2026-08-22T11:05:00Z",
            actor="Claude",
        )
        updated = MODULE.make_checkpoint(**arguments, previous=previous)
        archived = updated["evidence_snapshot"]["superseded_active_issue_evidence_2026-08-22T10:00:00Z"]
        self.assertEqual(archived, unique)
        self.assertNotEqual(updated["evidence_snapshot"]["active_issue_evidence"], unique)

        held = json.loads(json.dumps(previous))
        held["evidence_snapshot"]["active_issue_evidence"] = {"other": "evidence"}
        sprint_copy = json.loads(json.dumps(active))
        sprint_copy["work_packages"].append({"issue": 999, "title": "Old", "lifecycle": "completed", "evidence": {"other": "evidence"}})
        not_archived = MODULE.make_checkpoint(**{**arguments, "active": sprint_copy}, previous=held)
        self.assertFalse(
            [k for k in not_archived["evidence_snapshot"] if k.startswith("superseded_active_issue_evidence_")]
        )

    def test_checkpoint_guard_rejects_dropped_evidence(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        cases = {
            "top-level 'recovery_1384'": lambda doc: doc.pop("recovery_1384"),
            "evidence_snapshot.issue_1388_recovery": lambda doc: doc["evidence_snapshot"].pop("issue_1388_recovery"),
            "baselines.historical_release_evidence": lambda doc: doc["baselines"].pop("historical_release_evidence"),
            "observations": lambda doc: doc.__setitem__("observations", []),
        }
        for label, drop in cases.items():
            with self.subTest(label=label):
                reduced = json.loads(json.dumps(previous))
                drop(reduced)
                with self.assertRaisesRegex(ValueError, "would drop existing evidence"):
                    MODULE._require_preserved(previous, reduced)

    def test_checkpoint_refuses_stale_sprint_baseline_unless_accepted(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        key = next(iter(active["baselines"]))
        recorded = previous["baselines"][key]
        stale = json.loads(json.dumps(active))
        stale["baselines"][key] = SHA_C if recorded != SHA_C else SHA_B
        arguments = dict(
            active=stale,
            current=stale["selection"]["active_work_package"],
            event="checkpoint",
            next_action="Continue",
            timestamp="2026-08-22T11:05:00Z",
            actor="Claude",
            previous=previous,
        )
        with self.assertRaisesRegex(ValueError, f"baselines differ .*{key}"):
            MODULE.make_checkpoint(**arguments)
        accepted = MODULE.make_checkpoint(**arguments, accept_baseline_changes=True)
        self.assertEqual(accepted["baselines"][key], stale["baselines"][key])
        self.assertEqual(accepted["baselines"]["historical_release_evidence"], "runtime/evidence/older")

    def test_checkpoint_against_repository_state_drops_nothing(self) -> None:
        active = MODULE.load(ROOT / ".project" / "ACTIVE_SPRINT.json")
        previous = MODULE.load(ROOT / ".project" / "LAST_CHECKPOINT.json")
        if previous.get("schema_version") != 2:
            self.skipTest("repository checkpoint is not State Model v2")
        updated = MODULE.make_checkpoint(
            active=active,
            current=active["selection"].get("active_work_package"),
            event="regression-1641",
            next_action="Continue",
            timestamp="2026-11-23T00:00:00Z",
            actor="Claude",
            previous=previous,
        )
        self.assertEqual(set(updated) - {"active_work"}, set(previous) - {"active_work"})
        for key, value in previous["evidence_snapshot"].items():
            if key != "active_issue_evidence":
                self.assertEqual(updated["evidence_snapshot"][key], value, key)
        self.assertEqual(updated["observations"], previous["observations"])
        for key in previous["baselines"]:
            self.assertIn(key, updated["baselines"])

    def test_checkpoint_cli_preserves_evidence_on_disk(self) -> None:
        active = MODULE.migrate_active_v1(v1_active(), observed_at="2026-08-22T11:00:00Z")
        previous = self._previous_checkpoint(active)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".project").mkdir()
            (root / ".project" / "ACTIVE_SPRINT.json").write_text(MODULE.canonical(active), encoding="utf-8")
            (root / ".project" / "LAST_CHECKPOINT.json").write_text(MODULE.canonical(previous), encoding="utf-8")
            (root / ".project" / "CURRENT_STATE.md").write_text("# NEXOLAB Current State\n", encoding="utf-8")
            (root / ".project" / "BLOCKERS.md").write_text("# NEXOLAB Blockers\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--root",
                    tmp,
                    "checkpoint",
                    "--event",
                    "cli",
                    "--next-action",
                    "Continue",
                    "--timestamp",
                    "2026-08-22T11:05:00Z",
                    "--actor",
                    "Claude",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads((root / ".project" / "LAST_CHECKPOINT.json").read_text(encoding="utf-8"))
        self.assertEqual(written["event"], "cli")
        self.assertEqual(written["evidence_snapshot"]["issue_1388_recovery"], {"result": "PASS", "checks": 12})
        self.assertEqual(written["recovery_1384"], {"status": "verified"})
        self.assertEqual(written["observations"], previous["observations"])

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
