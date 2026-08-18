#!/usr/bin/env python3
"""Adopt a controlled source deployment as trusted lineage evidence.

This command does not create validated package authority. It records the exact
source revision, runtime mode, platform, database schema and deployment evidence
only after the live LOCAL_LAN/standalone runtime passes bounded read-only checks.
The resulting current.json therefore remains intentionally absent from the local
package catalog and cannot authorize update/rollback activation by itself.
"""

from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request
from uuid import uuid4

EXPECTED_REPOSITORY = "eNgine9r/nexolab-platform"
EXPECTED_BRANCH = "main"
DEVICE_AGENT_HEALTH_URL = "http://127.0.0.1:8081/health"
SOURCE_AUTHORITY = "controlled_source_deployment"
SHA = re.compile(r"^[0-9a-f]{40}$")


class AdoptionFailure(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(*command: str, timeout: int = 30) -> str:
    result = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise AdoptionFailure(f"command failed safely: {' '.join(command)}: {detail}")
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run("git", "-C", str(repo), *args)


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


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.geteuid() == 0:
            parent = path.parent.stat()
            os.chown(path, parent.st_uid, parent.st_gid)
            os.chmod(path, 0o640)
    finally:
        temporary.unlink(missing_ok=True)


def read_json_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "NEXOLAB-source-adoption"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        UnicodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        raise AdoptionFailure(f"local runtime check failed for {url}") from error
    if not isinstance(payload, dict):
        raise AdoptionFailure(f"local runtime check returned invalid JSON for {url}")
    return payload


def parse_key_value_file(path: Path) -> dict[str, str]:
    facts: dict[str, str] = {}
    key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key_pattern.fullmatch(key) and key not in facts:
            facts[key] = value
    return facts


def repository_schema_head(repo: Path) -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    migration_root = repo / "services" / "telemetry-service" / "migrations" / "versions"
    for path in migration_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values: dict[str, Any] = {}
        for node in tree.body:
            name: str | None = None
            value: ast.expr | None = None
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name = node.targets[0].id
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
                value = node.value
            if name in {"revision", "down_revision"} and value is not None:
                values[name] = ast.literal_eval(value)
        revision = values.get("revision")
        parent = values.get("down_revision")
        if isinstance(revision, str) and revision:
            revisions.add(revision)
        if isinstance(parent, str):
            parents.add(parent)
        elif isinstance(parent, (tuple, list)):
            parents.update(item for item in parent if isinstance(item, str))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise AdoptionFailure(f"expected one repository Alembic head, found {heads}")
    return heads[0]


def host_platform() -> str:
    architecture = platform.machine()
    mapped = {"aarch64": "linux/arm64", "x86_64": "linux/amd64"}.get(architecture)
    if mapped is None:
        raise AdoptionFailure(f"unsupported host platform: {architecture}")
    return mapped


def verify_live_schema(expected_head: str) -> None:
    containers = run(
        "docker",
        "ps",
        "-q",
        "--filter",
        "label=com.docker.compose.project=nexolab-central",
        "--filter",
        "label=com.docker.compose.service=telemetry-service",
    ).splitlines()
    if len(containers) != 1:
        raise AdoptionFailure("exactly one running central telemetry-service container is required")
    revision = run("docker", "exec", containers[0], "alembic", "current")
    if expected_head not in revision:
        raise AdoptionFailure(
            f"live database revision does not match repository head {expected_head}"
        )


def verify_live_runtime(api_base_url: str) -> str:
    api = read_json_url(f"{api_base_url.rstrip('/')}/health/ready")
    if (
        api.get("status") != "ready"
        or api.get("database") != "ready"
        or api.get("mqtt") != "ready"
    ):
        raise AdoptionFailure("Telemetry API/database/MQTT readiness is not fully ready")

    device = read_json_url(DEVICE_AGENT_HEALTH_URL)
    if device.get("status") not in {"ok", "degraded"}:
        raise AdoptionFailure("Device Agent health is neither ok nor degraded")
    acquisition = device.get("acquisition")
    scheduler = acquisition.get("scheduler") if isinstance(acquisition, dict) else None
    if not isinstance(scheduler, dict):
        raise AdoptionFailure("Device Agent scheduler evidence is missing")
    expected = scheduler.get("expected_bus_workers")
    active = scheduler.get("active_bus_workers")
    workers_healthy = scheduler.get("workers_healthy")
    if (
        not isinstance(expected, int)
        or isinstance(expected, bool)
        or expected <= 0
        or not isinstance(active, int)
        or isinstance(active, bool)
        or active != expected
        or workers_healthy is not True
    ):
        raise AdoptionFailure("Device Agent bus-worker invariant is not healthy")
    latest = device.get("latest_values")
    last_attempt = latest.get("last_attempt_at") if isinstance(latest, dict) else None
    if not isinstance(last_attempt, str) or not last_attempt:
        raise AdoptionFailure("Device Agent has no advancing-attempt evidence")
    return "degraded" if device.get("status") == "degraded" else "ready"


def deployment_evidence(repo: Path, evidence_dir: Path) -> tuple[Path, dict[str, str]]:
    repo = repo.resolve()
    deployments_root = (repo / "runtime" / "deployments").resolve()
    candidate = evidence_dir if evidence_dir.is_absolute() else repo / evidence_dir
    resolved = candidate.resolve()
    try:
        resolved.relative_to(deployments_root)
    except ValueError as error:
        raise AdoptionFailure("deployment evidence must live under runtime/deployments") from error
    summary = resolved / "summary.txt"
    final_state = resolved / "final-state.txt"
    if not summary.is_file() or not final_state.is_file():
        raise AdoptionFailure("deployment summary/final-state evidence is missing")
    if "DEPLOYMENT PASSED" not in summary.read_text(encoding="utf-8"):
        raise AdoptionFailure("deployment evidence does not contain DEPLOYMENT PASSED")
    facts = parse_key_value_file(final_state)
    required = {
        "deployed_at",
        "commit",
        "runtime_mode",
        "api",
        "auth_mode",
        "local_auth_overlay",
        "dashboard_auth_provider",
    }
    missing = sorted(required - facts.keys())
    if missing:
        raise AdoptionFailure(f"deployment final-state evidence is incomplete: {missing}")
    return resolved, facts


def _existing_current(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(payload, dict):
        raise AdoptionFailure("existing current deployment evidence is invalid")
    return payload


def adopt(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise AdoptionFailure(f"repository not found: {repo}")

    remote = git(repo, "remote", "get-url", "origin")
    if normalized_repository(remote) != EXPECTED_REPOSITORY:
        raise AdoptionFailure("configured origin is not the canonical NEXOLAB repository")
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != EXPECTED_BRANCH:
        raise AdoptionFailure("source adoption is allowed only from main")
    tracked_changes = git(repo, "status", "--porcelain", "--untracked-files=no")
    if tracked_changes:
        raise AdoptionFailure("tracked local changes block source adoption")
    head = git(repo, "rev-parse", "HEAD")
    origin_head = git(repo, "rev-parse", f"origin/{EXPECTED_BRANCH}")
    if not SHA.fullmatch(head) or not SHA.fullmatch(origin_head):
        raise AdoptionFailure("repository source revision is invalid")
    git(repo, "merge-base", "--is-ancestor", head, origin_head)

    evidence_dir, facts = deployment_evidence(repo, args.evidence_dir)
    if facts["commit"] != head:
        raise AdoptionFailure("deployment evidence commit does not match repository HEAD")
    runtime_mode_path = repo / "runtime" / "runtime-mode"
    runtime_mode = runtime_mode_path.read_text(encoding="utf-8").strip()
    if runtime_mode not in {"lan", "standalone"} or facts["runtime_mode"] != runtime_mode:
        raise AdoptionFailure("runtime mode does not match deployment evidence")
    if facts["auth_mode"] == "disabled":
        raise AdoptionFailure("controlled source adoption refuses AUTH_MODE=disabled")
    if facts["local_auth_overlay"] == "true" and facts["dashboard_auth_provider"] != "local":
        raise AdoptionFailure("local-auth deployment evidence does not match dashboard provider")

    schema_head = repository_schema_head(repo)
    verify_live_schema(schema_head)
    health = verify_live_runtime(facts["api"])
    platform_name = host_platform()
    build_timestamp = git(repo, "show", "-s", "--format=%cI", head)
    source_identity = f"source-main-{head[:12]}"
    relative_evidence = evidence_dir.relative_to(repo).as_posix()
    current_path = root / "current.json"
    existing = _existing_current(current_path)

    previous_source_commit: str | None = None
    previous_source_evidence: str | None = None
    if existing is not None:
        if existing.get("deployment_authority") != SOURCE_AUTHORITY:
            raise AdoptionFailure("current deployment evidence already exists; refusing to replace it")
        existing_commit = existing.get("source_commit")
        existing_evidence = existing.get("source_deployment_evidence")
        if existing_commit == head and existing_evidence == relative_evidence:
            return {
                "status": "already_recorded",
                "source_commit": head,
                "runtime_mode": runtime_mode,
                "platform": platform_name,
                "schema_head": schema_head,
                "health": health,
                "deployment_authority": SOURCE_AUTHORITY,
                "known_packaged_release": False,
                "evidence": relative_evidence,
            }
        if isinstance(existing_commit, str):
            previous_source_commit = existing_commit
        if isinstance(existing_evidence, str):
            previous_source_evidence = existing_evidence

    payload: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": source_identity,
        "bundle_root": None,
        "release": source_identity,
        "source_commit": head,
        "build_timestamp": build_timestamp,
        "runtime_mode": runtime_mode,
        "platform": platform_name,
        "schema_head": schema_head,
        "deployed_at": facts["deployed_at"],
        "health": health,
        "runtime_state_known": True,
        "previous_bundle_id": None,
        "previous_release": None,
        "last_operation_id": None,
        "deployment_authority": SOURCE_AUTHORITY,
        "known_packaged_release": False,
        "source_deployment_evidence": relative_evidence,
        "previous_source_commit": previous_source_commit,
        "previous_source_deployment_evidence": previous_source_evidence,
        "recorded_at": now(),
    }
    atomic_json(current_path, payload)
    return {
        "status": "recorded",
        "source_commit": head,
        "runtime_mode": runtime_mode,
        "platform": platform_name,
        "schema_head": schema_head,
        "health": health,
        "deployment_authority": SOURCE_AUTHORITY,
        "known_packaged_release": False,
        "evidence": relative_evidence,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Record trusted lineage evidence for a controlled source-deployed NEXOLAB runtime."
    )
    result.add_argument("--root", type=Path, required=True)
    result.add_argument("--repo", type=Path, required=True)
    result.add_argument("--evidence-dir", type=Path, required=True)
    return result


def main() -> int:
    payload = adopt(parser().parse_args())
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AdoptionFailure,
        FileNotFoundError,
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"NEXOLAB source deployment adoption stopped safely: {error}", file=sys.stderr)
        raise SystemExit(1) from error
