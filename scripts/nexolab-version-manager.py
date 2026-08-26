#!/usr/bin/env python3
"""Host-side executor for bounded NEXOLAB offline update and rollback requests."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


OPERATION_PHASES = (
    "verifying_package",
    "checking_capacity",
    "creating_backup",
    "applying_update",
    "verifying_runtime",
    "done",
)
DEVICE_AGENT_HEALTH_URL = "http://127.0.0.1:8081/health"
DEFAULT_POST_UPDATE_OBSERVATION_SECONDS = 60
DEFAULT_POST_UPDATE_POLL_SECONDS = 3
SOURCE_DEPLOYMENT_AUTHORITY = "controlled_source_deployment"
PACKAGED_DEPLOYMENT_AUTHORITY = "validated_package"
SOURCE_DASHBOARD_SERVICE = "nexolab-dashboard.service"
OFFLINE_IMAGE_ENV = {
    "dashboard": "OFFLINE_DASHBOARD_IMAGE",
    "telemetry-service": "OFFLINE_TELEMETRY_IMAGE",
    "device-agent": "OFFLINE_DEVICE_AGENT_IMAGE",
    "mqtt": "OFFLINE_MQTT_IMAGE",
    "postgres": "OFFLINE_POSTGRES_IMAGE",
    "minio": "OFFLINE_MINIO_IMAGE",
    "minio-client": "OFFLINE_MINIO_CLIENT_IMAGE",
}
CENTRAL_PERSISTENT_VOLUMES = (
    "nexolab-central-postgres-data",
    "nexolab-central-mqtt-data",
    "nexolab-central-object-storage-data",
    "nexolab-central-telemetry-ingestion-data",
)
EDGE_PERSISTENT_VOLUMES = (
    "nexolab-edge_edge-data",
    "nexolab-edge_mqtt-data",
)


class VersionManagerFailure(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise VersionManagerFailure(f"{path} must contain a JSON object")
    return payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
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


def enter_phase(operation_path: Path, operation: dict[str, Any], phase: str) -> None:
    if phase not in OPERATION_PHASES:
        raise VersionManagerFailure(f"unsupported operation phase: {phase}")
    completed = operation.get("completed_phases")
    if not isinstance(completed, list):
        completed = []
    previous = operation.get("phase")
    if isinstance(previous, str) and previous in OPERATION_PHASES and previous != phase:
        if previous not in completed:
            completed.append(previous)
    operation["completed_phases"] = completed
    operation["phase"] = phase
    operation["phase_status"] = "running" if phase != "done" else "succeeded"
    atomic_json(operation_path, operation)


def fail_current_phase(operation: dict[str, Any]) -> None:
    if operation.get("phase") in OPERATION_PHASES:
        operation["phase_status"] = "failed"


def manifest_digest(bundle_root: Path) -> str:
    return hashlib.sha256((bundle_root / "manifest.json").read_bytes()).hexdigest()


def verify_bundle(bundle_root: Path) -> dict[str, Any]:
    verifier = bundle_root / "scripts" / "verify-offline-bundle.py"
    if not verifier.is_file():
        raise VersionManagerFailure("bundle verifier is missing")
    subprocess.run([sys.executable, str(verifier), str(bundle_root)], check=True)
    manifest = load_json(bundle_root / "manifest.json")
    management = manifest.get("version_management")
    if not isinstance(management, dict) or not management.get("bundle_id"):
        raise VersionManagerFailure("bundle has no version-management identity")
    return manifest


def stage(args: argparse.Namespace) -> None:
    source = args.bundle.resolve()
    manifest = verify_bundle(source)
    bundle_id = str(manifest["version_management"]["bundle_id"])
    destination = args.root.resolve() / "catalog" / bundle_id
    if destination.exists():
        raise VersionManagerFailure(f"catalog entry already exists: {bundle_id}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = destination.with_name(f".{bundle_id}.{os.getpid()}.staging")
    try:
        shutil.copytree(source, temporary, symlinks=False)
        copied_manifest = verify_bundle(temporary)
        if copied_manifest["version_management"]["bundle_id"] != bundle_id:
            raise VersionManagerFailure("copied bundle identity changed")
        atomic_json(
            temporary / ".nexolab-validated.json",
            {
                "schema_version": 1,
                "manifest_sha256": manifest_digest(temporary),
                "validated_at": now(),
            },
        )
        os.chmod(temporary / ".nexolab-validated.json", 0o644)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(json.dumps({"status": "staged", "bundle_id": bundle_id}, sort_keys=True))


def bootstrap(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    bundle_root = root / "catalog" / args.bundle_id
    manifest = verify_staged_bundle(bundle_root, args.bundle_id)
    schema = manifest["version_management"]["database_schema"]
    current_path = root / "current.json"
    if current_path.exists():
        raise VersionManagerFailure("current deployment evidence already exists")
    atomic_json(
        current_path,
        {
            "schema_version": 1,
            "bundle_id": args.bundle_id,
            "bundle_root": str(bundle_root),
            "release": manifest["bundle_version"],
            "source_commit": manifest["source_commit"],
            "build_timestamp": manifest["created_at"],
            "runtime_mode": args.runtime_mode,
            "platform": manifest["platform"],
            "schema_head": args.schema_head or schema["head"],
            "deployed_at": args.deployed_at or now(),
            "health": args.health,
            "runtime_state_known": True,
            "previous_bundle_id": None,
            "previous_release": None,
            "last_operation_id": None,
        },
    )
    print(json.dumps({"status": "bootstrapped", "bundle_id": args.bundle_id}, sort_keys=True))


def verify_staged_bundle(bundle_root: Path, expected_id: str) -> dict[str, Any]:
    manifest = verify_bundle(bundle_root)
    if manifest["version_management"]["bundle_id"] != expected_id:
        raise VersionManagerFailure("target bundle ID does not match its catalog directory")
    marker = load_json(bundle_root / ".nexolab-validated.json")
    if marker.get("manifest_sha256") != manifest_digest(bundle_root):
        raise VersionManagerFailure("target validation marker is stale or invalid")
    expected_platform = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
    if expected_platform is None or manifest.get("platform") != expected_platform:
        raise VersionManagerFailure("target package platform does not match this host")
    return manifest


def compose_args(bundle_root: Path, env_path: Path, *, central: bool, local_auth: bool) -> list[str]:
    side = "central" if central else "edge"
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_path),
        "-f",
        str(bundle_root / "deploy" / "compose" / f"compose.{side}.yaml"),
        "-f",
        str(bundle_root / "deploy" / "offline" / f"compose.{side}.offline.yaml"),
    ]
    if central and local_auth:
        command.extend(
            ["-f", str(bundle_root / "deploy" / "compose" / "compose.local-auth.yaml")]
        )
    return command


def deployed_schema_after(action: str, current_schema: str, target_schema: str) -> str:
    if action == "update":
        return target_schema
    if action == "rollback":
        return current_schema
    raise VersionManagerFailure("unsupported version operation")


def run_capacity_preflight(root: Path, operation_id: str) -> str:
    guard = Path(__file__).resolve().with_name("deploy-capacity-guard.sh")
    if not guard.is_file():
        raise VersionManagerFailure("deployment capacity guard is missing")
    evidence_dir = root / "operation-evidence" / operation_id
    report = evidence_dir / "capacity-preflight.txt"
    subprocess.run(
        [
            "bash",
            str(guard),
            "--repo",
            str(root),
            "--audit-dir",
            str(evidence_dir),
            "--report",
            str(report),
        ],
        check=True,
    )
    if not report.is_file():
        raise VersionManagerFailure("deployment capacity evidence was not created")
    facts: dict[str, str] = {}
    for raw in report.read_text(encoding="utf-8").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            facts[key] = value
    if facts.get("status") != "PASS":
        raise VersionManagerFailure("deployment capacity preflight did not pass")
    return str(report.relative_to(root))


def read_local_json(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "NEXOLAB-version-manager"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        TimeoutError,
        UnicodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        raise VersionManagerFailure(f"local runtime verification failed for {url}") from error
    if not isinstance(payload, dict):
        raise VersionManagerFailure(f"local runtime verification returned invalid JSON for {url}")
    return payload


def _device_agent_facts(payload: dict[str, Any]) -> tuple[int, int, bool, str | None]:
    if payload.get("status") not in {"ok", "degraded"}:
        raise VersionManagerFailure("Device Agent health is not usable after version activation")
    acquisition = payload.get("acquisition")
    scheduler = acquisition.get("scheduler") if isinstance(acquisition, dict) else None
    if not isinstance(scheduler, dict):
        raise VersionManagerFailure("Device Agent scheduler health evidence is missing")
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
        raise VersionManagerFailure("Device Agent bus workers are not healthy after version activation")
    latest = payload.get("latest_values")
    last_attempt_at = latest.get("last_attempt_at") if isinstance(latest, dict) else None
    if last_attempt_at is not None and not isinstance(last_attempt_at, str):
        raise VersionManagerFailure("Device Agent telemetry freshness evidence is invalid")
    return expected, active, True, last_attempt_at


def verify_device_agent_progress(
    *,
    observation_seconds: int = DEFAULT_POST_UPDATE_OBSERVATION_SECONDS,
    poll_seconds: int = DEFAULT_POST_UPDATE_POLL_SECONDS,
) -> dict[str, Any]:
    observation_seconds = max(1, observation_seconds)
    poll_seconds = max(1, min(poll_seconds, observation_seconds))
    deadline = time.monotonic() + observation_seconds
    baseline: str | None = None
    expected = 0
    active = 0

    while time.monotonic() < deadline:
        payload = read_local_json(DEVICE_AGENT_HEALTH_URL)
        expected, active, _, last_attempt_at = _device_agent_facts(payload)
        if last_attempt_at:
            if baseline is None:
                baseline = last_attempt_at
            elif last_attempt_at != baseline:
                return {
                    "status": "verified",
                    "expected_bus_workers": expected,
                    "active_bus_workers": active,
                    "workers_healthy": True,
                    "baseline_last_attempt_at": baseline,
                    "advanced_last_attempt_at": last_attempt_at,
                }
        time.sleep(poll_seconds)

    if baseline is None:
        raise VersionManagerFailure("Device Agent produced no telemetry attempt during post-update observation")
    raise VersionManagerFailure("Device Agent telemetry did not advance during post-update observation")



def require_exact_alembic_head(output: str, expected: str) -> None:
    revisions = [line.strip().split()[0] for line in output.splitlines() if line.strip()]
    if revisions != [expected]:
        raise VersionManagerFailure(
            f"deployed database revision must be exactly one expected head: {expected}"
        )


def wait_http_success(url: str, *, attempts: int = 30, delay_seconds: float = 1.0) -> None:
    for _ in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, TimeoutError, urllib.error.URLError):
            pass
        time.sleep(delay_seconds)
    raise VersionManagerFailure(f"HTTP readiness did not recover: {url}")


def expected_real_hardware_contract(args: argparse.Namespace) -> dict[str, str]:
    if args.skip_edge or args.edge_env is None:
        raise VersionManagerFailure("source-to-package authority requires the real edge runtime")
    env = parse_env_file(args.edge_env.resolve())
    serial = env.get("RS485_HOST_DEVICE", "")
    if not serial.startswith("/dev/serial/by-id/"):
        raise VersionManagerFailure("real hardware transition requires stable RS485_HOST_DEVICE identity")
    configured_mode = env.get("HARDWARE_DEVICE_MODE", "xjp60d").strip().lower()
    if configured_mode in {"simulator", "simulation", "demo", "mock", "disabled"}:
        raise VersionManagerFailure("real hardware transition refuses simulator/demo/mock device mode")
    return {
        "configured_mode": configured_mode,
        "host_serial_device": serial,
        "container_serial_device": f"/host{serial}",
    }


def verify_real_hardware_runtime(args: argparse.Namespace) -> dict[str, Any]:
    expected = expected_real_hardware_contract(args)
    payload = read_local_json(DEVICE_AGENT_HEALTH_URL)
    if payload.get("status") not in {"ok", "degraded"}:
        raise VersionManagerFailure("Device Agent real-hardware health is unavailable")
    if payload.get("device_mode") != "modbus":
        raise VersionManagerFailure("Device Agent is not running the real Modbus hardware path")
    acquisition = payload.get("acquisition")
    request_series = acquisition.get("request_series") if isinstance(acquisition, dict) else None
    if not isinstance(request_series, list) or not request_series:
        raise VersionManagerFailure("Device Agent real-hardware request evidence is missing")
    buses: set[str] = set()
    successful_requests = 0
    for item in request_series:
        if not isinstance(item, dict):
            continue
        bus = item.get("bus")
        if isinstance(bus, str) and bus.startswith("/host/dev/serial/by-id/"):
            buses.add(bus)
        outcome = item.get("outcome")
        requests_total = item.get("requests_total")
        if outcome == "success" and isinstance(requests_total, int) and not isinstance(requests_total, bool):
            successful_requests += requests_total
        outcomes = item.get("outcomes")
        if isinstance(outcomes, dict):
            success = outcomes.get("success")
            if isinstance(success, int) and not isinstance(success, bool):
                successful_requests += success
    if expected["container_serial_device"] not in buses:
        raise VersionManagerFailure("Device Agent is not using the expected stable RS-485 identity")
    if successful_requests <= 0:
        raise VersionManagerFailure("Device Agent has no successful real-hardware request evidence")
    return {
        "status": "verified",
        "device_mode": "modbus",
        "configured_mode": expected["configured_mode"],
        "host_serial_device": expected["host_serial_device"],
        "observed_buses": sorted(buses),
        "successful_requests": successful_requests,
    }


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_local_auth_host_paths(central_env: Path) -> dict[str, str]:
    env_path = central_env.resolve()
    values = parse_env_file(env_path)
    resolved: dict[str, str] = {}
    for key in ("AUTH_LOCAL_PRIVATE_KEY_HOST_FILE", "AUTH_LOCAL_PUBLIC_KEY_HOST_FILE"):
        raw = values.get(key, "").strip()
        if not raw:
            raise VersionManagerFailure(f"local-auth external host path is missing: {key}")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = env_path.parent / candidate
        candidate = candidate.resolve()
        if not candidate.is_file() or not os.access(candidate, os.R_OK):
            raise VersionManagerFailure(f"local-auth external host file is not readable: {key}")
        resolved[key] = str(candidate)
    return resolved


def local_auth_subprocess_env(args: argparse.Namespace) -> dict[str, str] | None:
    if not args.local_auth:
        return None
    environment = os.environ.copy()
    environment.update(resolve_local_auth_host_paths(args.central_env))
    return environment


def source_deployment_identity(current: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    required = (
        "source_dashboard_origin",
        "source_auth_mode",
        "source_local_auth_overlay",
        "source_dashboard_auth_provider",
    )
    if all(key in current for key in required):
        return dict(current)

    evidence = current.get("source_deployment_evidence")
    if not isinstance(evidence, str) or not evidence:
        raise VersionManagerFailure("source deployment evidence path is missing")
    source_repo = Path(
        getattr(args, "source_repo", Path(__file__).resolve().parents[1])
    ).resolve()
    deployments_root = (source_repo / "runtime" / "deployments").resolve()
    evidence_path = (source_repo / evidence).resolve()
    try:
        evidence_path.relative_to(deployments_root)
    except ValueError as error:
        raise VersionManagerFailure("source deployment evidence must remain under runtime/deployments") from error
    facts_path = evidence_path / "final-state.txt"
    if not facts_path.is_file():
        raise VersionManagerFailure("source deployment final-state evidence is missing")
    facts = parse_env_file(facts_path)
    if facts.get("commit") != current.get("source_commit"):
        raise VersionManagerFailure("source deployment evidence commit does not match current lineage")
    if facts.get("runtime_mode") != current.get("runtime_mode"):
        raise VersionManagerFailure("source deployment evidence runtime mode does not match current lineage")
    required_facts = {
        "dashboard",
        "auth_mode",
        "local_auth_overlay",
        "dashboard_auth_provider",
    }
    missing = sorted(required_facts - facts.keys())
    if missing:
        raise VersionManagerFailure(f"source deployment authentication evidence is incomplete: {missing}")

    enriched = dict(current)
    enriched["source_dashboard_origin"] = facts["dashboard"]
    enriched["source_auth_mode"] = facts["auth_mode"]
    enriched["source_local_auth_overlay"] = facts["local_auth_overlay"] == "true"
    enriched["source_dashboard_auth_provider"] = facts["dashboard_auth_provider"]
    return enriched


def source_dashboard_state(current: dict[str, Any]) -> dict[str, Any]:
    origin = current.get("source_dashboard_origin")
    if not isinstance(origin, str) or not origin.startswith("http"):
        raise VersionManagerFailure("source dashboard origin evidence is missing")
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", SOURCE_DASHBOARD_SERVICE], check=False
    ).returncode == 0
    enabled = subprocess.run(
        ["systemctl", "is-enabled", "--quiet", SOURCE_DASHBOARD_SERVICE], check=False
    ).returncode == 0
    if not active:
        raise VersionManagerFailure("controlled source dashboard service is not active")
    return {"active": active, "enabled": enabled, "origin": origin}


def stop_source_dashboard() -> None:
    subprocess.run(["systemctl", "stop", SOURCE_DASHBOARD_SERVICE], check=True)
    if subprocess.run(
        ["systemctl", "is-active", "--quiet", SOURCE_DASHBOARD_SERVICE], check=False
    ).returncode == 0:
        raise VersionManagerFailure("source dashboard service did not stop before packaged activation")


def stop_packaged_dashboard(
    target_root: Path, args: argparse.Namespace, *, compose_env: dict[str, str] | None = None
) -> None:
    central = compose_args(
        target_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
    )
    subprocess.run(
        central + ["stop", "dashboard"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=compose_env,
    )


def restore_source_dashboard(
    target_root: Path,
    args: argparse.Namespace,
    state: dict[str, Any],
    *,
    compose_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    stop_packaged_dashboard(target_root, args, compose_env=compose_env)
    if state.get("enabled") is True:
        subprocess.run(["systemctl", "enable", SOURCE_DASHBOARD_SERVICE], check=True)
    subprocess.run(["systemctl", "start", SOURCE_DASHBOARD_SERVICE], check=True)
    wait_http_success(str(state["origin"]))
    return {"status": "restored", "service": SOURCE_DASHBOARD_SERVICE}


def source_central_compose_args(
    source_repo: Path, env_path: Path, *, runtime_mode: str, local_auth: bool
) -> list[str]:
    compose_dir = source_repo.resolve() / "infrastructure" / "compose"
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_path.resolve()),
        "-f",
        str(compose_dir / "compose.central.yaml"),
        "-f",
        str(compose_dir / "compose.observability.yaml"),
    ]
    if runtime_mode == "standalone":
        command.extend(["-f", str(compose_dir / "compose.central-standalone.yaml")])
    if local_auth:
        command.extend(["-f", str(compose_dir / "compose.local-auth.yaml")])
    return command


def restore_source_runtime(
    target_root: Path, target: dict[str, Any], current: dict[str, Any],
    args: argparse.Namespace, dashboard_state: dict[str, Any],
    *, compose_env: dict[str, str] | None,
) -> dict[str, Any]:
    source_repo = Path(getattr(args, "source_repo", Path(__file__).resolve().parents[1]))
    central = source_central_compose_args(
        source_repo, args.central_env, runtime_mode=str(current["runtime_mode"]),
        local_auth=args.local_auth,
    )
    subprocess.run(central + ["up", "-d", "--no-build", "--pull", "never"],
                   check=True, env=compose_env)
    dashboard = target.get("dashboard")
    api_base = dashboard.get("api_base_url") if isinstance(dashboard, dict) else None
    if not isinstance(api_base, str) or not api_base:
        raise VersionManagerFailure("source recovery API base URL is missing")
    wait_http_success(f"{api_base.rstrip('/')}/health/ready")
    readiness = read_local_json(f"{api_base.rstrip('/')}/health/ready")
    if readiness.get("status") != "ready" or readiness.get("database") != "ready" or readiness.get("mqtt") != "ready":
        raise VersionManagerFailure("source central runtime did not recover readiness")
    dashboard_restore = restore_source_dashboard(
        target_root, args, dashboard_state, compose_env=compose_env
    )
    return {"status": "restored", "central_readiness": readiness,
            "dashboard": dashboard_restore}


def commit_source_dashboard_handoff() -> None:
    subprocess.run(["systemctl", "disable", SOURCE_DASHBOARD_SERVICE], check=True)


def assert_no_active_version_operation(root: Path) -> None:
    if any((root / "requests").glob("*.json")):
        raise VersionManagerFailure("a version update or rollback request is already queued")
    for path in (root / "operations").glob("*.json"):
        operation = load_json(path)
        if operation.get("status") in {"queued", "running"}:
            raise VersionManagerFailure("a version update or rollback operation is active")


def persistent_volume_names(*, skip_edge: bool) -> tuple[str, ...]:
    return CENTRAL_PERSISTENT_VOLUMES if skip_edge else CENTRAL_PERSISTENT_VOLUMES + EDGE_PERSISTENT_VOLUMES


def capture_volume_identities(*, skip_edge: bool) -> list[dict[str, Any]]:
    names = persistent_volume_names(skip_edge=skip_edge)
    result = subprocess.run(
        ["docker", "volume", "inspect", *names],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise VersionManagerFailure("Docker volume identity output is invalid")
    identities: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("Name") not in names:
            raise VersionManagerFailure("Docker volume identity output contains an unexpected volume")
        identities.append(
            {
                "name": item.get("Name"),
                "driver": item.get("Driver"),
                "mountpoint": item.get("Mountpoint"),
                "created_at": item.get("CreatedAt"),
                "scope": item.get("Scope"),
            }
        )
    if {item["name"] for item in identities} != set(names):
        raise VersionManagerFailure("one or more required persistent volume identities are missing")
    return sorted(identities, key=lambda item: str(item["name"]))


def create_postgresql_backup(
    central: list[str], backup_dir: Path, backup_id: str,
    *, compose_env: dict[str, str] | None = None,
) -> Path:
    backup_path = backup_dir.resolve() / backup_id
    partial_backup_path = backup_path.with_suffix(".dump.partial")
    backup_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    with partial_backup_path.open("xb") as output:
        subprocess.run(
            central
            + [
                "exec",
                "-T",
                "postgres",
                "sh",
                "-ec",
                'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ],
            check=True,
            stdout=output,
            env=compose_env,
        )
    if partial_backup_path.stat().st_size == 0:
        raise VersionManagerFailure("PostgreSQL backup is empty")
    with partial_backup_path.open("rb") as backup_input:
        subprocess.run(
            central + ["exec", "-T", "postgres", "pg_restore", "--list"],
            check=True,
            stdin=backup_input,
            stdout=subprocess.DEVNULL,
            env=compose_env,
        )
    os.replace(partial_backup_path, backup_path)
    return backup_path


def activate_offline_image_environment(manifest: dict[str, Any]) -> dict[str, str]:
    images = manifest.get("images")
    if not isinstance(images, list):
        raise VersionManagerFailure("offline package image inventory is missing")
    references: dict[str, str] = {}
    for item in images:
        if not isinstance(item, dict):
            continue
        logical_id = item.get("id")
        reference = item.get("reference")
        if logical_id in OFFLINE_IMAGE_ENV:
            if logical_id in references or not isinstance(reference, str) or not reference:
                raise VersionManagerFailure("offline package image inventory is invalid")
            references[str(logical_id)] = reference
    missing = sorted(set(OFFLINE_IMAGE_ENV) - set(references))
    if missing:
        raise VersionManagerFailure(f"offline package image inventory is incomplete: {missing}")
    applied: dict[str, str] = {}
    for logical_id, variable in OFFLINE_IMAGE_ENV.items():
        reference = references[logical_id]
        os.environ[variable] = reference
        applied[variable] = reference
    return applied


def validate_package_tooling(bundle_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    provenance = load_json(bundle_root / "evidence" / "provenance.json")
    source_commit = manifest.get("source_commit")
    if provenance.get("source_commit") != source_commit:
        raise VersionManagerFailure("package provenance source commit does not match manifest")
    tooling_commit = provenance.get("tooling_commit")
    if not isinstance(tooling_commit, str) or len(tooling_commit) != 40 or any(
        char not in "0123456789abcdef" for char in tooling_commit.lower()
    ):
        raise VersionManagerFailure("package tooling commit evidence is missing or invalid")
    capabilities = provenance.get("tooling_capabilities")
    required_capabilities = {"runtime-mode", "hardware", "split-runtime-tooling"}
    if not isinstance(capabilities, list) or not required_capabilities.issubset(set(capabilities)):
        raise VersionManagerFailure("package tooling capability evidence is incomplete")
    installer = bundle_root / "scripts" / "install-offline-bundle.sh"
    if not installer.is_file():
        raise VersionManagerFailure("package installer is missing")
    required_overlays = (
        "compose.hardware.yaml",
        "compose.edge-central-bridge.yaml",
        "compose.edge-standalone.yaml",
        "compose.central-standalone.yaml",
    )
    missing = [
        name for name in required_overlays
        if not (bundle_root / "deploy" / "compose" / name).is_file()
    ]
    if missing:
        raise VersionManagerFailure(f"package runtime overlays are incomplete: {missing}")
    return {
        "source_commit": source_commit,
        "tooling_commit": tooling_commit,
        "tooling_capabilities": sorted(required_capabilities),
    }


def offline_installer_command(
    bundle_root: Path,
    args: argparse.Namespace,
    *,
    runtime_mode: str | None = None,
    hardware: bool = False,
) -> list[str]:
    installer = bundle_root / "scripts" / "install-offline-bundle.sh"
    if not installer.is_file():
        raise VersionManagerFailure("offline bundle installer is missing")
    command = [str(installer), "--central-env", str(args.central_env.resolve())]
    if args.skip_edge:
        command.append("--skip-edge")
    else:
        command.extend(["--edge-env", str(args.edge_env.resolve())])
    if args.local_auth:
        command.append("--local-auth")
    if runtime_mode is not None:
        if runtime_mode not in {"lan", "standalone"}:
            raise VersionManagerFailure("offline installer runtime mode is invalid")
        command.extend(["--runtime-mode", runtime_mode])
    if hardware:
        if args.skip_edge:
            raise VersionManagerFailure("hardware package install cannot skip the edge runtime")
        command.append("--hardware")
    return command


def validate_source_transition(
    current: dict[str, Any], target: dict[str, Any], args: argparse.Namespace
) -> str:
    if current.get("deployment_authority") != SOURCE_DEPLOYMENT_AUTHORITY:
        raise VersionManagerFailure("current deployment is not trusted controlled source lineage")
    if current.get("runtime_state_known") is not True or current.get("health") != "ready":
        raise VersionManagerFailure("current source runtime is not verified ready")
    if current.get("bundle_root") not in {None, ""}:
        raise VersionManagerFailure("current source lineage unexpectedly references a package root")
    if target.get("source_commit") != current.get("source_commit"):
        raise VersionManagerFailure("staged package source commit does not match current source deployment")
    if target.get("platform") != current.get("platform"):
        raise VersionManagerFailure("staged package platform does not match current source deployment")
    management = target.get("version_management")
    schema = management.get("database_schema") if isinstance(management, dict) else None
    if not isinstance(schema, dict):
        raise VersionManagerFailure("staged package database compatibility metadata is missing")
    current_schema = str(current.get("schema_head", ""))
    if not current_schema or schema.get("head") != current_schema:
        raise VersionManagerFailure("source-to-package transition requires the exact current schema head")
    compatible = schema.get("runtime_compatible_schema_heads")
    if not isinstance(compatible, list) or current_schema not in compatible:
        raise VersionManagerFailure("staged package does not explicitly support the current schema")

    env = parse_env_file(args.central_env.resolve())
    runtime_mode = current.get("runtime_mode")
    bind = env.get("CENTRAL_BIND_ADDRESS", "127.0.0.1")
    if runtime_mode == "standalone" and bind not in {"127.0.0.1", "localhost"}:
        raise VersionManagerFailure("standalone source lineage does not match loopback runtime bind")
    if runtime_mode == "lan" and bind in {"127.0.0.1", "localhost"}:
        raise VersionManagerFailure("LAN source lineage does not match trusted-LAN runtime bind")
    if runtime_mode not in {"lan", "standalone"}:
        raise VersionManagerFailure("current source runtime mode is invalid")

    dashboard = target.get("dashboard")
    local_auth = target.get("local_auth")
    provider = dashboard.get("auth_provider") if isinstance(dashboard, dict) else None
    origin = dashboard.get("origin") if isinstance(dashboard, dict) else None
    selected = local_auth.get("selected") if isinstance(local_auth, dict) else None
    source_provider = current.get("source_dashboard_auth_provider")
    source_overlay = current.get("source_local_auth_overlay")
    source_auth_mode = current.get("source_auth_mode")
    source_origin = current.get("source_dashboard_origin")
    if source_provider != "local" or source_overlay is not True or not isinstance(source_auth_mode, str) or source_auth_mode == "disabled":
        raise VersionManagerFailure("controlled source authentication evidence is not verified local auth")
    if not args.local_auth:
        raise VersionManagerFailure("source-to-package transition requires the local-auth overlay")
    if provider != "local" or selected is not True or env.get("AUTH_MODE", "disabled") == "disabled":
        raise VersionManagerFailure("local-auth package/runtime boundary is not verified")
    if origin != source_origin:
        raise VersionManagerFailure("staged package dashboard origin does not match source deployment evidence")
    return current_schema


def verify_transition_runtime(
    target_root: Path,
    target: dict[str, Any],
    current: dict[str, Any],
    args: argparse.Namespace,
    *,
    source_hardware: dict[str, Any] | None = None,
    compose_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    validate_source_transition(current, target, args)
    dashboard = target.get("dashboard")
    api_base = dashboard.get("api_base_url") if isinstance(dashboard, dict) else None
    dashboard_origin = dashboard.get("origin") if isinstance(dashboard, dict) else None
    if not isinstance(api_base, str) or not api_base:
        raise VersionManagerFailure("staged package API base URL is missing")
    if not isinstance(dashboard_origin, str) or not dashboard_origin:
        raise VersionManagerFailure("staged package dashboard origin is missing")
    readiness = read_local_json(f"{api_base.rstrip('/')}/health/ready")
    if (
        readiness.get("status") != "ready"
        or readiness.get("database") != "ready"
        or readiness.get("mqtt") != "ready"
    ):
        raise VersionManagerFailure("Telemetry API/database/MQTT readiness is not fully ready")
    wait_http_success(dashboard_origin)

    central = compose_args(
        target_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
    )
    revision = subprocess.run(
        central + ["exec", "-T", "telemetry-service", "alembic", "current"],
        check=True,
        capture_output=True,
        text=True,
        env=compose_env,
    ).stdout.strip()
    expected_schema = str(target["version_management"]["database_schema"]["head"])
    require_exact_alembic_head(revision, expected_schema)

    device: dict[str, Any]
    hardware: dict[str, Any]
    if args.skip_edge:
        device = {"status": "not_applicable", "reason": "edge_skipped"}
        hardware = {"status": "not_applicable", "reason": "edge_skipped"}
    else:
        hardware = verify_real_hardware_runtime(args)
        if source_hardware is None:
            raise VersionManagerFailure("source real-hardware baseline is missing")
        if hardware.get("device_mode") != source_hardware.get("device_mode"):
            raise VersionManagerFailure("Device Agent hardware mode changed during package transition")
        if hardware.get("observed_buses") != source_hardware.get("observed_buses"):
            raise VersionManagerFailure("Device Agent RS-485 topology changed during package transition")
        observation_seconds = int(
            os.environ.get(
                "NEXOLAB_POST_UPDATE_OBSERVATION_SECONDS",
                str(DEFAULT_POST_UPDATE_OBSERVATION_SECONDS),
            )
        )
        device = verify_device_agent_progress(observation_seconds=observation_seconds)
    return {
        "readiness": readiness,
        "schema_head": expected_schema,
        "device_agent": device,
        "hardware": hardware,
        "dashboard": {"status": "ready", "origin": dashboard_origin},
    }

def source_transition_id(bundle_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{stamp}:{bundle_id}:{os.getpid()}".encode()).hexdigest()[:12]
    return f"source-to-packaged-{stamp}-{digest}"


def establish_package_authority(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    lock_path = root / "worker.lock"
    update_lock_path = root / "update-plane.lock"
    with (
        lock_path.open("a+", encoding="utf-8") as lock,
        update_lock_path.open("a+", encoding="utf-8") as update_lock,
    ):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise VersionManagerFailure("another version-manager worker is active") from error
        try:
            fcntl.flock(update_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise VersionManagerFailure("the version update plane is active") from error

        assert_no_active_version_operation(root)
        current_path = root / "current.json"
        recorded_current = load_json(current_path)
        current = source_deployment_identity(recorded_current, args)
        target_root = root / "catalog" / args.bundle_id
        target = verify_staged_bundle(target_root, args.bundle_id)
        target_tooling = validate_package_tooling(target_root, target)
        activate_offline_image_environment(target)
        current_schema = validate_source_transition(current, target, args)
        compose_env = local_auth_subprocess_env(args)
        source_hardware = verify_real_hardware_runtime(args)
        dashboard_state = source_dashboard_state(current)
        transition_id = source_transition_id(args.bundle_id)
        evidence_dir = root / "operation-evidence" / transition_id
        evidence_dir.mkdir(parents=True, exist_ok=False, mode=0o750)
        transition_path = evidence_dir / "transition.json"
        atomic_json(evidence_dir / "source-lineage-before.json", recorded_current)
        mutation_started = False
        dashboard_handoff_started = False
        transition: dict[str, Any] = {
            "schema_version": 1,
            "type": "source_to_packaged_authority",
            "id": transition_id,
            "status": "running",
            "started_at": now(),
            "ended_at": None,
            "source_commit": current.get("source_commit"),
            "source_deployment_evidence": current.get("source_deployment_evidence"),
            "source_hardware_before": source_hardware,
            "source_dashboard_before": dashboard_state,
            "target_bundle_id": args.bundle_id,
            "target_release": target.get("bundle_version"),
            "target_manifest_sha256": manifest_digest(target_root),
            "target_tooling": target_tooling,
            "backup_evidence_id": None,
            "capacity_evidence_id": None,
            "runtime_verification": None,
        }
        atomic_json(transition_path, transition)

        try:
            transition["volume_identities_before"] = capture_volume_identities(
                skip_edge=args.skip_edge
            )
            atomic_json(
                evidence_dir / "volume-identities-before.json",
                {"volumes": transition["volume_identities_before"]},
            )
            transition["capacity_evidence_id"] = run_capacity_preflight(root, transition_id)
            atomic_json(transition_path, transition)

            central = compose_args(
                target_root,
                args.central_env.resolve(),
                central=True,
                local_auth=args.local_auth,
            )
            backup_id = f"{transition_id}-postgresql.dump"
            create_postgresql_backup(
                central, args.backup_dir.resolve(), backup_id, compose_env=compose_env
            )
            transition["backup_evidence_id"] = backup_id
            atomic_json(transition_path, transition)

            mutation_started = True
            dashboard_handoff_started = True
            stop_source_dashboard()
            transition["dashboard_handoff"] = {"status": "source_stopped"}
            atomic_json(transition_path, transition)
            subprocess.run(
                offline_installer_command(
                    target_root,
                    args,
                    runtime_mode=str(current["runtime_mode"]),
                    hardware=not args.skip_edge,
                ),
                check=True,
                env=compose_env,
            )
            verified_target = verify_staged_bundle(target_root, args.bundle_id)
            if manifest_digest(target_root) != transition["target_manifest_sha256"]:
                raise VersionManagerFailure("staged package manifest changed during installation")
            transition["runtime_verification"] = verify_transition_runtime(
                target_root,
                verified_target,
                current,
                args,
                source_hardware=source_hardware,
                compose_env=compose_env,
            )
            after = capture_volume_identities(skip_edge=args.skip_edge)
            atomic_json(evidence_dir / "volume-identities-after.json", {"volumes": after})
            if after != transition["volume_identities_before"]:
                raise VersionManagerFailure("persistent volume identities changed during package installation")

            transition["volume_identities_after"] = after
            transition["status"] = "verified_for_authority_commit"
            atomic_json(transition_path, transition)
            commit_source_dashboard_handoff()
            transition["dashboard_handoff"] = {
                "status": "packaged_active_source_disabled",
                "service": SOURCE_DASHBOARD_SERVICE,
            }
            atomic_json(transition_path, transition)
            atomic_json(
                current_path,
                {
                    "schema_version": 1,
                    "bundle_id": args.bundle_id,
                    "bundle_root": str(target_root),
                    "release": verified_target["bundle_version"],
                    "source_commit": verified_target["source_commit"],
                    "build_timestamp": verified_target["created_at"],
                    "runtime_mode": current["runtime_mode"],
                    "platform": verified_target["platform"],
                    "schema_head": current_schema,
                    "deployed_at": now(),
                    "health": "ready",
                    "runtime_state_known": True,
                    "previous_bundle_id": None,
                    "previous_release": None,
                    "last_operation_id": None,
                    "deployment_authority": PACKAGED_DEPLOYMENT_AUTHORITY,
                    "edge_hardware_required": True,
                    "hardware_contract": source_hardware,
                    "transition_evidence_id": transition_id,
                    "previous_source_commit": current.get("source_commit"),
                    "previous_source_deployment_evidence": current.get(
                        "source_deployment_evidence"
                    ),
                },
            )
            transition["status"] = "succeeded"
            transition["result_code"] = "packaged_authority_established"
            transition["ended_at"] = now()
            atomic_json(transition_path, transition)
        except Exception as error:
            source_restored = False
            if dashboard_handoff_started:
                try:
                    transition["source_restore"] = restore_source_runtime(
                        target_root, target, current, args, dashboard_state,
                        compose_env=compose_env,
                    )
                    source_restored = transition["source_restore"].get("status") == "restored"
                except Exception as restore_error:
                    transition["source_restore"] = {
                        "status": "failed",
                        "failure_type": type(restore_error).__name__,
                        "safe_message": str(restore_error)[:300],
                    }
            if mutation_started:
                recovered = dict(recorded_current)
                recovered["health"] = "ready" if source_restored else "verification_failed"
                recovered["runtime_state_known"] = source_restored
                recovered["last_operation_id"] = transition_id
                atomic_json(current_path, recovered)
            transition["status"] = "failed"
            transition["ended_at"] = now()
            transition["failure_type"] = type(error).__name__
            transition["safe_message"] = str(error)[:500]
            atomic_json(transition_path, transition)
            raise

    print(
        json.dumps(
            {
                "status": "packaged_authority_established",
                "bundle_id": args.bundle_id,
                "transition_evidence_id": transition_id,
            },
            sort_keys=True,
        )
    )

def run_once(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    lock_path = root / "worker.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise VersionManagerFailure("another version-manager worker is active") from error
        requests = sorted((root / "requests").glob("*.json"))
        if not requests:
            print(json.dumps({"status": "idle"}))
            return
        execute_request(args, requests[0])


def execute_request(args: argparse.Namespace, request_path: Path) -> None:
    root = args.root.resolve()
    operation = load_json(request_path)
    operation_id = str(operation.get("id", ""))
    if request_path.name != f"{operation_id}.json":
        raise VersionManagerFailure("request filename and operation identity differ")
    operation_path = root / "operations" / request_path.name
    current = load_json(root / "current.json")
    if operation.get("status") != "queued" or operation.get("source_bundle_id") != current.get("bundle_id"):
        raise VersionManagerFailure("request is stale or not queued")
    target_id = str(operation.get("target_bundle_id", ""))
    target_root = root / "catalog" / target_id

    operation["status"] = "running"
    operation.setdefault("completed_phases", [])
    atomic_json(operation_path, operation)
    mutation_started = False
    try:
        enter_phase(operation_path, operation, "verifying_package")
        target = verify_staged_bundle(target_root, target_id)
        operation["target_tooling"] = validate_package_tooling(target_root, target)
        schema = target["version_management"]["database_schema"]
        current_schema = str(current["schema_head"])
        compatibility_field = (
            "upgrade_from" if operation["action"] == "update" else "runtime_compatible_schema_heads"
        )
        if current_schema not in schema[compatibility_field]:
            raise VersionManagerFailure("schema compatibility is not explicitly declared")

        current_root = Path(str(current["bundle_root"])).resolve()
        current_manifest = verify_staged_bundle(current_root, str(current["bundle_id"]))
        if (
            current_manifest.get("bundle_version") != current.get("release")
            or current_manifest.get("source_commit") != current.get("source_commit")
        ):
            raise VersionManagerFailure("current deployment evidence does not match its staged package")
        activate_offline_image_environment(current_manifest)
        compose_env = local_auth_subprocess_env(args)

        hardware_required = current.get("edge_hardware_required") is True
        hardware_contract = current.get("hardware_contract")
        if hardware_required:
            if args.skip_edge:
                raise VersionManagerFailure(
                    "packaged hardware authority cannot skip the edge runtime"
                )
            if not isinstance(hardware_contract, dict):
                raise VersionManagerFailure(
                    "packaged hardware authority is missing its verified hardware contract"
                )

        enter_phase(operation_path, operation, "checking_capacity")
        operation["capacity_evidence_id"] = run_capacity_preflight(root, operation_id)
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "creating_backup")
        backup_id = f"{operation_id}-postgresql.dump"
        central = compose_args(
            current_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
        )
        create_postgresql_backup(
            central, args.backup_dir.resolve(), backup_id, compose_env=compose_env
        )
        operation["backup_evidence_id"] = backup_id
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "applying_update")
        mutation_started = True
        subprocess.run(
            offline_installer_command(
                target_root,
                args,
                runtime_mode=str(current["runtime_mode"]),
                hardware=hardware_required,
            ),
            check=True,
            env=compose_env,
        )
        operation["offline_bundle_smoke_verified"] = True
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "verifying_runtime")
        activate_offline_image_environment(target)
        target_central = compose_args(
            target_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
        )
        revision = subprocess.run(
            target_central + ["exec", "-T", "telemetry-service", "alembic", "current"],
            check=True,
            capture_output=True,
            text=True,
            env=compose_env,
        ).stdout.strip()
        expected_schema = deployed_schema_after(
            str(operation["action"]),
            current_schema,
            str(schema["head"]),
        )
        require_exact_alembic_head(revision, str(expected_schema))

        if args.skip_edge:
            operation["device_agent_verification"] = {
                "status": "not_applicable",
                "reason": "edge_skipped",
            }
            operation["hardware_verification"] = {
                "status": "not_applicable",
                "reason": "edge_skipped",
            }
        else:
            if hardware_required:
                observed_hardware = verify_real_hardware_runtime(args)
                assert isinstance(hardware_contract, dict)
                for key, label in (
                    ("device_mode", "hardware mode"),
                    ("configured_mode", "configured hardware mode"),
                    ("host_serial_device", "stable RS-485 identity"),
                    ("observed_buses", "RS-485 topology"),
                ):
                    if observed_hardware.get(key) != hardware_contract.get(key):
                        raise VersionManagerFailure(
                            f"Device Agent {label} changed during version operation"
                        )
                operation["hardware_verification"] = observed_hardware
            else:
                operation["hardware_verification"] = {
                    "status": "not_required",
                    "reason": "current_release_has_no_hardware_authority",
                }
            observation_seconds = int(
                os.environ.get(
                    "NEXOLAB_POST_UPDATE_OBSERVATION_SECONDS",
                    str(DEFAULT_POST_UPDATE_OBSERVATION_SECONDS),
                )
            )
            operation["device_agent_verification"] = verify_device_agent_progress(
                observation_seconds=observation_seconds
            )
        atomic_json(operation_path, operation)

        deployed_current = {
            "schema_version": 1,
            "bundle_id": target_id,
            "bundle_root": str(target_root),
            "release": target["bundle_version"],
            "source_commit": target["source_commit"],
            "build_timestamp": target["created_at"],
            "runtime_mode": current["runtime_mode"],
            "platform": target["platform"],
            "schema_head": expected_schema,
            "deployed_at": now(),
            "health": "ready",
            "runtime_state_known": True,
            "previous_bundle_id": current["bundle_id"],
            "previous_release": current["release"],
            "last_operation_id": operation_id,
        }
        for authority_key in (
            "deployment_authority",
            "edge_hardware_required",
            "hardware_contract",
            "transition_evidence_id",
            "previous_source_commit",
            "previous_source_deployment_evidence",
        ):
            if authority_key in current:
                deployed_current[authority_key] = current[authority_key]
        atomic_json(root / "current.json", deployed_current)
        operation["status"] = "succeeded"
        operation["result_code"] = "verified_ready"
        enter_phase(operation_path, operation, "done")
    except Exception as error:
        operation["status"] = "failed"
        operation["result_code"] = type(error).__name__
        operation["safe_message"] = str(error)[:500]
        fail_current_phase(operation)
        if mutation_started:
            current["health"] = "verification_failed"
            current["runtime_state_known"] = False
            current["last_operation_id"] = operation_id
            atomic_json(root / "current.json", current)
        raise
    finally:
        operation["ended_at"] = now()
        atomic_json(operation_path, operation)
        request_path.unlink(missing_ok=True)
    print(json.dumps({"status": operation["status"], "operation_id": operation_id}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subcommands = result.add_subparsers(dest="command", required=True)

    stage_parser = subcommands.add_parser("stage")
    stage_parser.add_argument("--root", type=Path, required=True)
    stage_parser.add_argument("--bundle", type=Path, required=True)
    stage_parser.set_defaults(handler=stage)

    bootstrap_parser = subcommands.add_parser("bootstrap")
    bootstrap_parser.add_argument("--root", type=Path, required=True)
    bootstrap_parser.add_argument("--bundle-id", required=True)
    bootstrap_parser.add_argument("--runtime-mode", choices=("lan", "standalone"), required=True)
    bootstrap_parser.add_argument("--schema-head")
    bootstrap_parser.add_argument("--deployed-at")
    bootstrap_parser.add_argument("--health", choices=("ready", "degraded"), default="ready")
    bootstrap_parser.set_defaults(handler=bootstrap)

    transition = subcommands.add_parser("establish-package-authority")
    transition.add_argument("--root", type=Path, required=True)
    transition.add_argument("--bundle-id", required=True)
    transition.add_argument("--central-env", type=Path, required=True)
    transition.add_argument("--edge-env", type=Path)
    transition.add_argument("--backup-dir", type=Path, required=True)
    transition.add_argument(
        "--source-repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository containing immutable source deployment evidence",
    )
    transition.add_argument("--skip-edge", action="store_true")
    transition.add_argument("--local-auth", action="store_true")
    transition.set_defaults(handler=establish_package_authority)

    worker = subcommands.add_parser("run-once")
    worker.add_argument("--root", type=Path, required=True)
    worker.add_argument("--central-env", type=Path, required=True)
    worker.add_argument("--edge-env", type=Path)
    worker.add_argument("--backup-dir", type=Path, required=True)
    worker.add_argument("--skip-edge", action="store_true")
    worker.add_argument("--local-auth", action="store_true")
    worker.set_defaults(handler=run_once)
    return result


def main() -> int:
    args = parser().parse_args()
    if (
        args.command in {"run-once", "establish-package-authority"}
        and not args.skip_edge
        and args.edge_env is None
    ):
        raise VersionManagerFailure("--edge-env is required unless --skip-edge is used")
    args.handler(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        VersionManagerFailure,
    ) as error:
        print(f"NEXOLAB version manager stopped safely: {error}", file=sys.stderr)
        raise SystemExit(1) from error
