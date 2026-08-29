from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "verify-local-candidate.py"
SPEC = importlib.util.spec_from_file_location("verify_local_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LocalCandidateVerificationTests(unittest.TestCase):
    def make_repository(self, changed_path: str) -> tuple[tempfile.TemporaryDirectory[str], Path, str, str]:
        temporary = tempfile.TemporaryDirectory(prefix="nexolab-candidate-test-")
        repo = Path(temporary.name)
        (repo / "scripts").mkdir()
        (repo / ".project").mkdir()
        shutil.copy2(ROOT / "scripts/classify-ci-impact.py", repo / "scripts/classify-ci-impact.py")
        shutil.copy2(
            ROOT / "scripts/prepare-clean-verification-worktree.sh",
            repo / "scripts/prepare-clean-verification-worktree.sh",
        )
        (repo / "scripts/validate-project-state.py").write_text(
            "#!/usr/bin/env python3\nprint('fixture state valid')\n", encoding="utf-8"
        )
        (repo / ".project/CURRENT_STATE.md").write_text("base\n", encoding="utf-8")

        def git(*args: str) -> str:
            return subprocess.check_output(("git", *args), cwd=repo, text=True).strip()

        git("init", "-q")
        git("config", "user.name", "NEXOLAB test")
        git("config", "user.email", "nexolab-test@example.invalid")
        git("add", ".")
        git("commit", "-q", "-m", "base")
        base_sha = git("rev-parse", "HEAD")

        target = repo / changed_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("candidate\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-q", "-m", "candidate")
        return temporary, repo, base_sha, git("rev-parse", "HEAD")


    def test_default_verification_root_is_repository_parent_not_system_tmp(self) -> None:
        temporary, repo, base_sha, candidate_sha = self.make_repository(
            ".project/CURRENT_STATE.md"
        )
        self.addCleanup(temporary.cleanup)
        observed: list[Path] = []
        real_temporary_directory = MODULE.tempfile.TemporaryDirectory

        def capture_root(*args: object, **kwargs: object):
            observed.append(Path(kwargs["dir"]))
            return real_temporary_directory(*args, **kwargs)

        with mock.patch.object(MODULE.tempfile, "TemporaryDirectory", side_effect=capture_root):
            result = MODULE.verify(repo, base_sha, candidate_sha, False)
        self.assertEqual(result, 0)
        self.assertEqual(observed, [repo.parent.resolve()])

    def test_state_only_selects_dependency_free_lane(self) -> None:
        impact = {
            "classes": ["state_only"],
            "state_only": True,
            "needs_full_quality": False,
            "fail_closed": False,
        }
        self.assertEqual(MODULE.verification_lane(impact), "state_only")

    def test_normal_product_change_selects_core_quality(self) -> None:
        impact = {
            "classes": ["frontend"],
            "state_only": False,
            "needs_full_quality": True,
            "fail_closed": False,
        }
        self.assertEqual(MODULE.verification_lane(impact), "core_quality")

    def test_changed_files_matches_exact_base_and_candidate_trees_when_base_diverged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nexolab-diverged-base-test-") as temporary:
            repo = Path(temporary)

            def git(*args: str) -> str:
                return subprocess.check_output(("git", *args), cwd=repo, text=True).strip()

            git("init", "-q")
            git("config", "user.name", "NEXOLAB test")
            git("config", "user.email", "nexolab-test@example.invalid")
            (repo / "shared.txt").write_text("base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "base")
            common = git("rev-parse", "HEAD")

            git("checkout", "-q", "-b", "candidate")
            (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "candidate")
            candidate = git("rev-parse", "HEAD")

            git("checkout", "-q", "-b", "advanced-base", common)
            (repo / "base-only.txt").write_text("advanced base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "advanced base")
            advanced_base = git("rev-parse", "HEAD")

            files = MODULE.changed_files(repo, advanced_base, candidate)

        self.assertEqual(files, ["base-only.txt", "candidate.txt"])

    def test_unknown_classification_fails_closed(self) -> None:
        impact = {
            "classes": ["cross_surface_or_unknown"],
            "state_only": False,
            "needs_full_quality": True,
            "fail_closed": True,
            "unknown_files": ["new-area/unknown.file"],
        }
        with self.assertRaisesRegex(MODULE.VerificationError, "new-area/unknown.file"):
            MODULE.verification_lane(impact)

    def test_inconsistent_lightweight_result_fails_closed(self) -> None:
        impact = {
            "classes": ["ci_governance"],
            "state_only": False,
            "needs_full_quality": False,
            "fail_closed": False,
        }
        with self.assertRaisesRegex(MODULE.VerificationError, "neither state-only nor full Core"):
            MODULE.verification_lane(impact)

    def test_core_plan_uses_deterministic_install_and_full_quality_build(self) -> None:
        commands = [check.command for check in MODULE.CORE_CHECKS]
        self.assertIn(("npm", "ci", "--no-audit", "--fund=false"), commands)
        self.assertIn(("npm", "run", "format:check"), commands)
        self.assertIn(("npm", "run", "lint"), commands)
        self.assertIn(("npm", "run", "typecheck"), commands)
        self.assertIn(("npm", "test"), commands)
        self.assertIn(("npm", "run", "build"), commands)

    def test_deployment_runtime_requires_compose_validation_automatically(self) -> None:
        impact = {"classes": ["deployment_runtime"]}
        self.assertTrue(MODULE.compose_validation_required(impact, False))

    def test_explicit_compose_validation_applies_to_other_known_classes(self) -> None:
        impact = {"classes": ["frontend"]}
        self.assertFalse(MODULE.compose_validation_required(impact, False))
        self.assertTrue(MODULE.compose_validation_required(impact, True))

    def test_run_check_disables_python_bytecode_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nexolab-bytecode-test-") as temporary:
            worktree = Path(temporary)
            (worktree / "candidate_fixture.py").write_text("VALUE = 1\n", encoding="utf-8")
            executed: list[str] = []
            with mock.patch.dict(
                MODULE.os.environ, {"PYTHONDONTWRITEBYTECODE": ""}, clear=False
            ):
                MODULE._run_check(
                    MODULE.Check(
                        "Python bytecode isolation",
                        ("python3", "-c", "import candidate_fixture"),
                    ),
                    worktree,
                    executed,
                )
            self.assertEqual(executed, ["Python bytecode isolation"])
            self.assertFalse((worktree / "__pycache__").exists())

    def test_exact_nvmrc_node_can_be_resolved_from_user_nvm_installation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nexolab-node-test-") as temporary:
            root = Path(temporary)
            worktree = root / "worktree"
            node = root / ".nvm/versions/node/v22.23.1/bin/node"
            worktree.mkdir()
            node.parent.mkdir(parents=True)
            node.write_text("fixture\n", encoding="utf-8")
            (worktree / ".nvmrc").write_text("22.23.1\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.shutil, "which", return_value=None),
                mock.patch.object(MODULE.Path, "home", return_value=root),
                mock.patch.dict(
                    MODULE.os.environ, {"NVM_DIR": str(root / ".nvm")}, clear=False
                ),
                mock.patch.object(MODULE, "_capture", side_effect=["v22.23.1", "v22.23.1", "10.9.4"]),
            ):
                environment = MODULE._verify_node_baseline(worktree, [])
        self.assertEqual(environment["PATH"].split(":", 1)[0], str(node.parent))

    def test_mismatched_path_node_falls_back_to_exact_nvmrc_installation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="nexolab-node-fallback-test-") as temporary:
            root = Path(temporary)
            worktree = root / "worktree"
            path_node = root / "system/bin/node"
            nvm_node = root / ".nvm/versions/node/v22.23.1/bin/node"
            worktree.mkdir()
            path_node.parent.mkdir(parents=True)
            nvm_node.parent.mkdir(parents=True)
            path_node.write_text("fixture\n", encoding="utf-8")
            nvm_node.write_text("fixture\n", encoding="utf-8")
            (worktree / ".nvmrc").write_text("22.23.1\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE.shutil, "which", return_value=str(path_node)),
                mock.patch.dict(
                    MODULE.os.environ, {"NVM_DIR": str(root / ".nvm")}, clear=False
                ),
                mock.patch.object(
                    MODULE,
                    "_capture",
                    side_effect=["v20.19.0", "v22.23.1", "v22.23.1", "10.9.4"],
                ),
            ):
                environment = MODULE._verify_node_baseline(worktree, [])
        self.assertEqual(environment["PATH"].split(":", 1)[0], str(nvm_node.parent))

    def test_candidate_script_is_known_ci_governance(self) -> None:
        classifier_path = ROOT / "scripts" / "classify-ci-impact.py"
        classifier_spec = importlib.util.spec_from_file_location(
            "classify_ci_impact_for_candidate", classifier_path
        )
        assert classifier_spec and classifier_spec.loader
        classifier = importlib.util.module_from_spec(classifier_spec)
        classifier_spec.loader.exec_module(classifier)
        result = classifier.classify(["scripts/verify-local-candidate.py"])
        self.assertIn("ci_governance", result["classes"])
        self.assertFalse(result["fail_closed"])

    def test_state_only_fixture_runs_in_clean_worktree_without_core_checks(self) -> None:
        temporary, repo, base_sha, candidate_sha = self.make_repository(
            ".project/CURRENT_STATE.md"
        )
        self.addCleanup(temporary.cleanup)
        with mock.patch.object(MODULE, "_verify_node_baseline") as node_check:
            result = MODULE.verify(repo, base_sha, candidate_sha, False)
        self.assertEqual(result, 0)
        node_check.assert_not_called()
        self.assertEqual(subprocess.check_output(("git", "worktree", "list", "--porcelain"), cwd=repo, text=True).count("worktree "), 1)

    def test_product_fixture_routes_the_full_core_plan(self) -> None:
        temporary, repo, base_sha, candidate_sha = self.make_repository("src/app/page.tsx")
        self.addCleanup(temporary.cleanup)
        executed: list[str] = []

        def record(check: object, _worktree: Path, names: list[str]) -> None:
            name = check.name  # type: ignore[attr-defined]
            names.append(name)
            executed.append(name)

        def record_node(_worktree: Path, names: list[str]) -> dict[str, str]:
            names.append("Exact Node baseline")
            executed.append("Exact Node baseline")
            return {"PATH": "/fixture-node"}

        with (
            mock.patch.object(MODULE, "_run_check", side_effect=record),
            mock.patch.object(MODULE, "_verify_node_baseline", side_effect=record_node),
        ):
            result = MODULE.verify(repo, base_sha, candidate_sha, False)
        self.assertEqual(result, 0)
        self.assertIn("Install dependencies deterministically", executed)
        self.assertIn("Frontend production build", executed)

    def test_unknown_fixture_returns_red_before_core_checks(self) -> None:
        temporary, repo, base_sha, candidate_sha = self.make_repository(
            "new-area/unknown.file"
        )
        self.addCleanup(temporary.cleanup)
        with mock.patch.object(MODULE, "_run_check") as run_check:
            result = MODULE.verify(repo, base_sha, candidate_sha, False)
        self.assertEqual(result, 1)
        run_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
