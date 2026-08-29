from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, env=env, check=False, capture_output=True, text=True)


class HistoricalMainSourceSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        self.assertEqual(run("git", "init", "--bare", str(self.remote), cwd=self.root).returncode, 0)
        self.assertEqual(run("git", "clone", str(self.remote), str(self.repo), cwd=self.root).returncode, 0)
        for key, value in (("user.email", "test@nexolab.local"), ("user.name", "NEXOLAB Test")):
            self.assertEqual(run("git", "config", key, value, cwd=self.repo).returncode, 0)
        self.assertEqual(run("git", "switch", "-c", "main", cwd=self.repo).returncode, 0)

        self.base = self._commit("base")
        self.assertEqual(run("git", "push", "-u", "origin", "main", cwd=self.repo).returncode, 0)
        self.target = self._commit("target")
        self.assertEqual(run("git", "push", "origin", "main", cwd=self.repo).returncode, 0)
        self.latest = self._commit("latest")
        self.assertEqual(run("git", "push", "origin", "main", cwd=self.repo).returncode, 0)
        self.base_evidence = self._set_deployed_evidence(self.base, "20260829T000000Z")

        self.assertEqual(run("git", "switch", "-c", "feature-only", cwd=self.repo).returncode, 0)
        self.feature = self._commit("feature")
        self.assertEqual(run("git", "switch", "main", cwd=self.repo).returncode, 0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _set_deployed_evidence(
        self,
        commit: str | None,
        stamp: str,
        *,
        passed: bool = True,
        mutated: bool = False,
        summary_extra: str = "",
    ) -> Path:
        evidence = self.repo / "runtime" / "deployments" / stamp
        evidence.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if mutated:
            lines.append("RUNTIME MUTATION STARTED: central backend activation")
            (evidence / "runtime-mutation-started").write_text("started\n", encoding="utf-8")
        if summary_extra:
            lines.append(summary_extra)
        if passed:
            lines.append("DEPLOYMENT PASSED")
        (evidence / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if commit is not None:
            (evidence / "final-state.txt").write_text(f"commit={commit}\n", encoding="utf-8")
        return evidence

    def _commit(self, value: str) -> str:
        (self.repo / "fixture.txt").write_text(value + "\n", encoding="utf-8")
        self.assertEqual(run("git", "add", "fixture.txt", cwd=self.repo).returncode, 0)
        self.assertEqual(run("git", "commit", "-m", value, cwd=self.repo).returncode, 0)
        result = run("git", "rev-parse", "HEAD", cwd=self.repo)
        self.assertEqual(result.returncode, 0)
        return result.stdout.strip()

    def _validate(self, source: str, deployed: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        return run(
            "bash",
            str(DEPLOY),
            "--source-ref",
            source,
            "--expected-deployed-source",
            deployed,
            "--source-selection-check-only",
            cwd=ROOT,
            env=env,
        )

    def test_valid_historical_main_lineage_passes_and_restores_main(self) -> None:
        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOURCE_SELECTION_VALIDATED", result.stdout)
        self.assertIn(f"target={self.target}", result.stdout)
        self.assertEqual(run("git", "branch", "--show-current", cwd=self.repo).stdout.strip(), "main")
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), self.latest)

    def test_malformed_source_sha_fails_closed(self) -> None:
        result = self._validate("abc", self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("full lowercase 40-character commit SHA", result.stdout + result.stderr)

    def test_feature_only_commit_fails_closed(self) -> None:
        result = self._validate(self.feature, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not contained in current main history", result.stdout + result.stderr)

    def test_downgrade_target_fails_closed(self) -> None:
        self._set_deployed_evidence(self.target, "20260829T010000Z")
        result = self._validate(self.base, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a fast-forward descendant", result.stdout + result.stderr)

    def test_dirty_starting_tree_fails_before_source_selection(self) -> None:
        (self.repo / "fixture.txt").write_text("dirty\n", encoding="utf-8")
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked local changes detected before source selection", result.stdout + result.stderr)

    def test_expected_deployed_source_must_match_authoritative_successful_evidence(self) -> None:
        result = self._validate(self.target, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the latest authoritative successful deployment evidence", result.stdout + result.stderr)

    def test_default_current_main_selection_still_passes_without_historical_arguments(self) -> None:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        result = run("bash", str(DEPLOY), "--source-selection-check-only", cwd=ROOT, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"target={self.latest}", result.stdout)
        self.assertIn("expected_deployed_source=not_supplied", result.stdout)

    def test_source_and_deployed_sha_must_be_supplied_together(self) -> None:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        result = run(
            "bash", str(DEPLOY), "--source-ref", self.target,
            "--source-selection-check-only", cwd=ROOT, env=env
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("must be supplied together", result.stderr)

    def test_mutable_mtime_cannot_make_older_success_authoritative(self) -> None:
        newer = self._set_deployed_evidence(self.target, "20260829T010000Z")
        future = time.time() + 86400
        os.utime(self.base_evidence, (future, future))
        result = self._validate(self.latest, self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.target}", result.stdout)
        self.assertIn(str(newer), result.stdout)

    def test_newer_failed_mutating_attempt_makes_authority_indeterminate(self) -> None:
        failed = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            mutated=True,
            summary_extra="ERROR: post-mutation readiness failed",
        )
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("crossed runtime mutation boundary without success", combined)
        self.assertIn(str(failed), combined)
        self.assertIn("deployed source authority is indeterminate", combined)

    def test_legacy_newer_mutating_attempt_without_marker_file_fails_closed(self) -> None:
        failed = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            summary_extra="Starting central backend, MinIO and observability",
        )
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("crossed runtime mutation boundary without success", combined)
        self.assertIn(str(failed), combined)

    def test_newer_failed_pre_mutation_attempt_does_not_replace_authority(self) -> None:
        self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            summary_extra="ERROR: frontend candidate verification port is already in use: 3100",
        )
        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.base}", result.stdout)

    def test_preflight_fetches_and_fast_forwards_to_fresh_remote_main(self) -> None:
        writer = self.root / "writer"
        self.assertEqual(
            run("git", "clone", "--branch", "main", str(self.remote), str(writer), cwd=self.root).returncode,
            0,
        )
        for key, value in (("user.email", "writer@nexolab.local"), ("user.name", "Writer")):
            self.assertEqual(run("git", "config", key, value, cwd=writer).returncode, 0)
        (writer / "remote.txt").write_text("fresh remote\n", encoding="utf-8")
        self.assertEqual(run("git", "add", "remote.txt", cwd=writer).returncode, 0)
        self.assertEqual(run("git", "commit", "-m", "remote advance", cwd=writer).returncode, 0)
        remote_head = run("git", "rev-parse", "HEAD", cwd=writer).stdout.strip()
        self.assertEqual(run("git", "push", "origin", "main", cwd=writer).returncode, 0)
        self.assertEqual(run("git", "rev-parse", "origin/main", cwd=self.repo).stdout.strip(), self.latest)

        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"origin_main={remote_head}", result.stdout)
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), remote_head)
        self.assertEqual(run("git", "rev-parse", "origin/main", cwd=self.repo).stdout.strip(), remote_head)


if __name__ == "__main__":
    unittest.main()
