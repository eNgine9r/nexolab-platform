#!/usr/bin/env python3
"""Host-side GitHub update discovery for the existing NEXOLAB version control plane.

This process is maintenance-plane only. It never mutates product data directly and
never turns a remote commit into installation authority. A remote candidate must pass
the main-branch GREEN contract and match an already validated local package before an
automatic operation can enter the existing privileged version-manager queue.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
import urllib.error
import urllib.request
from uuid import uuid4

EXPECTED_REPOSITORY = "eNgine9r/nexolab-platform"
EXPECTED_BRANCH = "main"
EXPECTED_GREEN_WORKFLOW = "CI"
GITHUB_API_BASE = f"https://api.github.com/repos/{EXPECTED_REPOSITORY}"
POLICY_SCHEMA = 1
CHECK_SCHEMA = 1
CHECK_REQUEST_SCHEMA = 1
DEFAULT_SCHEDULE = "02:00"
DEFAULT_ROOT = Path("/var/lib/nexolab/version-management")
DEFAULT_REPOSITORY_PATH = Path(
    os.environ.get("NEXOLAB_REPOSITORY_PATH", "/home/nexolab/nexolab-platform")
)
DEFAULT_GIT_USER = os.environ.get("NEXOLAB_GIT_USER", "nexolab").strip() or None
STATE_UID = int(os.environ.get("NEXOLAB_VERSION_STATE_UID", "10001"))
STATE_GID = int(os.environ.get("NEXOLAB_VERSION_STATE_GID", "10001"))


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
        if os.geteuid() == 0:
            os.chown(temporary, STATE_UID, STATE_GID)
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


def git_command(repo: Path, *args: str, git_user: str | None = None) -> list[str]:
    command = ["git", "-C", str(repo), *args]
    if git_user:
        return ["runuser", "-u", git_user, "--", *command]
    return command


def git(
    repo: Path,
    *args: str,
    check: bool = True,
    git_user: str | None = None,
) -> str:
    result = subprocess.run(
        git_command(repo, *args, git_user=git_user),
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


def _github_ci_result(payload: dict[str, Any], target_commit: str) -> tuple[bool, str]:
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        return False, "github_ci_unavailable"
    matching = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("name") == EXPECTED_GREEN_WORKFLOW
        and run.get("event") == "push"
        and run.get("head_sha") == target_commit
        and run.get("status") == "completed"
    ]
    if any(run.get("conclusion") == "success" for run in matching):
        return True, ""
    if matching:
        return False, "ci_not_green"
    return False, "ci_pending_or_missing"


def github_ci_green(target_commit: str) -> tuple[bool, str]:
    url = (
        f"{GITHUB_API_BASE}/actions/runs?head_sha={target_commit}"
        f"&branch={EXPECTED_BRANCH}&status=completed&per_page=30"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NEXOLAB-update-orchestrator",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        UnicodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        return False, "github_ci_unavailable"
    if not isinstance(payload, dict):
        return False, "github_ci_unavailable"
    return _github_ci_result(payload, target_commit)


def _validated_catalog_manifest(bundle_root: Path) -> dict[str, Any] | None:
    manifest_path = bundle_root / "manifest.json"
    marker_path = bundle_root / ".nexolab-validated.json"
    try:
        raw = manifest_path.read_bytes()
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        manifest = json.loads(raw)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(marker, dict) or not isinstance(manifest, dict):
        return None
    digest = hashlib.sha256(raw).hexdigest()
    if marker.get("manifest_sha256") != digest or manifest.get("schema_version") != 1:
        return None
    management = manifest.get("version_management")
    if not isinstance(management, dict) or management.get("bundle_id") != bundle_root.name:
        return None
    schema = management.get("database_schema")
    if not isinstance(schema, dict):
        return None
    policy = manifest.get("persistent_data_policy")
    if not isinstance(policy, dict) or any(
        policy.get(key) is not expected
        for key, expected in (
            ("packaged", False),
            ("delete_volumes", False),
            ("compose_down_v_allowed", False),
        )
    ):
        return None
    if any(
        management.get(key) is not True
        for key in (
            "backup_required",
            "migration_before_readiness",
            "preserve_named_volumes",
            "preserve_edge_sqlite",
        )
    ):
        return None
    return manifest


def validated_candidate_bundle(root: Path, target_commit: str) -> tuple[str | None, str]:
    """Return an activation hint only after both current and target packages are validated.

    This never authorizes installation by itself. The authenticated API and privileged
    version manager revalidate package identity, platform and schema compatibility again
    before any runtime mutation.
    """

    current = read_json(root / "current.json")
    if current is None:
        return None, "current_release_unverified"
    current_bundle = current.get("bundle_id")
    current_release = current.get("release")
    current_commit = current.get("source_commit")
    current_platform = current.get("platform")
    current_schema = current.get("schema_head")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (
            current_bundle,
            current_release,
            current_commit,
            current_platform,
            current_schema,
        )
    ):
        return None, "current_release_unverified"

    current_manifest = _validated_catalog_manifest(root / "catalog" / str(current_bundle))
    if current_manifest is None:
        return None, "current_release_unverified"
    if (
        current_manifest.get("bundle_version") != current_release
        or current_manifest.get("source_commit") != current_commit
        or current_manifest.get("platform") != current_platform
    ):
        return None, "current_release_unverified"

    saw_target_package = False
    saw_platform_mismatch = False
    saw_schema_mismatch = False
    catalog_root = root / "catalog"
    if not catalog_root.is_dir():
        return None, "validated_package_required"
    for bundle_root in sorted(path for path in catalog_root.iterdir() if path.is_dir()):
        manifest = _validated_catalog_manifest(bundle_root)
        if manifest is None or manifest.get("source_commit") != target_commit:
            continue
        saw_target_package = True
        if manifest.get("platform") != current_platform:
            saw_platform_mismatch = True
            continue
        management = manifest.get("version_management")
        schema = management.get("database_schema") if isinstance(management, dict) else None
        upgrade_from = schema.get("upgrade_from") if isinstance(schema, dict) else None
        if not isinstance(upgrade_from, list) or current_schema not in upgrade_from:
            saw_schema_mismatch = True
            continue
        return bundle_root.name, ""

    if saw_schema_mismatch:
        return None, "schema_compatibility_unknown"
    if saw_platform_mismatch:
        return None, "platform_incompatible"
    if saw_target_package:
        return None, "target_release_unverified"
    return None, "validated_package_required"


def _active_operation(root: Path) -> dict[str, Any] | None:
    operations_root = root / "operations"
    if not operations_root.is_dir():
        return None
    for path in sorted(operations_root.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, RuntimeError, json.JSONDecodeError):
            continue
        if payload and payload.get("status") in {"queued", "running"}:
            return payload
    return None


def enqueue_scheduled_activation(root: Path, check: dict[str, Any]) -> dict[str, Any]:
    if check.get("source") != "scheduled" or check.get("actor") != "system:update-timer":
        raise CheckBlocked("invalid_scheduled_activation", "Only the scheduled system actor may auto-activate")
    if check.get("activation_eligible") is not True:
        raise CheckBlocked("candidate_not_eligible", "Scheduled candidate is not activation eligible")
    target_commit = check.get("target_commit")
    expected_bundle = check.get("candidate_bundle_id")
    if not isinstance(target_commit, str) or not isinstance(expected_bundle, str):
        raise CheckBlocked("candidate_identity_missing", "Scheduled candidate identity is incomplete")

    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    with (root / "queue.lock").open("a+", encoding="utf-8") as queue_lock:
        fcntl.flock(queue_lock, fcntl.LOCK_EX)
        if _active_operation(root) is not None or any((root / "requests").glob("*.json")):
            raise CheckBlocked("operation_in_progress", "Another update or rollback operation is active")
        bundle_id, blocked_reason = validated_candidate_bundle(root, target_commit)
        if bundle_id != expected_bundle:
            raise CheckBlocked(
                blocked_reason or "candidate_revalidation_failed",
                "Validated target package changed before scheduled activation",
            )
        current = read_json(root / "current.json")
        target = _validated_catalog_manifest(root / "catalog" / bundle_id)
        if current is None or target is None:
            raise CheckBlocked("candidate_revalidation_failed", "Current or target package evidence is missing")
        source_bundle = current.get("bundle_id")
        source_release = current.get("release")
        target_release = target.get("bundle_version")
        if not all(isinstance(value, str) and value for value in (source_bundle, source_release, target_release)):
            raise CheckBlocked("candidate_identity_missing", "Version operation identity is incomplete")
        operation_id = str(uuid4())
        operation = {
            "schema_version": 1,
            "id": operation_id,
            "organization_id": None,
            "actor_subject": "system:update-timer",
            "action": "update",
            "source_bundle_id": source_bundle,
            "source_release": source_release,
            "target_bundle_id": bundle_id,
            "target_release": target_release,
            "target_commit": target_commit,
            "status": "queued",
            "started_at": now(),
            "ended_at": None,
            "backup_evidence_id": None,
            "result_code": None,
            "reason": "automatic 02:00 update",
        }
        atomic_json(root / "requests" / f"{operation_id}.json", operation)
        atomic_json(root / "operations" / f"{operation_id}.json", operation)
        return operation


def discover(
    root: Path,
    repo: Path,
    *,
    actor: str,
    fetch_remote: bool = True,
    git_user: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": CHECK_SCHEMA,
        "status": "checking",
        "source": "manual" if actor != "system:update-timer" else "scheduled",
        "actor": actor,
        "started_at": now(),
        "completed_at": None,
        "result_code": None,
        "message": None,
        "current_commit": current_source_commit(root),
        "target_commit": None,
        "candidate_available": False,
        "candidate_bundle_id": None,
        "green_revision_verified": False,
        "activation_eligible": False,
        "automatic_activation_operation_id": None,
        "blocked_reason": None,
    }
    atomic_json(root / "update-check.json", result)
    try:
        remote = git(repo, "remote", "get-url", "origin", git_user=git_user)
        if normalized_repository(remote) != EXPECTED_REPOSITORY:
            raise CheckBlocked("repository_mismatch", "Configured origin is not the NEXOLAB repository")
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", git_user=git_user)
        if branch != EXPECTED_BRANCH:
            raise CheckBlocked("branch_mismatch", "Update discovery is allowed only from main")
        tracked_changes = git(
            repo,
            "status",
            "--porcelain",
            "--untracked-files=no",
            git_user=git_user,
        )
        if tracked_changes:
            raise CheckBlocked("tracked_worktree_dirty", "Tracked local changes block update discovery")
        current = result["current_commit"]
        if not current:
            raise CheckBlocked("current_revision_unknown", "Current deployed source commit is unknown")
        if fetch_remote:
            fetch = subprocess.run(
                git_command(repo, "fetch", "--quiet", "origin", EXPECTED_BRANCH, git_user=git_user),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if fetch.returncode != 0:
                raise CheckBlocked("github_unavailable", "GitHub/origin is unavailable")
        target = git(repo, "rev-parse", f"origin/{EXPECTED_BRANCH}", git_user=git_user)
        result["target_commit"] = target
        if target == current:
            result["status"] = "completed"
            result["result_code"] = "up_to_date"
            result["message"] = "Installed revision matches origin/main."
            return finalize(root, result)
        ancestor = subprocess.run(
            git_command(repo, "merge-base", "--is-ancestor", current, target, git_user=git_user),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ancestor.returncode != 0:
            raise CheckBlocked(
                "non_fast_forward",
                "origin/main is not fast-forward reachable from deployed lineage",
            )
        result["status"] = "completed"
        result["result_code"] = "candidate_discovered"
        result["candidate_available"] = True
        green, green_reason = github_ci_green(target)
        if not green:
            result["blocked_reason"] = green_reason
            result["message"] = (
                "A newer main revision exists but its required main-branch CI success "
                "has not been verified, so activation remains blocked."
            )
            return finalize(root, result)
        result["green_revision_verified"] = True
        candidate_bundle_id, blocked_reason = validated_candidate_bundle(root, target)
        result["candidate_bundle_id"] = candidate_bundle_id
        result["activation_eligible"] = candidate_bundle_id is not None
        result["blocked_reason"] = blocked_reason or None
        if candidate_bundle_id is None:
            result["message"] = (
                "A newer GREEN main revision exists but activation remains blocked until its "
                "local validated package satisfies the current platform and schema gates."
            )
        else:
            result["message"] = (
                "A newer GREEN main revision matches a validated local package. The authenticated "
                "version-management API must still revalidate every manual activation gate."
            )
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


def scheduled_check(
    root: Path,
    repo: Path,
    *,
    git_user: str | None = None,
) -> dict[str, Any]:
    policy = load_policy(root)
    if policy["automatic_updates_enabled"] is not True:
        return {
            "status": "skipped",
            "result_code": "automatic_updates_disabled",
            "schedule_local_time": DEFAULT_SCHEDULE,
        }
    result = discover(
        root,
        repo,
        actor="system:update-timer",
        fetch_remote=True,
        git_user=git_user,
    )
    if result.get("activation_eligible") is not True:
        return result
    try:
        operation = enqueue_scheduled_activation(root, result)
    except CheckBlocked as error:
        result["activation_eligible"] = False
        result["blocked_reason"] = error.code
        result["message"] = str(error)
        return finalize(root, result)
    result["automatic_activation_operation_id"] = operation["id"]
    result["message"] = (
        "Eligible GREEN package queued for the existing privileged version manager by "
        "system:update-timer. Runtime mutation remains inside the normal version operation gates."
    )
    return finalize(root, result)


def _validate_check_request(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        raise RuntimeError("update check request is missing")
    if payload.get("schema_version") != CHECK_REQUEST_SCHEMA:
        raise RuntimeError("unsupported update check request schema")
    if payload.get("source") != "manual" or payload.get("status") != "queued":
        raise RuntimeError("update check request must be a queued manual request")
    actor = payload.get("actor_subject")
    request_id = payload.get("id")
    if not isinstance(actor, str) or not actor.strip():
        raise RuntimeError("update check request actor is missing")
    if not isinstance(request_id, str) or not request_id.strip():
        raise RuntimeError("update check request id is missing")
    return payload


def process_requested_check(
    root: Path,
    repo: Path,
    *,
    git_user: str | None = None,
) -> dict[str, Any]:
    pending = sorted((root / "update-check-requests").glob("*.json"))
    if not pending:
        return {"status": "idle", "result_code": "no_pending_update_check"}
    request_path = pending[0]
    try:
        request = _validate_check_request(read_json(request_path))
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        rejected_dir = root / "update-check-rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        request_path.replace(rejected_dir / request_path.name)
        failed = {
            "schema_version": CHECK_SCHEMA,
            "status": "failed",
            "source": "host",
            "actor": "system:update-plane",
            "started_at": now(),
            "completed_at": now(),
            "result_code": "invalid_update_check_request",
            "message": str(error),
            "current_commit": current_source_commit(root),
            "target_commit": None,
            "candidate_available": False,
            "candidate_bundle_id": None,
            "green_revision_verified": False,
            "activation_eligible": False,
            "automatic_activation_operation_id": None,
            "blocked_reason": "invalid_update_check_request",
        }
        atomic_json(root / "update-check.json", failed)
        return failed
    result = discover(
        root,
        repo,
        actor=str(request["actor_subject"]),
        fetch_remote=True,
        git_user=git_user,
    )
    request_path.unlink()
    return {"request_id": request["id"], "check": result}


class CheckBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPOSITORY_PATH)
    parser.add_argument("--git-user", default=DEFAULT_GIT_USER)
    sub = parser.add_subparsers(dest="command", required=True)
    policy = sub.add_parser("set-policy")
    policy.add_argument("state", choices=("on", "off"))
    policy.add_argument("--actor", required=True)
    check_now = sub.add_parser("check-now")
    check_now.add_argument("--actor", default="system:update-timer")
    check_now.add_argument("--no-fetch", action="store_true")
    sub.add_parser("scheduled-check")
    sub.add_parser("run-requested-check")
    sub.add_parser("status")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True, mode=0o750)
    with (args.root / "update-plane.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "set-policy":
            payload = save_policy(args.root, args.state == "on", args.actor)
        elif args.command == "check-now":
            payload = discover(
                args.root,
                args.repo,
                actor=args.actor,
                fetch_remote=not args.no_fetch,
                git_user=args.git_user,
            )
        elif args.command == "scheduled-check":
            payload = scheduled_check(args.root, args.repo, git_user=args.git_user)
        elif args.command == "run-requested-check":
            payload = process_requested_check(args.root, args.repo, git_user=args.git_user)
        else:
            payload = {
                "policy": load_policy(args.root),
                "update_check": read_json(args.root / "update-check.json"),
            }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
