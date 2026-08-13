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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
            {"schema_version": 1, "manifest_sha256": manifest_digest(temporary), "validated_at": now()},
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
    atomic_json(operation_path, operation)
    mutation_started = False
    try:
        target = verify_staged_bundle(target_root, target_id)
        schema = target["version_management"]["database_schema"]
        current_schema = str(current["schema_head"])
        compatibility_field = (
            "upgrade_from" if operation["action"] == "update" else "runtime_compatible_schema_heads"
        )
        if current_schema not in schema[compatibility_field]:
            raise VersionManagerFailure("schema compatibility is not explicitly declared")

        backup_id = f"{operation_id}-postgresql.dump"
        backup_path = args.backup_dir.resolve() / backup_id
        partial_backup_path = backup_path.with_suffix(".dump.partial")
        backup_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        current_root = Path(str(current["bundle_root"])).resolve()
        current_manifest = verify_staged_bundle(current_root, str(current["bundle_id"]))
        if (
            current_manifest.get("bundle_version") != current.get("release")
            or current_manifest.get("source_commit") != current.get("source_commit")
        ):
            raise VersionManagerFailure("current deployment evidence does not match its staged package")
        central = compose_args(
            current_root, args.central_env.resolve(), central=True, local_auth=args.local_auth
        )
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
        operation["backup_evidence_id"] = backup_id
        atomic_json(operation_path, operation)

        installer = target_root / "scripts" / "install-offline-bundle.sh"
        command = [str(installer), "--central-env", str(args.central_env.resolve())]
        if args.skip_edge:
            command.append("--skip-edge")
        else:
            command.extend(["--edge-env", str(args.edge_env.resolve())])
        if args.local_auth:
            command.append("--local-auth")
        mutation_started = True
        subprocess.run(command, check=True)

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
    except Exception as error:
        operation["status"] = "failed"
        operation["result_code"] = type(error).__name__
        operation["safe_message"] = str(error)[:500]
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
    if args.command == "run-once" and not args.skip_edge and args.edge_env is None:
        raise VersionManagerFailure("--edge-env is required unless --skip-edge is used")
    args.handler(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError, VersionManagerFailure) as error:
        print(f"NEXOLAB version manager stopped safely: {error}", file=sys.stderr)
        raise SystemExit(1) from error
