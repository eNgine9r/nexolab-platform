#!/usr/bin/env python3
"""Bounded forward reconciliation of NEXOLAB #1381's proven partial update.

Not a generic repair. The failed original operation is kept as failed.
Never reinstall Docker images, alter database contents, or write hardware.
Site mutation requires explicit --execute and exact approval phrase.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
FAILED = "51dc3ae6-8e34-453c-b6ff-7ecac98b924c"
OLD = "29cff166e5abfe4d5ef8f871a2a49a3114be40fa"
NEW = "ffdefc4550d71e211724de1154ffe9057f905c9c"
OLD_BUNDLE = "recovery-29cff166e5ab-tooling-29cff166e5ab-protected-storage-992e9d9bc05f-29cff166e5ab"
NEW_BUNDLE = "recovery-ffdefc4550d7-tooling-ffdefc4550d7-protected-storage-992e9d9bc05f-ffdefc4550d7"
MANIFEST_SHA = "ed5aa07fdd55184b2f66add36bb8563bdf2931e679eb73e5553aa2d3cbdae29d"
BACKUP_SHA = "328b2a01617100472313c86a3004b3b940d086e2cd082701c594e49c9b5cf299"
SCHEMA = "20260908_0037"
ROOT = Path("/var/lib/nexolab/version-management")
BACKUP_DIR = Path("/var/backups/nexolab")
AUDIT = Path("/home/nexolab/commander-workspaces/nexolab-platform/release-1381-runtime-identity/owner-recovery-readiness-report-1384.json")
WORKER = Path("/usr/local/lib/nexolab/nexolab-version-manager.py")
WORKER_SHA256 = "7b6286738b2c437994f0baefa540313b980384a677082d20b639fa32e0d1d4c0"
AUDIT_SHA256 = "e7ae52dcfe0216475a6efbf35571948bc33ae5fd83e95ab8214fe6f1f7632686"
RECOVERY_ID = "reconcile-" + FAILED + "-to-" + NEW[:12]
CONTAINERS = {
    "dashboard": "nexolab-central-dashboard-1",
    "telemetry-service": "nexolab-central-telemetry-service-1",
    "device-agent": "nexolab-edge-device-agent-1",
    "mqtt": "nexolab-central-mqtt-1",
    "postgres": "nexolab-central-postgres-1",
    "object-storage": "nexolab-central-minio-1",
}
class RecoveryBlocked(RuntimeError):
    pass

def guard(ok: bool, reason: str) -> None:
    if not ok:
        raise RecoveryBlocked(reason)

def read_object(path: Path) -> dict:
    guard(path.is_file() and not path.is_symlink(), "SOURCE_EVIDENCE_UNSAFE")
    obj = json.loads(path.read_text(encoding="utf-8"))
    guard(isinstance(obj, dict), "SOURCE_EVIDENCE_INVALID")
    return obj

def sha256(path: Path) -> str:
    dig = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            dig.update(block)
    return dig.hexdigest()

def read_command(argv: list[str], *, timeout: int = 45) -> str:
    result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)
    guard(result.returncode == 0, "READ_ONLY_CHECK_FAILED")
    return result.stdout.strip()

def native_worker():
    guard(WORKER.is_file() and not WORKER.is_symlink(), "INSTALLED_WORKER_MISSING")
    info = WORKER.stat()
    guard(info.st_uid == 0 and not (info.st_mode & 0o022), "INSTALLED_WORKER_NOT_TRUSTED")
    guard(sha256(WORKER) == WORKER_SHA256, "INSTALLED_WORKER_SHA256_MISMATCH")
    spec = importlib.util.spec_from_file_location("nexolab_recovery_native", WORKER)
    guard(spec is not None and spec.loader is not None, "INSTALLED_WORKER_LOAD_INVALID")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def validate_old_authority(current: dict, op: dict, target: dict) -> None:
    guard(current.get("source_commit") == OLD
          and current.get("bundle_id") == OLD_BUNDLE
          and current.get("deployment_authority") == "validated_package"
          and current.get("health") == "verification_failed"
          and current.get("runtime_state_known") is False
          and current.get("last_operation_id") == FAILED, "CURRENT_IS_NOT_EXPECTED_FAILED_AUTHORITY")
    guard(op.get("id") == FAILED and op.get("status") == "failed"
          and op.get("action") == "update" and op.get("phase") == "verifying_runtime"
          and op.get("target_commit") == NEW
          and op.get("result_code") == "VersionManagerFailure"
          and op.get("safe_message") == "Device Agent RS-485 topology changed during version operation"
          and op.get("backup_evidence_id") == FAILED + "-postgresql.dump"
          and {"creating_backup", "applying_update"}.issubset(set(op.get("completed_phases", []))),
          "FAILED_OPERATION_NOT_EXACT")
    guard(target.get("source_commit") == NEW
          and target.get("platform") == "linux/arm64"
          and target.get("version_management", {}).get("bundle_id") == NEW_BUNDLE
          and target.get("version_management", {}).get("database_schema", {}).get("head") == SCHEMA
          and current.get("schema_head") == SCHEMA
          and current.get("edge_hardware_required") is True
          and current.get("hardware_contract", {}).get("status") == "verified"
          and target.get("dashboard", {}).get("auth_provider") == "local"
          and target.get("external_frontend", {}).get("source_commit") == NEW
          and target.get("external_frontend", {}).get("origin")
              == "https://nexolab-edge-01.tail7f9b04.ts.net",
          "TARGET_OR_HARDWARE_AUTHORITY_MISMATCH")

def confirm_backup() -> dict:
    guard(sha256(AUDIT) == AUDIT_SHA256, "OWNER_AUDIT_REPORT_SHA256_CHANGED")
    audit = read_object(AUDIT)
    guard(audit.get("kind") == "nexolab_1384_read_only_recovery_preflight"
          and audit.get("status") == "READ_ONLY_EVIDENCE_CAPTURED"
          and audit.get("all_read_only_gates_pass") is True
          and audit.get("backup_sha256") == BACKUP_SHA
          and audit.get("archive_list_entries", 0) >= 611,
          "OWNER_BACKUP_AUDIT_NOT_VERIFIED")
    path = BACKUP_DIR / (FAILED + "-postgresql.dump")
    info = path.lstat()
    guard(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
          and stat.S_IMODE(info.st_mode) == 0o600
          and info.st_size == 992743918, "PROTECTED_BACKUP_CHANGED")
    guard(sha256(path) == BACKUP_SHA, "PROTECTED_BACKUP_CHECKSUM_CHANGED")
    return {"sha256": BACKUP_SHA, "bytes": info.st_size,
            "archive_entries": audit["archive_list_entries"]}

def compare_images(manifest: dict) -> None:
    expected = {x["id"]: set(x["identity"]["runtime_digests"])
                for x in manifest["images"]}
    guard(set(expected) == set(CONTAINERS), "SIX_IMAGE_CONTRACT_MISSING")
    for ident, name in CONTAINERS.items():
        actual = read_command(["docker", "inspect", "--format", "{{.Image}}", name])
        guard(actual in expected[ident], "IMAGE_IDENTITY_CHANGED_" + ident)

def verify_runtime_container_health() -> None:
    # Five services have Docker HEALTHCHECK; the "minio" Compose compatibility
    # name runs VersityGW, which exposes a GET /health endpoint instead.
    for ident, name in CONTAINERS.items():
        if ident == "object-storage":
            guard(
                read_command(["docker", "inspect", "--format", "{{.State.Running}}", name])
                == "true",
                "OBJECT_STORAGE_NOT_RUNNING",
            )
            # Probe only local Docker DNS; never pass credentials or print HTTP
            # response bodies. HTTP errors and timeouts fail closed.
            probe = (
                "from urllib.request import urlopen\n"
                "with urlopen('http://minio:9000/health', timeout=5) as response:\n"
                "    if response.status != 200: raise SystemExit(1)\n"
                "print('READY')\n"
            )
            guard(
                read_command([
                    "docker", "exec", CONTAINERS["telemetry-service"],
                    "python3", "-c", probe,
                ], timeout=12) == "READY",
                "OBJECT_STORAGE_NOT_READY",
            )
        else:
            health = read_command(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", name]
            )
            guard(health == "healthy", "CONTAINER_NOT_HEALTHY_" + ident)


def verify_runtime(native, args, current: dict, target: dict) -> tuple[list, dict]:
    compare_images(target)
    revision = read_command(["docker", "exec", CONTAINERS["telemetry-service"],
                             "alembic", "current"])
    native.require_exact_alembic_head(revision, SCHEMA)
    baseline = current["hardware_contract"]
    observed = native.verify_real_hardware_runtime(args)
    for key in ("device_mode", "configured_mode", "host_serial_device",
                "observed_buses", "bus_bindings"):
        guard(observed.get(key) == baseline.get(key), "HARDWARE_CHANGED_" + key)
    verify_runtime_container_health()
    return native.capture_volume_identities(skip_edge=False), observed

def inspect_exact_site(args, native):
    guard(args.root == ROOT and args.backup_dir == BACKUP_DIR,
          "NONCANONICAL_PROTECTED_PATH")
    guard(args.central_env == Path("/home/nexolab/nexolab-platform/infrastructure/compose/.env.central")
          and args.edge_env == Path("/home/nexolab/nexolab-platform/infrastructure/compose/.env.edge-central"),
          "SITE_ENV_PATH_NOT_EXACT")
    for required in (args.central_env, args.edge_env):
        guard(required.is_file() and not required.is_symlink(), "SITE_ENV_NOT_PRESENT")
    current = read_object(args.root / "current.json")
    target_root = args.root / "catalog" / NEW_BUNDLE
    guard(sha256(target_root / "manifest.json") == MANIFEST_SHA,
          "STAGED_MANIFEST_CHANGED")
    target = native.verify_staged_bundle(target_root, NEW_BUNDLE)
    op = read_object(args.root / "operations" / (FAILED + ".json"))
    validate_old_authority(current, op, target)
    native.validate_package_tooling(target_root, target)
    guard((args.root / "catalog" / OLD_BUNDLE / ".nexolab-validated.json").is_file(),
          "PREVIOUS_PACKAGE_NOT_RETAINED")
    for section in ("requests", "operations"):
        for record in (args.root / section).glob("*.json"):
            state = read_object(record)
            guard(state.get("status") not in ("queued", "running", "pending",
                                              "installing", "rolling_back")
                  and state.get("state") not in ("queued", "running", "pending",
                                                "installing", "rolling_back"),
                  "VERSION_OPERATION_ACTIVE")
    backup = confirm_backup()
    volume_ids, hardware = verify_runtime(native, args, current, target)
    return current, target, target_root, backup, volume_ids, hardware

def recovery_snapshot(args, native) -> dict:
    current, target, target_root, backup, volumes, hardware = inspect_exact_site(args, native)
    frontend = native.protected_frontend_transaction(
        target_root, target, current, args.root / "operation-evidence" / RECOVERY_ID
    )
    guard(frontend.enabled and frontend.was_active,
          "OLD_PROTECTED_FRONTEND_NOT_AUTHENTICATED")
    guard(frontend.original_identity.get("source_commit") == OLD,
          "OLD_PROTECTED_FRONTEND_IDENTITY_MISMATCH")
    return {
        "status": "READ_ONLY_RECOVERY_CANDIDATE_VERIFIED",
        "failed_operation_preserved": True,
        "target_source": NEW,
        "target_bundle": NEW_BUNDLE,
        "manifest_sha256": MANIFEST_SHA,
        "backup": backup,
        "volume_count": len(volumes),
        "hardware_status": hardware.get("status"),
        "protected_frontend_source": OLD,
        "production_mutation": False,
    }

def reconcile(args, native) -> dict:
    guard(os.geteuid() == 0, "ROOT_OWNER_CONTEXT_REQUIRED")
    guard(args.execute and args.approve == "RECONCILE-FAILED-" + FAILED,
          "OWNER_EXPLICIT_APPROVAL_REQUIRED")
    lock_path = args.root / "worker.lock"
    update_path = args.root / "update-plane.lock"
    with lock_path.open("a+", encoding="utf-8") as worker_lock, update_path.open("a+", encoding="utf-8") as update_lock:
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(update_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        native.assert_no_active_version_operation(args.root)
        current, target, target_root, backup, before, hardware = inspect_exact_site(args, native)
        evidence = args.root / "operation-evidence" / RECOVERY_ID
        guard(not evidence.exists(), "RECOVERY_ALREADY_ATTEMPTED")
        frontend = native.protected_frontend_transaction(target_root, target, current, evidence)
        guard(frontend.enabled and frontend.was_active
              and frontend.original_identity.get("source_commit") == OLD,
              "PROTECTED_FRONTEND_PREHANDOFF_FAILED")
        evidence.mkdir(mode=0o750)
        record = evidence / "recovery-result.json"
        result = {
            "kind": "nexolab_failed_update_forward_reconciliation",
            "id": RECOVERY_ID, "failed_operation": FAILED,
            "source_before": OLD, "target_source": NEW,
            "target_bundle": NEW_BUNDLE, "manifest_sha256": MANIFEST_SHA,
            "backup": backup, "status": "running",
            "started_at": native.now(), "ended_at": None,
            "original_failed_operation_preserved": True,
        }
        native.atomic_json(record, result)
        published = False
        try:
            # Native implementation guards current HTTPS identity, probes a
            # privately staged candidate, and can roll it back on failure.
            frontend.prepare()
            frontend.activate()
            after, observed = verify_runtime(native, args, current, target)
            guard(before == after, "PERSISTENT_VOLUME_IDENTITIES_CHANGED")
            native.verify_device_agent_progress(observation_seconds=60)
            guard(frontend.metadata.get("source_commit") == NEW,
                  "PROTECTED_HTTPS_SOURCE_NOT_NEW")
            guard(read_object(args.root / "current.json") == current,
                  "NATIVE_CURRENT_CHANGED_DURING_RECOVERY")
            deployed = {
                "schema_version": 1,
                "bundle_id": NEW_BUNDLE,
                "bundle_root": str(target_root),
                "release": target["bundle_version"],
                "source_commit": NEW,
                "build_timestamp": target["created_at"],
                "runtime_mode": current["runtime_mode"],
                "platform": target["platform"],
                "schema_head": SCHEMA,
                "deployed_at": native.now(),
                "health": "ready",
                "runtime_state_known": True,
                "protected_frontend_enabled": True,
                "external_frontend": frontend.metadata,
                "previous_bundle_id": OLD_BUNDLE,
                "previous_release": current["release"],
                "last_operation_id": RECOVERY_ID,
                "deployment_authority": "validated_package",
                "edge_hardware_required": True,
                "hardware_contract": observed,
                "recovered_from_failed_operation": FAILED,
            }
            for field in ("transition_evidence_id", "previous_source_commit",
                          "previous_source_deployment_evidence"):
                if field in current:
                    deployed[field] = current[field]
            result["status"] = "verified_commit_ready"
            result["hardware_read_only_verified"] = True
            result["persistent_volumes_unchanged"] = True
            result["protected_frontend_verified"] = frontend.metadata
            result["verified_at"] = native.now()
            native.atomic_json(record, result)
            # Sole authority commit. Never mark the original operation succeeded.
            native.atomic_json(args.root / "current.json", deployed)
            published = True
        except BaseException as error:
            if not published:
                # A failed fsync/chmod may occur *after* os.replace(current).
                # Never roll HTTPS back if authority may already name target.
                try:
                    recorded = read_object(args.root / "current.json")
                    published = recorded.get("last_operation_id") == RECOVERY_ID
                except Exception:
                    published = False
                if published:
                    result["status"] = "commit_uncertain_operator_review_required"
                    result["failure_type"] = type(error).__name__
                    result["ended_at"] = native.now()
                    try:
                        native.atomic_json(record, result)
                    except Exception:
                        pass
                else:
                    try:
                        frontend.rollback()
                    except Exception:
                        result["protected_frontend_rollback_failed"] = True
                    result["status"] = "failed"
                    result["failure_type"] = type(error).__name__
                    result["ended_at"] = native.now()
                    native.atomic_json(record, result)
            raise
        result["status"] = "succeeded"
        result["ended_at"] = native.now()
        try:
            native.atomic_json(record, result)
        except OSError:
            print("RECOVERY_COMMITTED_JOURNAL_FINALIZATION_PENDING", file=sys.stderr)
        return {
            "status": "succeeded", "operation_id": RECOVERY_ID,
            "source_commit": NEW, "previous_source": OLD,
            "original_failed_operation_preserved": True,
        }

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="NEXOLAB #1384 exact-site recovery")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--backup-dir", type=Path, default=BACKUP_DIR)
    p.add_argument("--central-env", type=Path, required=True)
    p.add_argument("--edge-env", type=Path, required=True)
    # Native hardware verifier requires this; keep the edge check mandatory.
    p.set_defaults(skip_edge=False)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--approve", default="")
    return p

def main() -> None:
    args = parser().parse_args()
    try:
        guard(os.geteuid() == 0, "ROOT_OWNER_CONTEXT_REQUIRED")
        native = native_worker()
        if args.execute:
            result = reconcile(args, native)
        else:
            result = recovery_snapshot(args, native)
    except Exception as exc:
        # Never emit site configuration, private journal data or stack traces.
        detail = str(exc) if isinstance(exc, RecoveryBlocked) else type(exc).__name__
        print("RECOVERY_STOP", detail, file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
