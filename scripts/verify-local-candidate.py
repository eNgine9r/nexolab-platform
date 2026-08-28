#!/usr/bin/env python3
"""Verify a committed NEXOLAB candidate in a detached clean worktree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class VerificationError(RuntimeError):
    """A deterministic local candidate verification failure."""


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    env: Mapping[str, str] | None = None


CORE_CHECKS = (
    Check(
        "CI policy tests",
        ("python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_ci_*.py", "-v"),
    ),
    Check("Canonical project state", ("python3", "scripts/validate-project-state.py")),
    Check(
        "Standalone Raspberry Pi runtime contracts",
        ("bash", "scripts/tests/standalone-offline-runtime-contract.sh"),
    ),
    Check("ADR registry", ("python3", "scripts/validate-adr-registry.py")),
    Check(
        "ADR registry tests",
        ("python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_adr_registry.py", "-v"),
    ),
    Check("Dependency policy", ("python3", "scripts/validate-dependency-policy.py")),
    Check(
        "Dependency policy tests",
        (
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_dependency_policy.py",
            "-v",
        ),
    ),
    Check(
        "Install dependencies deterministically",
        ("npm", "ci", "--no-audit", "--fund=false"),
        {"HUSKY": "0"},
    ),
    Check("Repository format", ("npm", "run", "format:check")),
    Check("Frontend lint", ("npm", "run", "lint")),
    Check("Frontend typecheck", ("npm", "run", "typecheck")),
    Check("Frontend tests", ("npm", "test")),
    Check(
        "Frontend production build",
        ("npm", "run", "build"),
        {"NEXT_TELEMETRY_DISABLED": "1"},
    ),
)


def verification_lane(impact: Mapping[str, object]) -> str:
    """Return the only safe local lane for a classifier result."""
    if impact.get("fail_closed") is True:
        unknown = impact.get("unknown_files", [])
        raise VerificationError(
            f"Classifier failed closed for unknown paths: {json.dumps(unknown)}"
        )
    if impact.get("state_only") is True:
        if impact.get("classes") != ["state_only"] or impact.get("needs_full_quality") is not False:
            raise VerificationError("Inconsistent state-only classifier result")
        return "state_only"
    if impact.get("needs_full_quality") is True:
        return "core_quality"
    raise VerificationError("Classifier selected neither state-only nor full Core verification")


def _capture(
    command: Sequence[str], cwd: Path, env: Mapping[str, str] | None = None
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VerificationError(f"Command failed ({' '.join(command)}): {detail}")
    return result.stdout.strip()


def resolve_commit(repo: Path, ref: str, label: str) -> str:
    output = _capture(
        ("git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"), repo
    )
    shas = output.splitlines()
    if len(shas) != 1 or len(shas[0]) != 40:
        raise VerificationError(f"{label} ref did not resolve to exactly one commit: {ref}")
    return shas[0]


def changed_files(repo: Path, base_sha: str, candidate_sha: str) -> list[str]:
    output = _capture(
        ("git", "diff", "--name-only", base_sha, candidate_sha, "--"), repo
    )
    return [line for line in output.splitlines() if line]


def _run_check(check: Check, worktree: Path, executed: list[str]) -> None:
    print(f"\n==> {check.name}", flush=True)
    executed.append(check.name)
    environment = os.environ.copy()
    if check.env:
        environment.update(check.env)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(check.command, cwd=worktree, env=environment, check=False)
    if result.returncode != 0:
        raise VerificationError(f"Check failed: {check.name} (exit code {result.returncode})")


def _verify_node_baseline(worktree: Path, executed: list[str]) -> dict[str, str]:
    name = "Exact Node baseline"
    print(f"\n==> {name}", flush=True)
    executed.append(name)
    expected = f"v{(worktree / '.nvmrc').read_text(encoding='utf-8').strip()}"
    node_path = shutil.which("node")
    if node_path is None:
        nvm_root = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm"))
        nvm_node = nvm_root / "versions" / "node" / expected / "bin" / "node"
        if nvm_node.is_file():
            node_path = str(nvm_node)
    if node_path is None:
        raise VerificationError(
            f"Node {expected} is not on PATH or installed in the configured NVM directory"
        )
    node_bin = str(Path(node_path).resolve().parent)
    node_environment = os.environ.copy()
    node_environment["PATH"] = os.pathsep.join(
        part for part in (node_bin, node_environment.get("PATH", "")) if part
    )
    actual = _capture(("node", "--version"), worktree, node_environment)
    if actual != expected:
        raise VerificationError(f"Expected Node {expected}, got {actual}")
    npm_version = _capture(("npm", "--version"), worktree, node_environment)
    print(f"Verified Node baseline: {actual}; npm version: {npm_version}")
    return {"PATH": node_environment["PATH"]}


def _classify(worktree: Path, files_file: Path) -> dict[str, object]:
    output = _capture(
        ("python3", "scripts/classify-ci-impact.py", "--files-file", str(files_file)),
        worktree,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"Classifier did not return valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise VerificationError("Classifier result must be a JSON object")
    return result


def _assert_clean(worktree: Path) -> None:
    status = _capture(("git", "status", "--porcelain", "--untracked-files=all"), worktree)
    if status:
        raise VerificationError(f"Verification worktree is dirty:\n{status}")


def _compose_checks(worktree: Path) -> tuple[Check, ...]:
    compose_dir = worktree / "infrastructure" / "compose"
    files = sorted(path.name for path in compose_dir.glob("compose*.yaml"))
    if not files:
        raise VerificationError("Compose validation requested but no compose*.yaml files exist")
    return tuple(
        Check(
            f"Compose contract: {name}",
            ("docker", "compose", "-f", name, "config", "--quiet"),
        )
        for name in files
    )


def verify(
    repo: Path,
    base_ref: str,
    candidate_ref: str,
    include_compose: bool,
    worktree_root: Path | None = None,
) -> int:
    base_sha = "UNRESOLVED"
    candidate_sha = "UNRESOLVED"
    impact: dict[str, object] = {}
    executed: list[str] = []
    error: str | None = None
    worktree: Path | None = None

    configured_root = worktree_root or Path(
        os.environ.get("NEXOLAB_VERIFICATION_ROOT", repo.parent)
    )
    verification_root = configured_root.expanduser().resolve()
    if not verification_root.is_dir():
        print(f"error=Verification root does not exist or is not a directory: {verification_root}")
        print("final=RED")
        return 1

    with tempfile.TemporaryDirectory(
        prefix=".nexolab-local-candidate-", dir=verification_root
    ) as temporary:
        temporary_path = Path(temporary)
        worktree = temporary_path / "candidate"
        files_file = temporary_path / "changed-files.txt"
        try:
            base_sha = resolve_commit(repo, base_ref, "Base")
            candidate_sha = resolve_commit(repo, candidate_ref, "Candidate")
            files = changed_files(repo, base_sha, candidate_sha)
            files_file.write_text("".join(f"{path}\n" for path in files), encoding="utf-8")

            helper = repo / "scripts" / "prepare-clean-verification-worktree.sh"
            prepared = subprocess.run(
                ("bash", str(helper), candidate_sha, str(worktree)),
                cwd=repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if prepared.returncode != 0:
                detail = prepared.stderr.strip() or prepared.stdout.strip()
                raise VerificationError(
                    f"Failed to prepare detached clean verification worktree: {detail}"
                )

            _assert_clean(worktree)
            impact = _classify(worktree, files_file)
            lane = verification_lane(impact)

            diff_check = Check(
                "Exact candidate diff integrity",
                ("git", "diff", "--check", base_sha, candidate_sha),
            )
            _run_check(diff_check, worktree, executed)

            if lane == "state_only":
                _run_check(
                    Check("Canonical project state", ("python3", "scripts/validate-project-state.py")),
                    worktree,
                    executed,
                )
            else:
                for check in CORE_CHECKS[:7]:
                    _run_check(check, worktree, executed)
                node_environment = _verify_node_baseline(worktree, executed)
                for check in CORE_CHECKS[7:]:
                    check_environment = dict(check.env or {})
                    check_environment.update(node_environment)
                    _run_check(
                        Check(check.name, check.command, check_environment),
                        worktree,
                        executed,
                    )

            if include_compose:
                for check in _compose_checks(worktree):
                    _run_check(check, worktree / "infrastructure" / "compose", executed)

            _assert_clean(worktree)
        except (OSError, VerificationError) as exc:
            error = str(exc)
        finally:
            if worktree is not None and worktree.exists():
                removed = subprocess.run(
                    ("git", "worktree", "remove", "--force", str(worktree)),
                    cwd=repo,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if removed.returncode != 0 and error is None:
                    error = f"Failed to remove verification worktree: {removed.stderr.strip()}"

    print("\nNEXOLAB LOCAL CANDIDATE SUMMARY")
    print(f"base_sha={base_sha}")
    print(f"candidate_sha={candidate_sha}")
    print(f"impact_classes={json.dumps(impact.get('classes', []), separators=(',', ':'))}")
    print(f"fail_closed={str(impact.get('fail_closed', True)).lower()}")
    print(
        "required_remote_workflows="
        + json.dumps(
            impact.get("verification", {}).get("required_external_workflows", [])
            if isinstance(impact.get("verification"), dict)
            else [],
            separators=(",", ":"),
        )
    )
    print(f"checks_executed={json.dumps(executed, separators=(',', ':'))}")
    print("authority=pre-push evidence only; GitHub exact-head CI and NEXOLAB Merge Gate remain required")
    if error:
        print(f"error={error}")
        print("final=RED")
        return 1
    print("final=GREEN")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a committed candidate in a detached clean Git worktree."
    )
    parser.add_argument("--base", default="origin/main", help="Base ref (default: origin/main)")
    parser.add_argument("--candidate", default="HEAD", help="Candidate ref (default: HEAD)")
    parser.add_argument(
        "--worktree-root",
        type=Path,
        help=(
            "Disk-backed parent for the temporary verification worktree. "
            "Defaults to the repository parent or NEXOLAB_VERIFICATION_ROOT."
        ),
    )
    parser.add_argument(
        "--include-compose-validation",
        action="store_true",
        help="Also validate every infrastructure/compose/compose*.yaml contract",
    )
    args = parser.parse_args()

    try:
        repo = Path(
            _capture(("git", "rev-parse", "--show-toplevel"), Path.cwd())
        ).resolve()
    except VerificationError as exc:
        print(f"error={exc}", file=sys.stderr)
        print("final=RED")
        return 1
    return verify(
        repo,
        args.base,
        args.candidate,
        args.include_compose_validation,
        args.worktree_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
