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
    if payload.get("status") != "ok":
        raise VersionManagerFailure("Device Agent health is not ok after version activation")
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



def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


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
    central: list[str], backup_dir: Path, backup_id: str
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
        )
    if partial_backup_path.stat().st_size == 0:
        raise VersionManagerFailure("PostgreSQL backup is empty")
    with partial_backup_path.open("rb") as backup_input:
        subprocess.run(
            central + ["exec", "-T", "postgres", "pg_restore", "--list"],
            check=True,
            stdin=backup_input,
            stdout=subprocess.DEVNULL,
        )
    os.replace(partial_backup_path, backup_path)
    return backup_path


def offline_installer_command(bundle_root: Path, args: argparse.Namespace) -> list[str]:
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
    selected = local_auth.get("selected") if isinstance(local_auth, dict) else None
    if args.local_auth:
        if provider != "local" or selected is not True or env.get("AUTH_MODE", "disabled") == "disabled":
            raise VersionManagerFailure("local-auth package/runtime boundary is not verified")
    elif selected is True:
        raise VersionManagerFailure("staged package requires the local-auth overlay")
    return current_schema


def verify_transition_runtime(
    target_root: Path,
    target: dict[str, Any],
    current: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    validate_source_transition(current, target, args)
    dashboard = target.get("dashboard")
    api_base = dashboard.get("api_base_url") if isinstance(dashboard, dict) else None
    if not isinstance(api_base, str) or not api_base:
        raise VersionManagerFailure("staged package API base URL is missing")
    readiness = read_local_json(f"{api_base.rstrip('/')}/health/ready")
    if (
        readiness.get("status") != "ready"
        or readiness.get("database") != "ready"
        or readiness.get("mqtt") != "ready"
    ):
        raise VersionManagerFailure("Telemetry API/database/MQTT readiness is not fully ready")

    central = compose_args(
        target_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
    )
    revision = subprocess.run(
        central + ["exec", "-T", "telemetry-service", "alembic", "current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_schema = str(target["version_management"]["database_schema"]["head"])
    if expected_schema not in revision:
        raise VersionManagerFailure("deployed database revision does not match staged package")

    device: dict[str, Any]
    if args.skip_edge:
        device = {"status": "not_applicable", "reason": "edge_skipped"}
    else:
        observation_seconds = int(
            os.environ.get(
                "NEXOLAB_POST_UPDATE_OBSERVATION_SECONDS",
                str(DEFAULT_POST_UPDATE_OBSERVATION_SECONDS),
            )
        )
        device = verify_device_agent_progress(observation_seconds=observation_seconds)
    return {"readiness": readiness, "schema_head": expected_schema, "device_agent": device}


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
        current = load_json(current_path)
        target_root = root / "catalog" / args.bundle_id
        target = verify_staged_bundle(target_root, args.bundle_id)
        current_schema = validate_source_transition(current, target, args)
        transition_id = source_transition_id(args.bundle_id)
        evidence_dir = root / "operation-evidence" / transition_id
        evidence_dir.mkdir(parents=True, exist_ok=False, mode=0o750)
        transition_path = evidence_dir / "transition.json"
        atomic_json(evidence_dir / "source-lineage-before.json", current)
        mutation_started = False
        transition: dict[str, Any] = {
            "schema_version": 1,
            "type": "source_to_packaged_authority",
            "id": transition_id,
            "status": "running",
            "started_at": now(),
            "ended_at": None,
            "source_commit": current.get("source_commit"),
            "source_deployment_evidence": current.get("source_deployment_evidence"),
            "target_bundle_id": args.bundle_id,
            "target_release": target.get("bundle_version"),
            "target_manifest_sha256": manifest_digest(target_root),
            "backup_evidence_id": None,
            "capacity_evidence_id": None,
            "runtime_verification": None,
        }
        atomic_json(transition_path, transition)

        try:
            transition["volume_identities_before"] = capture_volume_identities(
                skip_edge=args.skip_edge
            )
            atomic_json(evidence_dir / "volume-identities-before.json", {
                "volumes": transition["volume_identities_before"]
            })
            transition["capacity_evidence_id"] = run_capacity_preflight(root, transition_id)
            atomic_json(transition_path, transition)

            central = compose_args(
                target_root,
                args.central_env.resolve(),
                central=True,
                local_auth=args.local_auth,
            )
            backup_id = f"{transition_id}-postgresql.dump"
            create_postgresql_backup(central, args.backup_dir.resolve(), backup_id)
            transition["backup_evidence_id"] = backup_id
            atomic_json(transition_path, transition)

            mutation_started = True
            subprocess.run(offline_installer_command(target_root, args), check=True)
            verified_target = verify_staged_bundle(target_root, args.bundle_id)
            if manifest_digest(target_root) != transition["target_manifest_sha256"]:
                raise VersionManagerFailure("staged package manifest changed during installation")
            transition["runtime_verification"] = verify_transition_runtime(
                target_root, verified_target, current, args
            )
            after = capture_volume_identities(skip_edge=args.skip_edge)
            atomic_json(evidence_dir / "volume-identities-after.json", {"volumes": after})
            if after != transition["volume_identities_before"]:
                raise VersionManagerFailure("persistent volume identities changed during package installation")

            transition["volume_identities_after"] = after
            transition["status"] = "verified_for_authority_commit"
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
            if mutation_started:
                uncertain = dict(current)
                uncertain["health"] = "verification_failed"
                uncertain["runtime_state_known"] = False
                uncertain["last_operation_id"] = transition_id
                atomic_json(current_path, uncertain)
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

        enter_phase(operation_path, operation, "checking_capacity")
        operation["capacity_evidence_id"] = run_capacity_preflight(root, operation_id)
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "creating_backup")
        backup_id = f"{operation_id}-postgresql.dump"
        central = compose_args(
            current_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
        )
        create_postgresql_backup(central, args.backup_dir.resolve(), backup_id)
        operation["backup_evidence_id"] = backup_id
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "applying_update")
        mutation_started = True
        subprocess.run(offline_installer_command(target_root, args), check=True)
        operation["offline_bundle_smoke_verified"] = True
        atomic_json(operation_path, operation)

        enter_phase(operation_path, operation, "verifying_runtime")
        target_central = compose_args(
            target_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
        )
        revision = subprocess.run(
            target_central + ["exec", "-T", "telemetry-service", "alembic", "current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected_schema = deployed_schema_after(
            str(operation["action"]),
            current_schema,
            str(schema["head"]),
        )
        if str(expected_schema) not in revision:
            raise VersionManagerFailure("deployed database revision does not match target manifest")

        if args.skip_edge:
            operation["device_agent_verification"] = {
                "status": "not_applicable",
                "reason": "edge_skipped",
            }
        else:
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

        atomic_json(
            root / "current.json",
            {
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
            },
        )
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
