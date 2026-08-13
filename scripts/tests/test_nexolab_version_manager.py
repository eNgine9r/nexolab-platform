from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-version-manager.py"
SPEC = importlib.util.spec_from_file_location("nexolab_version_manager", SCRIPT)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)

VERIFIER_SCRIPT = Path(__file__).resolve().parents[1] / "verify-offline-bundle.py"
VERIFIER_SPEC = importlib.util.spec_from_file_location("verify_offline_bundle", VERIFIER_SCRIPT)
assert VERIFIER_SPEC and VERIFIER_SPEC.loader
verifier = importlib.util.module_from_spec(VERIFIER_SPEC)
VERIFIER_SPEC.loader.exec_module(verifier)


def test_backup_failure_stops_before_install_and_preserves_current(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    request_dir = root / "requests"
    operation_dir = root / "operations"
    request_dir.mkdir(parents=True)
    operation_dir.mkdir()
    current_root = root / "catalog" / "release-1"
    target_root = root / "catalog" / "release-2"
    current_root.mkdir(parents=True)
    target_root.mkdir(parents=True)

    current = {
        "bundle_id": "release-1",
        "bundle_root": str(current_root),
        "release": "1.0.0",
        "source_commit": "1" * 40,
        "schema_head": "schema-1",
        "runtime_mode": "lan",
    }
    operation = {
        "schema_version": 1,
        "id": "operation-1",
        "action": "update",
        "source_bundle_id": "release-1",
        "source_release": "1.0.0",
        "target_bundle_id": "release-2",
        "target_release": "2.0.0",
        "target_commit": "2" * 40,
        "status": "queued",
        "started_at": "2026-08-13T10:00:00Z",
        "ended_at": None,
        "backup_evidence_id": None,
        "result_code": None,
    }
    (root / "current.json").write_text(json.dumps(current), encoding="utf-8")
    request_path = request_dir / "operation-1.json"
    request_path.write_text(json.dumps(operation), encoding="utf-8")
    central_env = tmp_path / "central.env"
    central_env.write_text("POSTGRES_PASSWORD=test\n", encoding="utf-8")
    args = argparse.Namespace(
        root=root,
        central_env=central_env,
        edge_env=None,
        backup_dir=tmp_path / "backups",
        skip_edge=True,
        local_auth=True,
    )
    target_manifest = {
        "bundle_version": "2.0.0",
        "source_commit": "2" * 40,
        "created_at": "2026-08-13T09:00:00Z",
        "platform": "linux/arm64",
        "version_management": {
            "database_schema": {
                "head": "schema-2",
                "upgrade_from": ["schema-1"],
                "runtime_compatible_schema_heads": ["schema-2"],
            }
        },
    }
    current_manifest = {"bundle_version": "1.0.0", "source_commit": "1" * 40}

    def verified_manifest(path: Path, _expected_id: str) -> dict[str, object]:
        return target_manifest if path == target_root else current_manifest

    calls: list[list[str]] = []

    def fail_backup(command: list[str], **_: object) -> None:
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    with (
        patch.object(manager, "verify_staged_bundle", side_effect=verified_manifest),
        patch.object(manager.subprocess, "run", side_effect=fail_backup),
    ):
        try:
            manager.execute_request(args, request_path)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("backup failure must stop the operation")

    assert len(calls) == 1
    assert "pg_dump" in calls[0][-1]
    assert json.loads((root / "current.json").read_text(encoding="utf-8")) == current
    failed = json.loads((operation_dir / "operation-1.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["backup_evidence_id"] is None
    assert not request_path.exists()


@pytest.mark.parametrize("install_fails", [False, True])
def test_worker_records_verified_success_or_truthful_post_mutation_failure(
    tmp_path: Path,
    install_fails: bool,
) -> None:
    root = tmp_path / "versions"
    request_dir = root / "requests"
    operation_dir = root / "operations"
    request_dir.mkdir(parents=True)
    operation_dir.mkdir()
    current_root = root / "catalog" / "release-1"
    target_root = root / "catalog" / "release-2"
    (current_root / "deploy" / "compose").mkdir(parents=True)
    (current_root / "deploy" / "offline").mkdir()
    (target_root / "scripts").mkdir(parents=True)
    installer = target_root / "scripts" / "install-offline-bundle.sh"
    installer.write_text("#!/bin/sh\n", encoding="utf-8")
    current = {
        "bundle_id": "release-1",
        "bundle_root": str(current_root),
        "release": "1.0.0",
        "source_commit": "1" * 40,
        "schema_head": "schema-1",
        "runtime_mode": "lan",
    }
    operation = {
        "schema_version": 1,
        "id": "operation-2",
        "action": "update",
        "source_bundle_id": "release-1",
        "source_release": "1.0.0",
        "target_bundle_id": "release-2",
        "target_release": "2.0.0",
        "target_commit": "2" * 40,
        "status": "queued",
        "started_at": "2026-08-13T10:00:00Z",
        "ended_at": None,
        "backup_evidence_id": None,
        "result_code": None,
    }
    (root / "current.json").write_text(json.dumps(current), encoding="utf-8")
    request_path = request_dir / "operation-2.json"
    request_path.write_text(json.dumps(operation), encoding="utf-8")
    central_env = tmp_path / "central.env"
    central_env.write_text("POSTGRES_PASSWORD=test\n", encoding="utf-8")
    args = argparse.Namespace(
        root=root,
        central_env=central_env,
        edge_env=None,
        backup_dir=tmp_path / "backups",
        skip_edge=True,
        local_auth=False,
    )
    target_manifest = {
        "bundle_version": "2.0.0",
        "source_commit": "2" * 40,
        "created_at": "2026-08-13T09:00:00Z",
        "platform": "linux/arm64",
        "version_management": {
            "database_schema": {
                "head": "schema-2",
                "upgrade_from": ["schema-1"],
                "runtime_compatible_schema_heads": ["schema-2"],
            }
        },
    }
    current_manifest = {"bundle_version": "1.0.0", "source_commit": "1" * 40}

    def verified_manifest(path: Path, _expected_id: str) -> dict[str, object]:
        return target_manifest if path == target_root else current_manifest

    calls: list[list[str]] = []

    def successful_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = kwargs.get("stdout")
        if output is not None and hasattr(output, "write"):
            output.write(b"verified-postgresql-dump")
        if command[-2:] == ["alembic", "current"]:
            return subprocess.CompletedProcess(command, 0, stdout="schema-2 (head)\n")
        if install_fails and command[0] == str(installer):
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout="")

    with (
        patch.object(manager, "verify_staged_bundle", side_effect=verified_manifest),
        patch.object(manager.subprocess, "run", side_effect=successful_run),
    ):
        if install_fails:
            with pytest.raises(subprocess.CalledProcessError):
                manager.execute_request(args, request_path)
        else:
            manager.execute_request(args, request_path)

    assert "pg_dump" in calls[0][-1]
    assert calls[1][-2:] == ["pg_restore", "--list"]
    assert calls[2][0] == str(installer)
    deployed = json.loads((root / "current.json").read_text(encoding="utf-8"))
    completed = json.loads((operation_dir / "operation-2.json").read_text(encoding="utf-8"))
    if install_fails:
        assert len(calls) == 3
        assert deployed["bundle_id"] == "release-1"
        assert deployed["runtime_state_known"] is False
        assert deployed["health"] == "verification_failed"
        assert completed["status"] == "failed"
        assert not request_path.exists()
        return

    assert calls[3][-2:] == ["alembic", "current"]
    assert deployed["bundle_id"] == "release-2"
    assert deployed["previous_bundle_id"] == "release-1"
    assert deployed["schema_head"] == "schema-2"
    assert completed["status"] == "succeeded"
    assert completed["result_code"] == "verified_ready"
    assert completed["backup_evidence_id"] == "operation-2-postgresql.dump"


def test_rollback_preserves_the_current_compatible_schema() -> None:
    assert manager.deployed_schema_after("rollback", "schema-2", "schema-1") == "schema-2"
    assert manager.deployed_schema_after("update", "schema-1", "schema-2") == "schema-2"


@pytest.mark.parametrize(
    ("field", "unsafe_value", "message"),
    [
        ("backup_required", False, "Version update does not require backup"),
        ("migration_before_readiness", False, "Migration ordering is unsafe"),
        ("preserve_named_volumes", False, "Named volumes are not preserved"),
        ("preserve_edge_sqlite", False, "Edge SQLite is not preserved"),
    ],
)
def test_offline_verifier_rejects_unsafe_version_management_contract(
    tmp_path: Path,
    field: str,
    unsafe_value: bool,
    message: str,
) -> None:
    management = {
        "bundle_id": "release-2",
        "database_schema": {
            "head": "schema-2",
            "upgrade_from": ["schema-1"],
            "runtime_compatible_schema_heads": ["schema-2"],
        },
        "backup_required": True,
        "migration_before_readiness": True,
        "preserve_named_volumes": True,
        "preserve_edge_sqlite": True,
    }
    management[field] = unsafe_value
    manifest = {
        "schema_version": 1,
        "platform": "linux/arm64",
        "runtime_network_required": False,
        "paid_runtime_service_required": False,
        "secrets_included": False,
        "version_management": management,
    }

    with pytest.raises(SystemExit, match=message):
        verifier.verify_manifest(tmp_path, manifest)
