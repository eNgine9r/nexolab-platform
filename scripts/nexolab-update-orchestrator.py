#!/usr/bin/env python3
"""Host-side GitHub update discovery for the existing NEXOLAB version control plane.

This process is maintenance-plane only. It never activates a revision, never writes
product data, and never turns a remote commit into installation authority. A remote
candidate must still enter the validated local version-management catalog before the
existing privileged version manager may activate it.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4
from datetime import UTC, datetime

EXPECTED_REPOSITORY = "eNgine9r/nexolab-platform"
EXPECTED_BRANCH = "main"
POLICY_SCHEMA = 1
CHECK_SCHEMA = 1
DEFAULT_SCHEDULE = "02:00"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def default_policy() -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA,
        "automatic_updates_enabled": False,
        "schedule_local_time": DEFAULT_SCHEDULE,
        "updated_at": None,
        "updated_by": None,
    }


def load_policy(root: Path) -> dict[str, Any]:
    payload = read_json(root / "update-policy.json")
    if payload is None:
        return default_policy()
    if payload.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("unsupported update policy schema")
    enabled = payload.get("automatic_updates_enabled")
    if not isinstance(enabled, bool):
        raise RuntimeError("automatic_updates_enabled must be boolean")
    if payload.get("schedule_local_time") != DEFAULT_SCHEDULE:
        raise RuntimeError("automatic update schedule must remain fixed at 02:00")
    return payload


def save_policy(root: Path, enabled: bool, actor: str) -> dict[str, Any]:
    policy = {
        "schema_version": POLICY_SCHEMA,
        "automatic_updates_enabled": enabled,
        "schedule_local_time": DEFAULT_SCHEDULE,
        "updated_at": now(),
        "updated_by": actor,
    }
    atomic_json(root / "update-policy.json", policy)
    return policy


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def normalized_repository(remote: str) -> str | None:
    value = remote.strip().removesuffix(".git")
    for prefix in (
        "git@github.com:",
        "ssh://git@github.com/",
        "https://github.com/",
        "http://github.com/",
    ):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def current_source_commit(root: Path) -> str | None:
    current = read_json(root / "current.json")
    value = current.get("source_commit") if current else None
    return value if isinstance(value, str) and len(value) == 40 else None


def discover(root: Path, repo: Path, *, actor: str, fetch_remote: bool = True) -> dict[str, Any]:
    started_at = now()
    result: dict[str, Any] = {
        "schema_version": CHECK_SCHEMA,
        "status": "checking",
        "source": "manual" if actor != "system:update-timer" else "scheduled",
        "actor": actor,
        "started_at": started_at,
        "completed_at": None,
        "result_code": None,
        "message": None,
        "current_commit": current_source_commit(root),
        "target_commit": None,
        "candidate_available": False,
        "activation_eligible": False,
        "blocked_reason": None,
    }
    atomic_json(root / "update-check.json", result)

    try:
        remote = git(repo, "remote", "get-url", "origin")
        if normalized_repository(remote) != EXPECTED_REPOSITORY:
            raise CheckBlocked("repository_mismatch", "Configured origin is not the NEXOLAB repository")

        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != EXPECTED_BRANCH:
            raise CheckBlocked("branch_mismatch", "Update discovery is allowed only from main")

        tracked_changes = git(repo, "status", "--porcelain", "--untracked-files=no")
        if tracked_changes:
            raise CheckBlocked("tracked_worktree_dirty", "Tracked local changes block update discovery")

        current = result["current_commit"]
        if not current:
            raise CheckBlocked("current_revision_unknown", "Current deployed source commit is unknown")

        if fetch_remote:
            fetch = subprocess.run(
                ["git", "-C", str(repo), "fetch", "--quiet", "origin", EXPECTED_BRANCH],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if fetch.returncode != 0:
                raise CheckBlocked("github_unavailable", "GitHub/origin is unavailable")

        target = git(repo, "rev-parse", f"origin/{EXPECTED_BRANCH}")
        result["target_commit"] = target
        if target == current:
            result["status"] = "completed"
            result["result_code"] = "up_to_date"
            result["message"] = "Installed revision matches origin/main."
            return finalize(root, result)

        ancestor = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", current, target],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ancestor.returncode != 0:
            raise CheckBlocked("non_fast_forward", "origin/main is not fast-forward reachable from deployed lineage")

        result["status"] = "completed"
        result["result_code"] = "candidate_discovered"
        result["message"] = "A newer main revision exists but is not installable until a validated local package is staged."
        result["candidate_available"] = True
        result["activation_eligible"] = False
        result["blocked_reason"] = "validated_package_required"
        return finalize(root, result)
    except CheckBlocked as error:
        result["status"] = "blocked"
        result["result_code"] = error.code
        result["message"] = str(error)
        result["blocked_reason"] = error.code
        return finalize(root, result)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result["status"] = "failed"
        result["result_code"] = "update_check_failed"
        result["message"] = str(error)
        result["blocked_reason"] = "update_check_failed"
        return finalize(root, result)


def finalize(root: Path, result: dict[str, Any]) -> dict[str, Any]:
    result["completed_at"] = now()
    atomic_json(root / "update-check.json", result)
    return result


class CheckBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/var/lib/nexolab/versions"))
    parser.add_argument("--repo", type=Path, default=Path("/opt/nexolab-platform"))
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("set-policy")
    policy.add_argument("state", choices=("on", "off"))
    policy.add_argument("--actor", required=True)

    check_now = sub.add_parser("check-now")
    check_now.add_argument("--actor", default="system:update-timer")
    check_now.add_argument("--no-fetch", action="store_true")

    sub.add_parser("status")
    args = parser.parse_args()

    args.root.mkdir(parents=True, exist_ok=True, mode=0o750)
    lock_path = args.root / "update-plane.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "set-policy":
            payload = save_policy(args.root, args.state == "on", args.actor)
        elif args.command == "check-now":
            payload = discover(args.root, args.repo, actor=args.actor, fetch_remote=not args.no_fetch)
        else:
            payload = {
                "policy": load_policy(args.root),
                "update_check": read_json(args.root / "update-check.json"),
            }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
