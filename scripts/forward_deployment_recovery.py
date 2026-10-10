#!/usr/bin/env python3
"""Fail-closed forward recovery for a healthy post-mutation deployment.

This tool verifies an already-running runtime against immutable failed-deployment
evidence. It never mutates NEXOLAB runtime or product data. Execute mode writes
only a sanitized authority record into the failed deployment evidence directory.
"""

from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import hashlib
import json
import ipaddress
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any
import urllib.request
from uuid import uuid4
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")
EXPECTED_REPOSITORY = "eNgine9r/nexolab-platform"
RESULT_NAME = "forward-recovery-result.json"
DEVICE_AGENT_URL = "http://127.0.0.1:8081/health"


class RecoveryFailure(RuntimeError):
    pass


def run(*command: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryFailure(f"command failed safely: {' '.join(command)}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RecoveryFailure(f"command failed safely: {' '.join(command)}: {detail}")
    return result.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return run("git", "-C", str(repo), *args)

def _safe_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise RecoveryFailure(f"{label} is missing or unsafe: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    _safe_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryFailure(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RecoveryFailure(f"{label} must be a JSON object")
    return value


def parse_key_values(path: Path, label: str) -> dict[str, str]:
    _safe_file(path, label)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RecoveryFailure(f"forward recovery result already exists: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def normalized_repository(remote: str) -> str | None:
    value = remote.strip().removesuffix(".git")
    for prefix in ("git@github.com:", "ssh://git@github.com/", "https://github.com/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _migration_facts(source: str) -> tuple[str | None, Any]:
    tree = ast.parse(source)
    values: dict[str, Any] = {}
    for node in tree.body:
        name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name in {"revision", "down_revision"} and value is not None:
            values[name] = ast.literal_eval(value)
    revision = values.get("revision")
    return revision if isinstance(revision, str) else None, values.get("down_revision")

def repository_schema_head(repo: Path, source_commit: str) -> str:
    if not SHA_RE.fullmatch(source_commit):
        raise RecoveryFailure("target source for schema inspection is invalid")
    root = "services/telemetry-service/migrations/versions"
    listing = git(repo, "ls-tree", "-r", "--name-only", source_commit, "--", root)
    revisions: set[str] = set()
    parents: set[str] = set()
    for relative in listing.splitlines():
        if not relative.endswith(".py"):
            continue
        source = git(repo, "show", f"{source_commit}:{relative}")
        try:
            revision, parent = _migration_facts(source)
        except (SyntaxError, ValueError) as exc:
            raise RecoveryFailure(f"invalid migration metadata in {relative}") from exc
        if revision:
            revisions.add(revision)
        if isinstance(parent, str):
            parents.add(parent)
        elif isinstance(parent, (tuple, list)):
            parents.update(item for item in parent if isinstance(item, str))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise RecoveryFailure(f"expected one Alembic head at {source_commit}, found {heads}")
    return heads[0]


def _valid_stamp(name: str) -> bool:
    if not STAMP_RE.fullmatch(name):
        return False
    try:
        datetime.strptime(name, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def _deployment_dirs(repo: Path) -> list[Path]:
    root = repo / "runtime" / "deployments"
    if not root.is_dir():
        raise RecoveryFailure("deployment evidence root is unavailable")
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and _valid_stamp(p.name)],
        key=lambda p: p.name,
    )

def latest_success_before(repo: Path, stamp: str) -> tuple[Path, str]:
    successes: list[tuple[str, Path, str]] = []
    for directory in _deployment_dirs(repo):
        if directory.name >= stamp:
            continue
        summary = directory / "summary.txt"
        final_state = directory / "final-state.txt"
        if not summary.is_file() or not final_state.is_file():
            continue
        if "DEPLOYMENT PASSED" not in summary.read_text(encoding="utf-8", errors="replace"):
            continue
        commit = parse_key_values(final_state, "successful deployment final state").get("commit", "")
        if SHA_RE.fullmatch(commit):
            successes.append((directory.name, directory, commit))
    if not successes:
        raise RecoveryFailure("no prior successful deployment authority is available")
    _stamp, directory, commit = max(successes, key=lambda item: item[0])
    return directory, commit


def ensure_no_newer_mutation(repo: Path, failed_stamp: str) -> None:
    for directory in _deployment_dirs(repo):
        if directory.name <= failed_stamp:
            continue
        summary = directory / "summary.txt"
        summary_text = (
            summary.read_text(encoding="utf-8", errors="replace") if summary.is_file() else ""
        )
        mutated = (directory / "runtime-mutation-started").is_file() or any(
            marker in summary_text
            for marker in (
                "RUNTIME MUTATION STARTED",
                "Starting central backend, MinIO and observability",
                "Starting real-hardware edge stack",
                "Activating verified frontend release",
            )
        )
        if mutated:
            raise RecoveryFailure(
                f"failed deployment is not the latest runtime mutation attempt: {directory}"
            )


def _unit_value(text: str, key: str) -> str:
    prefix = key + "="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise RecoveryFailure(f"dashboard candidate unit is missing {key}")


def _unit_environment(text: str, key: str) -> str:
    prefix = f"Environment={key}="
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    raise RecoveryFailure(f"dashboard candidate unit is missing environment {key}")


def _last_summary_timestamp(summary_text: str) -> str:
    timestamps: list[datetime] = []
    for line in summary_text.splitlines():
        match = re.match(r"^\[([^]]+)\]", line)
        if not match:
            continue
        try:
            timestamps.append(datetime.fromisoformat(match.group(1)))
        except ValueError:
            continue
    if not timestamps:
        raise RecoveryFailure("failed deployment summary has no timestamped evidence")
    return max(timestamps).isoformat()

def build_context(repo: Path, evidence: Path, prior_source: str, target_source: str) -> dict[str, Any]:
    deployments_root = (repo / "runtime" / "deployments").resolve()
    resolved = evidence.resolve()
    if resolved.parent != deployments_root or not _valid_stamp(resolved.name) or evidence.is_symlink():
        raise RecoveryFailure("deployment evidence must be a direct timestamped deployment directory")
    if not SHA_RE.fullmatch(prior_source) or not SHA_RE.fullmatch(target_source):
        raise RecoveryFailure("expected source identities must be full lowercase SHAs")

    summary = _safe_file(resolved / "summary.txt", "failed deployment summary")
    summary_text = summary.read_text(encoding="utf-8", errors="replace")
    if "DEPLOYMENT PASSED" in summary_text:
        raise RecoveryFailure("forward recovery is only for a failed deployment")
    marker = parse_key_values(resolved / "runtime-mutation-started", "runtime mutation marker")
    if marker.get("source") != target_source or not marker.get("started_at"):
        raise RecoveryFailure("runtime mutation marker is not bound to the expected target")

    metadata = read_json(resolved / "edge-sqlite-pre-cutover.json", "edge SQLite metadata")
    if metadata.get("kind") != "nexolab-edge-sqlite-pre-cutover" or metadata.get("schema_version") != 1:
        raise RecoveryFailure("edge SQLite metadata contract is invalid")
    if metadata.get("deployed_source") != prior_source or metadata.get("target_source") != target_source:
        raise RecoveryFailure("edge SQLite metadata source lineage does not match recovery request")
    if metadata.get("source_quick_check") != "ok" or metadata.get("snapshot_quick_check") != "ok":
        raise RecoveryFailure("pre-cutover SQLite evidence is not healthy")
    if metadata.get("outbound_queue_count") != 0:
        raise RecoveryFailure("pre-cutover edge queue was not empty; forward recovery is not safe")

    prior_dir, authoritative_prior = latest_success_before(repo, resolved.name)
    if authoritative_prior != prior_source:
        raise RecoveryFailure("expected prior source is not the latest successful pre-cutover authority")
    ensure_no_newer_mutation(repo, resolved.name)

    remote = normalized_repository(git(repo, "remote", "get-url", "origin"))
    if remote != EXPECTED_REPOSITORY:
        raise RecoveryFailure("configured origin is not the canonical NEXOLAB repository")
    branch = git(repo, "branch", "--show-current")
    if branch != "main":
        raise RecoveryFailure("forward recovery must run from main")
    if git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise RecoveryFailure("tracked local changes block forward recovery")
    head = git(repo, "rev-parse", "HEAD")
    origin_main = git(repo, "rev-parse", "origin/main")
    if head != origin_main:
        raise RecoveryFailure("local main must exactly match origin/main for forward recovery")
    git(repo, "merge-base", "--is-ancestor", prior_source, target_source)
    git(repo, "merge-base", "--is-ancestor", target_source, head)
    git(repo, "merge-base", "--is-ancestor", head, origin_main)

    frontend = parse_key_values(resolved / "frontend-artifact-import.txt", "frontend import evidence")
    if frontend.get("status") != "PASS" or frontend.get("source_sha") != target_source:
        raise RecoveryFailure("frontend artifact evidence is not bound to the failed target")
    if frontend.get("platform") != "linux/arm64" or not frontend.get("build_id"):
        raise RecoveryFailure("frontend artifact platform/build identity is invalid")

    unit_path = _safe_file(resolved / "dashboard-unit-candidate.service", "dashboard candidate unit")
    unit_text = unit_path.read_text(encoding="utf-8")
    release_dir = Path(_unit_value(unit_text, "WorkingDirectory"))
    expected_contract = {
        "runtime_mode": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_DATA_MODE"),
        "api_base_url": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_API_BASE_URL"),
        "websocket_url": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL"),
        "auth_provider": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER"),
        "organization_id": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID"),
    }
    expected_name = f"{target_source}-{resolved.name}"
    if release_dir.name != expected_name or release_dir.parent != repo / "runtime" / "frontend-releases":
        raise RecoveryFailure("dashboard candidate release path is not exact failed-target evidence")

    volume_path = _safe_file(resolved / "volume-identities-before.json", "volume identity evidence")
    volumes = json.loads(volume_path.read_text(encoding="utf-8"))
    if not isinstance(volumes, list) or not volumes:
        raise RecoveryFailure("volume identity evidence is empty or invalid")
    schema_head = repository_schema_head(repo, target_source)

    evidence_files = {
        "runtime_mutation_started": resolved / "runtime-mutation-started",
        "edge_sqlite_pre_cutover": resolved / "edge-sqlite-pre-cutover.json",
        "frontend_artifact_import": resolved / "frontend-artifact-import.txt",
        "dashboard_unit_candidate": unit_path,
        "volume_identities_before": volume_path,
    }
    return {
        "repo": repo,
        "evidence": resolved,
        "stamp": resolved.name,
        "prior_dir": prior_dir,
        "prior_source": prior_source,
        "target_source": target_source,
        "mutation_started_at": marker["started_at"],
        "attempt_completed_at": _last_summary_timestamp(summary_text),
        "metadata": metadata,
        "frontend": frontend,
        "release_dir": release_dir,
        "unit_text": unit_text,
        "expected_contract": expected_contract,
        "volumes": volumes,
        "schema_head": schema_head,
        "head": head,
        "origin_main": origin_main,
        "evidence_hashes": {key: sha256_file(path) for key, path in evidence_files.items()},
    }


def load_published_authority(repo: Path, evidence: Path) -> dict[str, Any]:
    repo = repo.resolve()
    deployments_root = (repo / "runtime" / "deployments").resolve()
    resolved = evidence.resolve()
    if resolved.parent != deployments_root or evidence.is_symlink() or not _valid_stamp(resolved.name):
        raise RecoveryFailure("forward recovery evidence path is unsafe")

    summary = _safe_file(resolved / "summary.txt", "failed deployment summary")
    summary_text = summary.read_text(encoding="utf-8", errors="replace")
    if "DEPLOYMENT PASSED" in summary_text:
        raise RecoveryFailure("forward recovery result cannot replace successful deployment evidence")
    document = read_json(resolved / RESULT_NAME, "forward recovery result")
    prior = document.get("previous_source")
    target = document.get("target_source")
    if not isinstance(prior, str) or not SHA_RE.fullmatch(prior):
        raise RecoveryFailure("forward recovery previous source is invalid")
    if not isinstance(target, str) or not SHA_RE.fullmatch(target):
        raise RecoveryFailure("forward recovery target source is invalid")

    marker = parse_key_values(resolved / "runtime-mutation-started", "runtime mutation marker")
    metadata = read_json(resolved / "edge-sqlite-pre-cutover.json", "edge SQLite metadata")
    frontend = parse_key_values(resolved / "frontend-artifact-import.txt", "frontend import evidence")
    unit_path = _safe_file(resolved / "dashboard-unit-candidate.service", "dashboard candidate unit")
    unit_text = unit_path.read_text(encoding="utf-8")
    volume_path = _safe_file(resolved / "volume-identities-before.json", "volume identity evidence")
    try:
        volumes = json.loads(volume_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryFailure("volume identity evidence is unreadable") from exc

    if marker.get("source") != target or not marker.get("started_at"):
        raise RecoveryFailure("published recovery is not bound to its mutation marker")
    if (
        metadata.get("kind") != "nexolab-edge-sqlite-pre-cutover"
        or metadata.get("schema_version") != 1
        or metadata.get("deployed_source") != prior
        or metadata.get("target_source") != target
        or metadata.get("source_quick_check") != "ok"
        or metadata.get("snapshot_quick_check") != "ok"
        or metadata.get("outbound_queue_count") != 0
    ):
        raise RecoveryFailure("published recovery edge SQLite lineage is invalid")
    if frontend.get("status") != "PASS" or frontend.get("source_sha") != target:
        raise RecoveryFailure("published recovery frontend evidence is invalid")
    if frontend.get("platform") != "linux/arm64" or not frontend.get("build_id"):
        raise RecoveryFailure("published recovery frontend identity is invalid")

    release_dir = Path(_unit_value(unit_text, "WorkingDirectory"))
    if release_dir != repo / "runtime" / "frontend-releases" / f"{target}-{resolved.name}":
        raise RecoveryFailure("published recovery Dashboard release path is invalid")
    expected_contract = {
        "runtime_mode": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_DATA_MODE"),
        "api_base_url": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_API_BASE_URL"),
        "auth_provider": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER"),
        "organization_id": _unit_environment(unit_text, "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID"),
    }
    if expected_contract["runtime_mode"] != "live" or expected_contract["auth_provider"] != "local":
        raise RecoveryFailure("published recovery Dashboard contract is not LOCAL_LAN live/local-auth")

    evidence_files = {
        "runtime_mutation_started": resolved / "runtime-mutation-started",
        "edge_sqlite_pre_cutover": resolved / "edge-sqlite-pre-cutover.json",
        "frontend_artifact_import": resolved / "frontend-artifact-import.txt",
        "dashboard_unit_candidate": unit_path,
        "volume_identities_before": volume_path,
    }
    expected_hashes = {key: sha256_file(path) for key, path in evidence_files.items()}
    context = {
        "stamp": resolved.name,
        "prior_source": prior,
        "target_source": target,
        "evidence_hashes": expected_hashes,
    }
    validate_result(document, context)
    if document.get("runtime_activated_at") != marker["started_at"]:
        raise RecoveryFailure("published recovery activation timestamp mismatch")
    if document.get("schema_head") != repository_schema_head(repo, target):
        raise RecoveryFailure("published recovery schema does not match target source")
    if document.get("dashboard_release_dir") != str(release_dir):
        raise RecoveryFailure("published recovery Dashboard release mismatch")
    if document.get("dashboard_build_id") != frontend["build_id"]:
        raise RecoveryFailure("published recovery Dashboard build mismatch")
    if document.get("api") != expected_contract["api_base_url"]:
        raise RecoveryFailure("published recovery API origin mismatch")
    if document.get("dashboard_auth_provider") != expected_contract["auth_provider"]:
        raise RecoveryFailure("published recovery auth provider mismatch")
    if document.get("dashboard_organization_id") != expected_contract["organization_id"]:
        raise RecoveryFailure("published recovery organization mismatch")
    if document.get("local_auth_overlay") is not True:
        raise RecoveryFailure("published recovery local-auth overlay is not enabled")
    if document.get("platform") != "linux/arm64" or document.get("runtime_mode") != "lan":
        raise RecoveryFailure("published recovery runtime identity is invalid")
    if not isinstance(volumes, list) or not any(
        isinstance(item, dict) and item.get("Name") == document.get("postgres_volume_name")
        for item in volumes
    ):
        raise RecoveryFailure("published recovery PostgreSQL volume is not evidence-bound")

    git(repo, "cat-file", "-e", f"{prior}^{{commit}}")
    git(repo, "cat-file", "-e", f"{target}^{{commit}}")
    git(repo, "merge-base", "--is-ancestor", prior, target)
    return document


def _docker_one(project: str, service: str) -> tuple[str, dict[str, Any]]:
    ids = [line for line in run(
        "docker", "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", f"label=com.docker.compose.service={service}",
    ).splitlines() if line]
    if len(ids) != 1:
        raise RecoveryFailure(f"expected exactly one running {project}/{service} container")
    document = json.loads(run("docker", "inspect", ids[0]))
    if not isinstance(document, list) or len(document) != 1:
        raise RecoveryFailure(f"invalid Docker inspect for {project}/{service}")
    return ids[0], document[0]

def _http_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)
    except Exception as exc:
        raise RecoveryFailure(f"runtime health request failed: {url}") from exc
    if not isinstance(payload, dict):
        raise RecoveryFailure(f"runtime health payload is not a JSON object: {url}")
    return payload


def _http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return int(response.status)
    except Exception as exc:
        raise RecoveryFailure(f"runtime HTTP request failed: {url}") from exc


def _container_mount(inspect: dict[str, Any], destination: str) -> dict[str, Any]:
    mounts = inspect.get("Mounts")
    if not isinstance(mounts, list):
        raise RecoveryFailure("Docker inspect is missing mounts")
    matches = [m for m in mounts if isinstance(m, dict) and m.get("Destination") == destination]
    if len(matches) != 1:
        raise RecoveryFailure(f"expected exactly one mount at {destination}")
    return matches[0]


def _volume_identity(name: str) -> dict[str, Any]:
    document = json.loads(run("docker", "volume", "inspect", name))
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise RecoveryFailure(f"invalid Docker volume identity: {name}")
    item = document[0]
    return {key: item.get(key) for key in ("Name", "Driver", "Mountpoint", "CreatedAt")}

def collect_runtime_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    release_dir: Path = context["release_dir"]
    working_dir = run("systemctl", "show", "-p", "WorkingDirectory", "--value", "nexolab-dashboard.service")
    main_pid = run("systemctl", "show", "-p", "MainPID", "--value", "nexolab-dashboard.service")
    if not main_pid.isdigit() or int(main_pid) <= 0:
        raise RecoveryFailure("dashboard service has no running MainPID")
    process_cwd = os.readlink(f"/proc/{main_pid}/cwd")

    source_sha = _safe_file(release_dir / "frontend-source-sha.txt", "active frontend source").read_text().strip()
    build_id = _safe_file(release_dir / "frontend-build-id.txt", "active frontend build id").read_text().strip()
    frontend_platform = _safe_file(release_dir / "frontend-platform.txt", "active frontend platform").read_text().strip()
    contract = parse_key_values(release_dir / "frontend-runtime-contract.txt", "active frontend contract")
    api = contract.get("api_base_url", "")
    if not api.startswith("http://"):
        raise RecoveryFailure("active frontend API contract is invalid")
    dashboard = api.rsplit(":", 1)[0] + ":3000"

    edge_short, edge = _docker_one("nexolab-edge", "device-agent")
    edge_full = str(edge.get("Id", ""))
    edge_image = str(edge.get("Image", ""))
    edge_state = edge.get("State") if isinstance(edge.get("State"), dict) else {}
    edge_mount = _container_mount(edge, "/var/lib/nexolab")
    local_edge_image = run("docker", "image", "inspect", "--format", "{{.Id}}", "nexolab-device-agent:local")

    run(
        sys.executable,
        str(context["repo"] / "scripts" / "device-agent-deployment-health-gate.py"),
        "--expected-container-id", edge_short,
        "--timeout-seconds", "10",
        "--poll-seconds", "1",
        timeout=15,
    )
    device_health = _http_json(DEVICE_AGENT_URL)
    sqlite_probe = r'''import json,sqlite3
c=sqlite3.connect("file:/var/lib/nexolab/edge.db?mode=ro",uri=True)
quick=c.execute("PRAGMA quick_check").fetchone()[0]
count=c.execute("select count(*) from outbound_queue").fetchone()[0]
seq=c.execute("select seq from sqlite_sequence where name='outbound_queue'").fetchone()
streams=c.execute("select count(*) from node_stream_sequences").fetchone()[0]
print(json.dumps({"quick_check":quick,"outbound_queue_count":count,"outbound_queue_high_water":seq[0] if seq else 0,"node_stream_sequences_count":streams}))'''
    edge_sqlite = json.loads(run("docker", "exec", edge_short, "/usr/bin/python3.13", "-c", sqlite_probe))

    telemetry_short, telemetry = _docker_one("nexolab-central", "telemetry-service")
    telemetry_image = str(telemetry.get("Image", ""))
    telemetry_state = telemetry.get("State") if isinstance(telemetry.get("State"), dict) else {}
    local_telemetry_image = run("docker", "image", "inspect", "--format", "{{.Id}}", "nexolab-telemetry-service:local")
    telemetry_ready = _http_json(api.rstrip("/") + "/health/ready")

    postgres_short, postgres = _docker_one("nexolab-central", "postgres")
    postgres_state = postgres.get("State") if isinstance(postgres.get("State"), dict) else {}
    postgres_mount = _container_mount(postgres, "/var/lib/postgresql/data")
    live_schema = run(
        "docker", "exec", postgres_short, "sh", "-lc",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"',
    ).splitlines()[-1].strip()

    telemetry_env = ((telemetry.get("Config") or {}).get("Env") or [])
    auth_mode = next((item.split("=", 1)[1] for item in telemetry_env if isinstance(item, str) and item.startswith("AUTH_MODE=")), "")
    volume_snapshot: dict[str, dict[str, Any]] = {}
    for item in context["volumes"]:
        if not isinstance(item, dict) or not isinstance(item.get("Name"), str):
            raise RecoveryFailure("pre-cutover volume evidence contains an invalid item")
        volume_snapshot[item["Name"]] = _volume_identity(item["Name"])

    scheduler = ((device_health.get("acquisition") or {}).get("scheduler") or {})
    registry = device_health.get("acquisition_registry") or {}
    return {
        "platform": {"machine": platform.machine()},
        "dashboard": {
            "working_directory": working_dir,
            "process_cwd": process_cwd,
            "source_sha": source_sha,
            "build_id": build_id,
            "platform": frontend_platform,
            "runtime_contract": contract,
            "http_status": _http_status(dashboard),
            "url": dashboard,
        },
        "device_agent": {
            "container_id": edge_full,
            "created_at": str(edge.get("Created", "")),
            "image_id": edge_image,
            "local_image_id": local_edge_image,
            "docker_health": ((edge_state.get("Health") or {}).get("Status")),
            "edge_volume": edge_mount.get("Name"),
            "status": device_health.get("status"),
            "device_mode": device_health.get("device_mode"),
            "mqtt_connected": device_health.get("mqtt_connected"),
            "queue_depth": device_health.get("queue_depth"),
            "expected_bus_workers": scheduler.get("expected_bus_workers"),
            "active_bus_workers": scheduler.get("active_bus_workers"),
            "workers_healthy": scheduler.get("workers_healthy"),
            "registry_revision": registry.get("revision"),
            "latest_attempt_at": ((device_health.get("latest_values") or {}).get("last_attempt_at")),
            "sqlite": edge_sqlite,
        },
        "telemetry": {
            "container_id": str(telemetry.get("Id", "")),
            "created_at": str(telemetry.get("Created", "")),
            "image_id": telemetry_image,
            "local_image_id": local_telemetry_image,
            "docker_health": ((telemetry_state.get("Health") or {}).get("Status")),
            "ready": telemetry_ready,
            "api": api,
            "auth_mode": auth_mode,
        },
        "postgres": {
            "container_id": str(postgres.get("Id", "")),
            "docker_health": ((postgres_state.get("Health") or {}).get("Status")),
            "volume_name": postgres_mount.get("Name"),
            "schema_head": live_schema,
        },
        "volumes": volume_snapshot,
    }


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RecoveryFailure(f"{label} timestamp is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryFailure(f"{label} timestamp is invalid") from exc


def _require_container_from_attempt(created_at: object, context: dict[str, Any], label: str) -> None:
    created = _parse_time(created_at, label)
    started = _parse_time(context["mutation_started_at"], "runtime mutation")
    completed = _parse_time(context["attempt_completed_at"], "failed deployment completion")
    if created < started or created > completed:
        raise RecoveryFailure(f"{label} container was not created by the failed deployment attempt")


def validate_runtime_snapshot(snapshot: dict[str, Any], context: dict[str, Any]) -> None:
    if snapshot.get("platform", {}).get("machine") != "aarch64":
        raise RecoveryFailure("forward recovery is limited to the controlled linux/arm64 host")

    dashboard = snapshot.get("dashboard") or {}
    expected_release = str(context["release_dir"])
    if dashboard.get("working_directory") != expected_release or dashboard.get("process_cwd") != expected_release:
        raise RecoveryFailure("active Dashboard process is not the failed target release")
    if dashboard.get("source_sha") != context["target_source"]:
        raise RecoveryFailure("active Dashboard source does not match failed target")
    if dashboard.get("build_id") != context["frontend"]["build_id"] or dashboard.get("platform") != "linux/arm64":
        raise RecoveryFailure("active Dashboard build identity does not match failed evidence")
    if dashboard.get("http_status") != 200:
        raise RecoveryFailure("active Dashboard is not HTTP-ready")
    if dashboard.get("runtime_contract") != context.get("expected_contract"):
        raise RecoveryFailure("active Dashboard runtime contract does not match failed evidence")
    if dashboard["runtime_contract"].get("runtime_mode") != "live":
        raise RecoveryFailure("active Dashboard runtime mode is not live")
    if dashboard["runtime_contract"].get("auth_provider") != "local":
        raise RecoveryFailure("active Dashboard authentication provider is not local")

    device = snapshot.get("device_agent") or {}
    _require_container_from_attempt(device.get("created_at"), context, "Device Agent")
    if device.get("image_id") != device.get("local_image_id") or not IMAGE_RE.fullmatch(str(device.get("image_id", ""))):
        raise RecoveryFailure("active Device Agent image is not the selected local image")
    if device.get("docker_health") != "healthy" or device.get("status") != "ok":
        raise RecoveryFailure("Device Agent is not healthy")
    if device.get("device_mode") != "modbus" or device.get("mqtt_connected") is not True:
        raise RecoveryFailure("Device Agent mode/MQTT state is not acceptable")
    if device.get("queue_depth") != 0:
        raise RecoveryFailure("Device Agent outbound queue is not empty")
    expected = device.get("expected_bus_workers")
    active = device.get("active_bus_workers")
    if type(expected) is not int or type(active) is not int or expected <= 0 or active != expected:
        raise RecoveryFailure("Device Agent bus-worker invariant is not healthy")
    if device.get("workers_healthy") is not True:
        raise RecoveryFailure("Device Agent scheduler workers are not healthy")
    if device.get("registry_revision") != context["metadata"].get("registry_revision"):
        raise RecoveryFailure("Device Agent acquisition-registry revision drifted from cutover boundary")
    if not isinstance(device.get("latest_attempt_at"), str) or not device.get("latest_attempt_at"):
        raise RecoveryFailure("Device Agent has no advancing acquisition evidence")
    if device.get("edge_volume") != "nexolab-edge_edge-data":
        raise RecoveryFailure("Device Agent edge SQLite volume identity is unexpected")

    sqlite = device.get("sqlite") or {}
    if sqlite.get("quick_check") != "ok" or sqlite.get("outbound_queue_count") != 0:
        raise RecoveryFailure("live edge SQLite integrity/queue state is not acceptable")
    previous_high_water = context["metadata"].get("outbound_queue_high_water")
    current_high_water = sqlite.get("outbound_queue_high_water")
    if type(previous_high_water) is not int or type(current_high_water) is not int or current_high_water < previous_high_water:
        raise RecoveryFailure("edge SQLite queue high-water mark moved backward")

    telemetry = snapshot.get("telemetry") or {}
    _require_container_from_attempt(telemetry.get("created_at"), context, "Telemetry Service")
    ready = telemetry.get("ready") or {}
    if telemetry.get("image_id") != telemetry.get("local_image_id"):
        raise RecoveryFailure("active Telemetry Service image is not the selected local image")
    if telemetry.get("docker_health") != "healthy":
        raise RecoveryFailure("Telemetry Service Docker health is not healthy")
    if ready.get("status") != "ready" or ready.get("database") != "ready" or ready.get("mqtt") != "ready":
        raise RecoveryFailure("Telemetry Service readiness is not healthy")
    if telemetry.get("auth_mode") == "disabled" or not telemetry.get("auth_mode"):
        raise RecoveryFailure("controlled recovery refuses disabled/unknown authentication")
    if telemetry.get("api") != context["expected_contract"].get("api_base_url"):
        raise RecoveryFailure("Telemetry Service API origin does not match failed Dashboard contract")

    postgres = snapshot.get("postgres") or {}
    if postgres.get("docker_health") != "healthy":
        raise RecoveryFailure("PostgreSQL is not healthy")
    if postgres.get("volume_name") != "nexolab-central-postgres-data":
        raise RecoveryFailure("PostgreSQL volume identity is unexpected")
    if postgres.get("schema_head") != context["schema_head"]:
        raise RecoveryFailure("live PostgreSQL schema does not match failed target source")

    expected_volumes = {
        item["Name"]: {key: item.get(key) for key in ("Name", "Driver", "Mountpoint", "CreatedAt")}
        for item in context["volumes"]
        if isinstance(item, dict) and isinstance(item.get("Name"), str)
    }
    if snapshot.get("volumes") != expected_volumes:
        raise RecoveryFailure("persistent volume identities changed since the pre-cutover boundary")


def build_result(snapshot: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    dashboard = snapshot["dashboard"]
    device = snapshot["device_agent"]
    telemetry = snapshot["telemetry"]
    return {
        "schema_version": 1,
        "kind": "nexolab-forward-deployment-recovery-result",
        "status": "reconciled",
        "deployment_evidence_id": context["stamp"],
        "previous_source": context["prior_source"],
        "target_source": context["target_source"],
        "runtime_activated_at": context["mutation_started_at"],
        "recovered_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "control_origin_main": context["origin_main"],
        "runtime_mode": "lan",
        "platform": "linux/arm64",
        "schema_head": context["schema_head"],
        "dashboard": dashboard["url"],
        "api": telemetry["api"],
        "auth_mode": telemetry["auth_mode"],
        "local_auth_overlay": True,
        "dashboard_auth_provider": dashboard["runtime_contract"].get("auth_provider"),
        "dashboard_organization_id": dashboard["runtime_contract"].get("organization_id"),
        "dashboard_release_dir": dashboard["working_directory"],
        "dashboard_build_id": dashboard["build_id"],
        "device_agent_container_id": device["container_id"],
        "device_agent_image_id": device["image_id"],
        "device_agent_registry_revision": device["registry_revision"],
        "device_agent_queue_depth": device["queue_depth"],
        "device_agent_expected_bus_workers": device["expected_bus_workers"],
        "device_agent_active_bus_workers": device["active_bus_workers"],
        "edge_sqlite_quick_check": device["sqlite"]["quick_check"],
        "edge_sqlite_outbound_queue_count": device["sqlite"]["outbound_queue_count"],
        "edge_sqlite_outbound_queue_high_water": device["sqlite"]["outbound_queue_high_water"],
        "telemetry_service_container_id": telemetry["container_id"],
        "telemetry_service_image_id": telemetry["image_id"],
        "postgres_container_id": snapshot["postgres"]["container_id"],
        "postgres_volume_name": snapshot["postgres"]["volume_name"],
        "evidence_hashes": context["evidence_hashes"],
        "safety": {
            "runtime_mutation": "none",
            "edge_sqlite_write": "none",
            "postgres_write": "none",
            "modbus_write": "none",
            "hardware_write": "none",
        },
    }

def validate_result(document: dict[str, Any], context: dict[str, Any]) -> None:
    required_strings = (
        "deployment_evidence_id", "previous_source", "target_source", "runtime_activated_at",
        "recovered_at", "control_origin_main", "runtime_mode", "platform", "schema_head",
        "dashboard", "api", "auth_mode", "dashboard_auth_provider", "dashboard_release_dir",
        "dashboard_build_id", "device_agent_container_id", "device_agent_image_id",
        "telemetry_service_container_id", "telemetry_service_image_id", "postgres_container_id",
        "postgres_volume_name",
    )
    if document.get("schema_version") != 1 or document.get("kind") != "nexolab-forward-deployment-recovery-result":
        raise RecoveryFailure("forward recovery result contract is invalid")
    if document.get("status") != "reconciled":
        raise RecoveryFailure("forward recovery result is not reconciled")
    if any(not isinstance(document.get(key), str) or not document.get(key) for key in required_strings):
        raise RecoveryFailure("forward recovery result is incomplete")
    if document["deployment_evidence_id"] != context["stamp"]:
        raise RecoveryFailure("forward recovery result evidence id mismatch")
    if document["previous_source"] != context["prior_source"] or document["target_source"] != context["target_source"]:
        raise RecoveryFailure("forward recovery result source lineage mismatch")
    if not IMAGE_RE.fullmatch(document["device_agent_image_id"]):
        raise RecoveryFailure("forward recovery Device Agent image id is invalid")
    if document.get("evidence_hashes") != context["evidence_hashes"]:
        raise RecoveryFailure("forward recovery evidence hashes do not match immutable inputs")
    safety = document.get("safety")
    if not isinstance(safety, dict) or any(safety.get(key) != "none" for key in (
        "runtime_mutation", "edge_sqlite_write", "postgres_write", "modbus_write", "hardware_write"
    )):
        raise RecoveryFailure("forward recovery safety record is invalid")

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reconcile a healthy forward-mutated NEXOLAB deployment without data rollback.")
    result.add_argument("--repo", type=Path, default=Path.cwd())
    result.add_argument("--deployment-evidence", type=Path, required=True)
    result.add_argument("--expected-prior-source", required=True)
    result.add_argument("--expected-target-source", required=True)
    mode = result.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return result


def _partial_read(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise RecoveryFailure("partial continuation metadata path is missing or unsafe")
    return read_json(path, "partial continuation metadata")


def _partial_run(*command: str) -> str:
    # Never include raw Docker/systemd output or environment in failures.
    args = list(command)
    if args[0] == "docker":
        args[1:1] = ["--host", "unix:///var/run/docker.sock"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False,
                                env={key: value for key, value in os.environ.items()
                                     if key in {"PATH", "HOME", "LANG", "LC_ALL"}})
    except (OSError, subprocess.SubprocessError) as error:
        raise RecoveryFailure("partial continuation read-only command unavailable") from error
    if result.returncode:
        raise RecoveryFailure("partial continuation read-only command failed")
    return result.stdout.strip()


def _partial_http(host: str, port: int, route: str) -> dict[str, Any]:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://{host}:{port}{route}", timeout=3) as response:
            if response.status != 200:
                raise ValueError("HTTP not ready")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized health response")
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("invalid health response")
            return document
    except Exception as error:
        raise RecoveryFailure("partial continuation local health/identity check failed") from error


def _partial_container(document: dict[str, Any]) -> dict[str, Any]:
    config = document.get("Config") or {}
    labels = config.get("Labels") or {}
    state = document.get("State") or {}
    return {"id": document.get("Id"), "image_id": document.get("Image"),
            "project": labels.get("com.docker.compose.project"),
            "service": labels.get("com.docker.compose.service"), "running": state.get("Running"),
            "docker_health": (state.get("Health") or {}).get("Status"),
            "status": state.get("Status"), "oom_killed": state.get("OOMKilled"),
            "name": document.get("Name"), "user": config.get("User"), "working_dir": config.get("WorkingDir"),
            "named_volumes": [{"name": item.get("Name"), "target": item.get("Destination"), "rw": item.get("RW")}
                              for item in document.get("Mounts", []) if item.get("Type") == "volume"]}


def check_partial_volume_preservation(facts: dict[str, Any]) -> None:
    for item in facts["all_existing_volumes"]:
        documents = json.loads(_partial_run("docker", "volume", "inspect", item["Name"]))
        if len(documents) != 1 or {key: documents[0].get(key) for key in ("Name", "Driver", "Mountpoint", "CreatedAt")} != item:
            raise RecoveryFailure("partial continuation persistent volume identity drifted")


def check_partial_input_preservation(repo: Path, failed: Path, recovery_path: Path, context: dict[str, Any]) -> None:
    paths = {"snapshot_metadata": failed / "edge-sqlite-pre-cutover.json",
             "attempt_quiesce": failed / "edge-device-agent-quiesce.json",
             "attempt_mutation_marker": failed / "runtime-mutation-started", "prior_recovery": recovery_path,
             "volume_identities_before": failed / "volume-identities-before.json"}
    for key, path in paths.items():
        _safe_file(path, "preserved partial continuation evidence")
        if sha256_file(path) != context["input_hashes"][key]:
            raise RecoveryFailure("partial continuation original evidence changed")
    for name, digest in context["site_configuration_sha256"].items():
        if name not in {".env.central", ".env.edge-central"}:
            raise RecoveryFailure("partial continuation site configuration identity is invalid")
        path = _safe_file(repo / "infrastructure/compose" / name, "preserved site configuration")
        if sha256_file(path) != digest:
            raise RecoveryFailure("partial continuation site configuration changed")


def _partial_acquisition_window(scheduler: dict[str, Any]) -> float:
    # Legacy health documents retain the existing short, fail-closed deadline.
    if "targets" not in scheduler:
        return 15.0
    targets = scheduler["targets"]
    count = scheduler.get("configured_targets")
    if (not isinstance(targets, list) or not targets or len(targets) > 4096
        or type(count) is not int or count != len(targets)):
        raise RecoveryFailure("partial continuation acquisition cadence metadata is invalid")
    intervals = []
    for target in targets:
        interval = target.get("interval_seconds") if isinstance(target, dict) else None
        if (type(interval) not in (int, float) or interval <= 0 or interval > 86400
            or not math.isfinite(interval)):
            raise RecoveryFailure("partial continuation acquisition cadence metadata is invalid")
        intervals.append(interval)
    # At least one sample is required: use the fastest persisted target, with
    # two opportunities plus 10s scheduler allowance. Never wait indefinitely.
    return min(120.0, max(15.0, 2 * min(intervals) + 10.0))


def check_partial_acquisition(facts: dict[str, Any]) -> None:
    def health() -> tuple[int, dict[str, Any]]:
        value = _partial_http("127.0.0.1", 8081, "/health")
        scheduler = ((value.get("acquisition") or {}).get("scheduler") or {})
        expected_workers = scheduler.get("expected_bus_workers")
        if (value.get("status") != "ok" or value.get("mqtt_connected") is not True or value.get("queue_depth") != 0
            or scheduler.get("workers_healthy") is not True or type(expected_workers) is not int or expected_workers <= 0
            or expected_workers != facts["agent_health"][0]["expected_bus_workers"]
            or scheduler.get("active_bus_workers") != expected_workers or type(value.get("samples_total")) is not int
            or value["samples_total"] < 0):
            raise RecoveryFailure("partial continuation recovered agent is not operationally healthy")
        return value["samples_total"], scheduler
    first, scheduler = health()
    cadence_required = "targets" in scheduler
    deadline = time.monotonic() + _partial_acquisition_window(scheduler)
    while time.monotonic() < deadline:
        time.sleep(1)
        observed, scheduler = health()
        if cadence_required and "targets" not in scheduler:
            raise RecoveryFailure("partial continuation acquisition cadence metadata is invalid")
        _partial_acquisition_window(scheduler)  # Validate each poll; never extend the deadline.
        if observed < first:
            raise RecoveryFailure("partial continuation recovered acquisition counter reset")
        if time.monotonic() > deadline:
            break
        if observed > first:
            return
    raise RecoveryFailure("partial continuation recovered acquisition is not advancing")


def check_partial_live_baseline(facts: dict[str, Any]) -> None:
    if platform.machine() != "aarch64":
        raise RecoveryFailure("partial continuation is limited to the actual ARM64 host")
    expected = facts["containers"]
    observed = []
    telemetry = []
    for project in ("nexolab-central", "nexolab-edge"):
        ids = _partial_run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").split()
        if len(ids) > 30 or any(not re.fullmatch("[0-9a-f]{12,64}", item) for item in ids):
            raise RecoveryFailure("partial continuation container inventory is ambiguous")
        for identifier in ids:
            documents = json.loads(_partial_run("docker", "inspect", identifier))
            if not isinstance(documents, list) or len(documents) != 1 or not isinstance(documents[0], dict):
                raise RecoveryFailure("partial continuation container metadata is ambiguous")
            item = _partial_container(documents[0])
            observed.append(item)
            if item["project"] == "nexolab-central" and item["service"] == "telemetry-service":
                telemetry.append(documents[0])
    keys = ("id", "image_id", "project", "service", "running", "name", "user", "working_dir", "named_volumes", "docker_health", "status", "oom_killed")
    pinned = [{key: item.get(key) for key in keys} for item in expected]
    if sorted(pinned, key=lambda x: x["id"]) != sorted(observed, key=lambda x: x["id"]):
        raise RecoveryFailure("partial continuation live container/image/mount baseline drifted")
    check_partial_volume_preservation(facts)
    expected_names = {item["Name"] for item in facts["all_existing_volumes"]}
    if set(_partial_run("docker", "volume", "ls", "-q").splitlines()) != expected_names:
        raise RecoveryFailure("partial continuation full volume inventory drifted")
    for profile, port, unit in (("lan", 3000, "nexolab-dashboard.service"),
                                ("protected", 3100, "nexolab-external-frontend.service")):
        anchor = facts["frontends"][profile]
        state = _partial_run("systemctl", "show", unit, "-p", "WorkingDirectory", "-p", "MainPID", "-p", "ActiveState", "-p", "ExecStart")
        values = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
        pid = values.get("MainPID", "")
        if values.get("ActiveState") != "active" or not re.fullmatch("[1-9][0-9]{0,8}", pid):
            raise RecoveryFailure("partial continuation active frontend process missing")
        if re.findall(r'(?<!\S)--port(?:\s+|=)([0-9]+)(?=\s|[;}]|$)', values.get("ExecStart", "")) != [str(port)]:
            raise RecoveryFailure("partial continuation active frontend port drifted")
        if values.get("WorkingDirectory") != anchor["unit"]["WorkingDirectory"] or os.readlink(f"/proc/{pid}/cwd") != anchor["process_cwd"]:
            raise RecoveryFailure("partial continuation frontend process baseline drifted")
        identity = _partial_http("127.0.0.1", port, "/api/runtime-identity")
        if any(identity.get(key) != anchor["identity"].get(key) for key in ("schema_version", "service", "source_commit", "build_id")):
            raise RecoveryFailure("partial continuation frontend source/build baseline drifted")
    endpoint = facts["central_ready"]["endpoint"]
    host, port = endpoint
    if len(telemetry) != 1:
        raise RecoveryFailure("partial continuation central service is ambiguous")
    bindings = (telemetry[0].get("HostConfig", {}).get("PortBindings") or {}).get("8082/tcp")
    addresses = json.loads(_partial_run("ip", "-j", "-4", "address", "show"))
    local = {item.get("local") for address in addresses for item in address.get("addr_info", []) if item.get("family") == "inet"}
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise RecoveryFailure("partial continuation central socket is ambiguous")
    binding = bindings[0]
    bound_host = binding.get("HostIp") or "0.0.0.0"
    normalized = "127.0.0.1" if bound_host == "0.0.0.0" or ipaddress.IPv4Address(bound_host).is_loopback else bound_host
    if host != normalized or int(binding["HostPort"]) != port or (host != "127.0.0.1" and host not in local):
        raise RecoveryFailure("partial continuation central socket baseline drifted")
    ready = _partial_http(host, port, "/health/ready")
    if any(ready.get(key) != "ready" for key in ("status", "database", "mqtt")):
        raise RecoveryFailure("partial continuation central readiness failed")
    check_partial_acquisition(facts)


def validate_partial_continuation(repo: Path, evidence: Path, previous: str, target: str,
                                  capture_path: Path, capture_digest: str, recovery_path: Path) -> dict[str, Any]:
    """Validate a partial baseline; never declare it a completed deployment.

    Only the explicit deploy continuation calls this. The normal unresolved-
    mutation gate remains closed. It reads metadata and live identities/health,
    without writing runtime, authority, SQLite or PostgreSQL.
    """
    repo = repo.resolve()
    failed = evidence.resolve()
    if evidence.is_symlink() or failed.parent != (repo / "runtime/deployments").resolve() or not _valid_stamp(failed.name):
        raise RecoveryFailure("partial continuation must select one canonical failed deployment")
    if not SHA_RE.fullmatch(previous) or not SHA_RE.fullmatch(target):
        raise RecoveryFailure("partial continuation source pins must be full SHAs")
    for filename in ("final-state.txt", "edge-sqlite-restore-result.json", RESULT_NAME):
        if (failed / filename).exists():
            raise RecoveryFailure("partial continuation cannot reuse completed or restored deployment evidence")
    summary = _safe_file(failed / "summary.txt", "failed deployment summary")
    if "DEPLOYMENT PASSED" in summary.read_text():
        raise RecoveryFailure("partial continuation cannot reuse a successful attempt")
    ensure_no_newer_mutation(repo, failed.name)
    marker = parse_key_values(failed / "runtime-mutation-started", "failed mutation marker")
    snapshot_path = failed / "edge-sqlite-pre-cutover.json"
    quiesce_path = failed / "edge-device-agent-quiesce.json"
    snapshot = _partial_read(snapshot_path)
    quiesce = _partial_read(quiesce_path)
    if (marker.get("source") != target or not marker.get("started_at")
        or snapshot.get("kind") != "nexolab-edge-sqlite-pre-cutover" or snapshot.get("schema_version") != 1
        or snapshot.get("deployment_evidence_id") != failed.name or snapshot.get("deployed_source") != previous
        or snapshot.get("target_source") != target or snapshot.get("source_quick_check") != "ok"
        or snapshot.get("snapshot_quick_check") != "ok"):
        raise RecoveryFailure("partial continuation failed-attempt source/snapshot lineage mismatch")
    image = snapshot.get("deployed_device_agent_image_id")
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image) or quiesce.get("kind") != "nexolab-edge-device-agent-quiesce" or quiesce.get("schema_version") != 1 or quiesce.get("image_id") != image or quiesce.get("target_source") != target or quiesce.get("deployment_evidence_id") != failed.name:
        raise RecoveryFailure("partial continuation exact quiesced agent image mismatch")
    capture = _partial_read(capture_path)
    if not re.fullmatch("[0-9a-f]{64}", capture_digest) or sha256_file(capture_path) != capture_digest:
        raise RecoveryFailure("partial continuation capture digest mismatch")
    if (capture.get("kind") != "nexolab-unified-runtime-check-1323" or capture.get("capture_version") != 2
        or capture.get("status") != "captured" or capture.get("runtime_mutation") != "none"):
        raise RecoveryFailure("partial continuation requires corrected complete read-only capture")
    facts = capture.get("facts")
    if not isinstance(facts, dict):
        raise RecoveryFailure("partial continuation capture facts missing")
    paths = {"snapshot_metadata": snapshot_path, "attempt_quiesce": quiesce_path,
             "attempt_mutation_marker": failed / "runtime-mutation-started", "prior_recovery": recovery_path}
    for key, path in paths.items():
        _safe_file(path, "partial continuation immutable input")
        if (facts.get(key) or {}).get("metadata_sha256") != sha256_file(path):
            raise RecoveryFailure("partial continuation immutable input hash mismatch")
    recovered = _partial_read(recovery_path)
    if (recovered.get("status") != "agent_recovery_verified" or recovered.get("runtime_mutation") != "device_agent_only"
        or recovered.get("database_restore") != "none" or recovered.get("package_authority") != "not_modified"
        or recovered.get("persistent_volume_identity") != "all_existing_unchanged"
        or recovered.get("non_agent_containers") != "unchanged" or recovered.get("recovery_image_id") != image):
        raise RecoveryFailure("partial continuation requires exact verified data-preserving agent-only recovery")
    containers = facts.get("containers")
    if not isinstance(containers, list) or not containers or any(not isinstance(x, dict) or not re.fullmatch("[0-9a-f]{64}", str(x.get("id", ""))) for x in containers) or len({x["id"] for x in containers}) != len(containers):
        raise RecoveryFailure("partial continuation captured containers are invalid")
    agents = [x for x in containers if x.get("project") == "nexolab-edge" and x.get("service") == "device-agent"]
    if len(agents) != 1 or agents[0].get("id") != recovered.get("recovered_container_id") or agents[0].get("image_id") != image or agents[0].get("running") is not True:
        raise RecoveryFailure("partial continuation recovered container/image binding mismatch")
    volumes = facts.get("all_existing_volumes")
    if not isinstance(volumes, list) or not volumes or any(not isinstance(x, dict) or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", str(x.get("Name", ""))) for x in volumes) or len({x["Name"] for x in volumes}) != len(volumes):
        raise RecoveryFailure("partial continuation volume inventory is empty or ambiguous")
    if facts.get("existing_volume_count") != len(volumes):
        raise RecoveryFailure("partial continuation capture did not retain its whole volume inventory")
    baseline_path = _safe_file(failed / "volume-identities-before.json", "failed volume baseline")
    baseline_volumes = json.loads(baseline_path.read_text())
    captured_volumes = {x["Name"]: x for x in volumes}
    if not isinstance(baseline_volumes, list) or not baseline_volumes or any(not isinstance(x, dict) or captured_volumes.get(x.get("Name")) != {key: x.get(key) for key in ("Name", "Driver", "Mountpoint", "CreatedAt")} for x in baseline_volumes):
        raise RecoveryFailure("partial continuation captured volumes do not match canonical failed baseline")
    health = facts.get("agent_health")
    if (not isinstance(health, list) or len(health) != 2 or any(not isinstance(x, dict) for x in health)
        or any(x.get("status") != "ok" or x.get("mqtt_connected") is not True or x.get("workers_healthy") is not True
               or type(x.get("expected_bus_workers")) is not int or x["expected_bus_workers"] <= 0
               or x.get("active_bus_workers") != x["expected_bus_workers"] or type(x.get("samples_total")) is not int for x in health)
        or health[1]["samples_total"] <= health[0]["samples_total"]):
        raise RecoveryFailure("partial continuation captured acquisition evidence is not healthy and advancing")
    for profile, port in (("lan", 3000), ("protected", 3100)):
        front = (facts.get("frontends") or {}).get(profile) or {}
        identity = front.get("identity") or {}
        if (front.get("http_status") != 200 or front.get("active_port") != port or front.get("port_contract_verified") is not True
            or identity.get("schema_version") != "nexolab-runtime-identity-v1" or identity.get("service") != "dashboard"
            or not SHA_RE.fullmatch(str(identity.get("source_commit", ""))) or not identity.get("build_id")
            or not (front.get("unit") or {}).get("WorkingDirectory") or front.get("process_cwd") != front["unit"]["WorkingDirectory"]):
            raise RecoveryFailure("partial continuation active frontend identity is incomplete")
    ready = facts.get("central_ready") or {}
    endpoint = ready.get("endpoint")
    if not isinstance(endpoint, list) or len(endpoint) != 2 or type(endpoint[1]) is not int or not 1 <= endpoint[1] <= 65535 or any(ready.get(key) != "ready" for key in ("status", "database", "mqtt")):
        raise RecoveryFailure("partial continuation captured central readiness is incomplete")
    try:
        ipaddress.IPv4Address(endpoint[0])
    except (ValueError, TypeError) as error:
        raise RecoveryFailure("partial continuation central address is invalid") from error
    check_partial_live_baseline(facts)
    paths["volume_identities_before"] = baseline_path
    configuration_hashes = {}
    for name in (".env.central", ".env.edge-central"):
        path = _safe_file(repo / "infrastructure/compose" / name, "existing site configuration")
        configuration_hashes[name] = sha256_file(path)
    return {"kind": "nexolab-partial-activation-continuation", "schema_version": 1,
            "status": "validated_partial_baseline", "baseline_scope": "partial_only_not_deployment_authority",
            "failed_deployment_evidence_id": failed.name, "previous_source": previous, "target_source": target,
            "recovered_device_agent_image_id": image, "recovered_device_agent_container_id": agents[0]["id"],
            "capture_sha256": capture_digest, "input_hashes": {key: sha256_file(path) for key, path in paths.items()},
            "site_configuration_sha256": configuration_hashes,
            "preservation": "retain_live_SQLite_outbox_PostgreSQL_and_all_existing_volumes;_no_restore"}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = args.repo.resolve()
    evidence = args.deployment_evidence
    if not evidence.is_absolute():
        evidence = repo / evidence
    try:
        context = build_context(repo, evidence, args.expected_prior_source, args.expected_target_source)
        snapshot = collect_runtime_snapshot(context)
        validate_runtime_snapshot(snapshot, context)
        result = build_result(snapshot, context)
        validate_result(result, context)
        result_path = context["evidence"] / RESULT_NAME
        if args.execute:
            atomic_json(result_path, result)
        elif result_path.exists():
            existing = read_json(result_path, "existing forward recovery result")
            validate_result(existing, context)
        print(f"FORWARD_RECOVERY_{'RECORDED' if args.execute else 'VALIDATED'}")
        print(f"target_source={context['target_source']}")
        print(f"device_agent_image_id={result['device_agent_image_id']}")
        print(f"schema_head={context['schema_head']}")
        print(f"evidence={context['evidence']}")
        return 0
    except RecoveryFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
