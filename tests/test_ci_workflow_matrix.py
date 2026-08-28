from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "verify-pr-workflow-matrix.py"
SPEC = importlib.util.spec_from_file_location("verify_pr_workflow_matrix", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
WorkflowRun = MODULE.WorkflowRun


class WorkflowMatrixTests(unittest.TestCase):
    def _workflow_run(
        self,
        *,
        run_id: int,
        workflow_id: int,
        name: str,
        status: str,
        conclusion=None,
        created="2026-08-22T10:00:00Z",
        attempt=1,
    ):
        return WorkflowRun(
            id=run_id,
            workflow_id=workflow_id,
            name=name,
            status=status,
            conclusion=conclusion,
            created_at=created,
            run_attempt=attempt,
        )

    def test_latest_by_workflow_excludes_current_core_run(self) -> None:
        runs = [
            self._workflow_run(
                run_id=10,
                workflow_id=1,
                name="CI",
                status="completed",
                conclusion="failure",
            ),
            self._workflow_run(
                run_id=11,
                workflow_id=1,
                name="CI",
                status="in_progress",
                created="2026-08-22T10:01:00Z",
            ),
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="success",
            ),
        ]
        latest = MODULE.latest_by_workflow(runs, current_run_id=11)
        self.assertEqual([item.id for item in latest], [20])

    def test_latest_by_workflow_uses_newest_run_for_each_workflow(self) -> None:
        runs = [
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="failure",
            ),
            self._workflow_run(
                run_id=21,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="success",
                created="2026-08-22T10:02:00Z",
            ),
        ]
        latest = MODULE.latest_by_workflow(runs, current_run_id=99)
        self.assertEqual([item.id for item in latest], [21])

    def test_pending_workflow_is_not_green(self) -> None:
        pending, failed = MODULE.evaluate_runs(
            [
                self._workflow_run(
                    run_id=20,
                    workflow_id=2,
                    name="Offline Bundle",
                    status="in_progress",
                )
            ]
        )
        self.assertEqual(len(pending), 1)
        self.assertEqual(failed, [])

    def test_failure_cancel_and_skip_are_merge_blocking(self) -> None:
        runs = [
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="failure",
            ),
            self._workflow_run(
                run_id=30,
                workflow_id=3,
                name="Browser",
                status="completed",
                conclusion="cancelled",
            ),
            self._workflow_run(
                run_id=40,
                workflow_id=4,
                name="Security",
                status="completed",
                conclusion="skipped",
            ),
        ]
        pending, failed = MODULE.evaluate_runs(runs)
        self.assertEqual(pending, [])
        self.assertEqual({item.id for item in failed}, {20, 30, 40})

    def test_missing_required_workflow_is_merge_blocking(self) -> None:
        runs = [
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Authenticated Dashboard Acceptance",
                status="completed",
                conclusion="success",
            )
        ]
        missing = MODULE.missing_required_workflows(
            runs,
            ["Authenticated Dashboard Acceptance", "Offline Bundle"],
        )
        self.assertEqual(missing, ["Offline Bundle"])

    def test_required_workflow_names_are_satisfied_by_observed_green_runs(self) -> None:
        runs = [
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="success",
            ),
            self._workflow_run(
                run_id=30,
                workflow_id=3,
                name="Authenticated Dashboard Acceptance",
                status="completed",
                conclusion="success",
            ),
        ]
        self.assertEqual(
            MODULE.missing_required_workflows(runs, ["Offline Bundle"]),
            [],
        )

    def test_only_successful_completed_workflows_are_green(self) -> None:
        runs = [
            self._workflow_run(
                run_id=20,
                workflow_id=2,
                name="Offline Bundle",
                status="completed",
                conclusion="success",
            ),
            self._workflow_run(
                run_id=30,
                workflow_id=3,
                name="Browser",
                status="completed",
                conclusion="success",
            ),
        ]
        pending, failed = MODULE.evaluate_runs(runs)
        self.assertEqual(pending, [])
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
