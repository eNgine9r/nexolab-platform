from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

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


def fixture_state(tmp_path: Path, operation_id: str) -> tuple[Path, Path, Path, dict[str, object], argparse.Namespace]:
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
    (target_root / "scripts" / "install-offline-bundle.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    current: dict[str, object] = {
        "bundle_id": "release-1",
        "bundle_root": str(current_root),
        "release": "1.0.0",
        "source_commit": "1" * 40,
        "schema_head": "schema-1",
        "runtime_mode": "lan",
    }
    operation = {
        "schema_version": 1,
        "id": operation_id,
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
    request_path = request_dir / f"{operation_id}.json"
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
    return root, current_root, target_root, current, args


def manifests(target_root: Path):
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

    return target_manifest, verified_manifest


def test_capacity_failure_stops_before_backup_install_and_preserves_current(tmp_path: Path) -> None:
    root, _, target_root, current, args = fixture_state(tmp_path, "operation-capacity")
    _, verified_manifest = manifests(target_root)
    request_path = root / "requests" / "operation-capacity.json"
    command_run = Mock()

    with (
        patch.object(manager, "verify_staged_bundle", side_effect=verified_manifest),
        patch.object(
            manager,
            "run_capacity_preflight",
            side_effect=manager.VersionManagerFailure("capacity blocked"),
        ),
        patch.object(manager.subprocess, "run", command_run),
    ):
        with pytest.raises(manager.VersionManagerFailure, match="capacity blocked"):
            manager.execute_request(args, request_path)

    command_run.assert_not_called()
    assert json.loads((root / "current.json").read_text(encoding="utf-8")) == current
    failed = json.loads((root / "operations" / "operation-capacity.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["phase"] == "checking_capacity"
    assert failed["phase_status"] == "failed"
    assert failed["completed_phases"] == ["verifying_package"]
    assert failed.get("backup_evidence_id") is None
    assert not request_path.exists()


def test_backup_failure_stops_before_install_and_preserves_current(tmp_path: Path) -> None:
    root, _, target_root, current, args = fixture_state(tmp_path, "operation-1")
    args.local_auth = True
    _, verified_manifest = manifests(target_root)
    request_path = root / "requests" / "operation-1.json"
    calls: list[list[str]] = []

    def fail_backup(command: list[str], **_: object) -> None:
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)

    with (
        patch.object(manager, "verify_staged_bundle", side_effect=verified_manifest),
        patch.object(manager, "run_capacity_preflight", return_value="operation-evidence/operation-1/capacity-preflight.txt"),
        patch.object(manager.subprocess, "run", side_effect=fail_backup),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            manager.execute_request(args, request_path)

    assert len(calls) == 1
    assert "pg_dump" in calls[0][-1]
    assert json.loads((root / "current.json").read_text(encoding="utf-8")) == current
    failed = json.loads((root / "operations" / "operation-1.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["phase"] == "creating_backup"
    assert failed["phase_status"] == "failed"
    assert failed["completed_phases"] == ["verifying_package", "checking_capacity"]
    assert failed["capacity_evidence_id"].endswith("capacity-preflight.txt")
    assert failed["backup_evidence_id"] is None
    assert not request_path.exists()


@pytest.mark.parametrize("install_fails", [False, True])
def test_worker_records_verified_success_or_truthful_post_mutation_failure(
    tmp_path: Path,
    install_fails: bool,
) -> None:
    root, _, target_root, _, args = fixture_state(tmp_path, "operation-2")
    request_path = root / "requests" / "operation-2.json"
    installer = target_root / "scripts" / "install-offline-bundle.sh"
    _, verified_manifest = manifests(target_root)
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
        patch.object(manager, "run_capacity_preflight", return_value="operation-evidence/operation-2/capacity-preflight.txt"),
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
    completed = json.loads((root / "operations" / "operation-2.json").read_text(encoding="utf-8"))
    if install_fails:
        assert len(calls) == 3
        assert deployed["bundle_id"] == "release-1"
        assert deployed["runtime_state_known"] is False
        assert deployed["health"] == "verification_failed"
        assert completed["status"] == "failed"
        assert completed["phase"] == "applying_update"
        assert completed["phase_status"] == "failed"
        assert completed["completed_phases"] == [
            "verifying_package",
            "checking_capacity",
            "creating_backup",
        ]
        assert not request_path.exists()
        return

    assert calls[3][-2:] == ["alembic", "current"]
    assert deployed["bundle_id"] == "release-2"
    assert deployed["previous_bundle_id"] == "release-1"
    assert deployed["schema_head"] == "schema-2"
    assert completed["status"] == "succeeded"
    assert completed["result_code"] == "verified_ready"
    assert completed["backup_evidence_id"] == "operation-2-postgresql.dump"
    assert completed["capacity_evidence_id"].endswith("capacity-preflight.txt")
    assert completed["phase"] == "done"
    assert completed["phase_status"] == "succeeded"
    assert completed["completed_phases"] == [
        "verifying_package",
        "checking_capacity",
        "creating_backup",
        "applying_update",
        "verifying_runtime",
    ]


def test_capacity_preflight_requires_pass_evidence(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    guard = tmp_path / "deploy-capacity-guard.sh"
    guard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    report = root / "operation-evidence" / "operation-3" / "capacity-preflight.txt"

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert command[0] == "bash"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("status=PASS\nfree_bytes=100\nrequired_bytes=10\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(manager.Path, "resolve", autospec=True, side_effect=lambda value: value),
        patch.object(manager.subprocess, "run", side_effect=fake_run),
    ):
        # Exercise report validation through an injected sibling location without relying on host layout.
        original_file = manager.__file__
        manager.__file__ = str(tmp_path / "nexolab-version-manager.py")
        try:
            evidence = manager.run_capacity_preflight(root, "operation-3")
        finally:
            manager.__file__ = original_file

    assert evidence == "operation-evidence/operation-3/capacity-preflight.txt"


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


def transition_fixture(tmp_path: Path):
    root = tmp_path / "versions"
    target_root = root / "catalog" / "release-current"
    (target_root / "scripts").mkdir(parents=True)
    (target_root / "scripts" / "install-offline-bundle.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8"
    )
    target = {
        "schema_version": 1,
        "bundle_version": "2026.08.24",
        "source_commit": "c" * 40,
        "created_at": "2026-08-24T09:00:00+00:00",
        "platform": "linux/arm64",
        "dashboard": {
            "origin": "http://172.18.48.66:3000",
            "api_base_url": "http://172.18.48.66:8082",
            "auth_provider": "local",
        },
        "local_auth": {"selected": True},
        "version_management": {
            "bundle_id": "release-current",
            "database_schema": {
                "head": "schema-current",
                "upgrade_from": ["schema-current"],
                "runtime_compatible_schema_heads": ["schema-current"],
            },
        },
    }
    (target_root / "manifest.json").write_text(
        json.dumps(target, sort_keys=True), encoding="utf-8"
    )
    current = {
        "schema_version": 1,
        "bundle_id": "source-main-cccccccccccc",
        "bundle_root": None,
        "release": "source-main-cccccccccccc",
        "source_commit": "c" * 40,
        "build_timestamp": "2026-08-24T08:00:00+00:00",
        "runtime_mode": "lan",
        "platform": "linux/arm64",
        "schema_head": "schema-current",
        "deployed_at": "2026-08-24T08:30:00+00:00",
        "health": "ready",
        "runtime_state_known": True,
        "previous_bundle_id": None,
        "previous_release": None,
        "last_operation_id": None,
        "deployment_authority": manager.SOURCE_DEPLOYMENT_AUTHORITY,
        "known_packaged_release": False,
        "source_deployment_evidence": "runtime/deployments/current",
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "current.json").write_text(json.dumps(current), encoding="utf-8")
    (root / "requests").mkdir()
    (root / "operations").mkdir()
    central_env = tmp_path / "central.env"
    central_env.write_text(
        "CENTRAL_BIND_ADDRESS=172.18.48.66\nAUTH_MODE=jwt\n", encoding="utf-8"
    )
    edge_env = tmp_path / "edge.env"
    edge_env.write_text("MQTT_HOST=mqtt\n", encoding="utf-8")
    args = argparse.Namespace(
        root=root,
        bundle_id="release-current",
        central_env=central_env,
        edge_env=edge_env,
        backup_dir=tmp_path / "backups",
        skip_edge=False,
        local_auth=True,
    )
    volumes = [
        {
            "name": name,
            "driver": "local",
            "mountpoint": f"/var/lib/docker/volumes/{name}/_data",
            "created_at": "2026-08-01T00:00:00Z",
            "scope": "local",
        }
        for name in manager.persistent_volume_names(skip_edge=False)
    ]
    return root, target_root, target, current, args, volumes


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda current, target: current.update(deployment_authority="manual"), "trusted controlled source lineage"),
        (lambda current, target: target.update(source_commit="d" * 40), "source commit"),
        (
            lambda current, target: target["version_management"]["database_schema"].update(head="other"),
            "exact current schema head",
        ),
        (lambda current, target: current.update(health="degraded"), "not verified ready"),
    ],
)
def test_source_transition_preconditions_fail_closed(tmp_path: Path, mutation, message: str) -> None:
    _, _, target, current, args, _ = transition_fixture(tmp_path)
    mutation(current, target)
    with pytest.raises(manager.VersionManagerFailure, match=message):
        manager.validate_source_transition(current, target, args)


def test_active_operation_blocks_source_transition(tmp_path: Path) -> None:
    root, _, _, _, _, _ = transition_fixture(tmp_path)
    (root / "requests" / "queued.json").write_text("{}", encoding="utf-8")
    with pytest.raises(manager.VersionManagerFailure, match="already queued"):
        manager.assert_no_active_version_operation(root)


def test_update_plane_lock_blocks_source_transition(tmp_path: Path) -> None:
    root, _, target, _, args, _ = transition_fixture(tmp_path)
    update_lock_path = root / "update-plane.lock"
    with update_lock_path.open("a+", encoding="utf-8") as update_lock:
        fcntl.flock(update_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch.object(manager, "verify_staged_bundle", return_value=target):
            with pytest.raises(manager.VersionManagerFailure, match="update plane is active"):
                manager.establish_package_authority(args)


def test_backup_failure_preserves_source_authority_and_skips_install(tmp_path: Path) -> None:
    root, _, target, current, args, volumes = transition_fixture(tmp_path)
    installer_run = Mock()
    with (
        patch.object(manager, "verify_staged_bundle", return_value=target),
        patch.object(manager, "source_transition_id", return_value="transition-backup-fail"),
        patch.object(manager, "capture_volume_identities", return_value=volumes),
        patch.object(manager, "run_capacity_preflight", return_value="capacity.txt"),
        patch.object(
            manager,
            "create_postgresql_backup",
            side_effect=manager.VersionManagerFailure("backup failed"),
        ),
        patch.object(manager.subprocess, "run", installer_run),
    ):
        with pytest.raises(manager.VersionManagerFailure, match="backup failed"):
            manager.establish_package_authority(args)

    installer_run.assert_not_called()
    assert json.loads((root / "current.json").read_text(encoding="utf-8")) == current
    evidence = json.loads(
        (root / "operation-evidence" / "transition-backup-fail" / "transition.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "failed"
    assert evidence["failure_type"] == "VersionManagerFailure"


def test_installer_failure_preserves_source_authority(tmp_path: Path) -> None:
    root, target_root, target, current, args, volumes = transition_fixture(tmp_path)
    installer = target_root / "scripts" / "install-offline-bundle.sh"

    def fail_installer(command: list[str], **_: object):
        assert command[0] == str(installer)
        raise subprocess.CalledProcessError(1, command)

    with (
        patch.object(manager, "verify_staged_bundle", return_value=target),
        patch.object(manager, "source_transition_id", return_value="transition-install-fail"),
        patch.object(manager, "capture_volume_identities", return_value=volumes),
        patch.object(manager, "run_capacity_preflight", return_value="capacity.txt"),
        patch.object(manager, "create_postgresql_backup", return_value=args.backup_dir / "backup.dump"),
        patch.object(manager.subprocess, "run", side_effect=fail_installer),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            manager.establish_package_authority(args)

    failed_current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert failed_current["deployment_authority"] == manager.SOURCE_DEPLOYMENT_AUTHORITY
    assert failed_current["source_commit"] == current["source_commit"]
    assert failed_current["runtime_state_known"] is False
    assert failed_current["health"] == "verification_failed"


def test_volume_identity_drift_blocks_authority_commit(tmp_path: Path) -> None:
    root, _, target, current, args, volumes = transition_fixture(tmp_path)
    changed = [dict(item) for item in volumes]
    changed[0]["created_at"] = "2026-08-24T10:00:00Z"
    with (
        patch.object(manager, "verify_staged_bundle", return_value=target),
        patch.object(manager, "source_transition_id", return_value="transition-volume-fail"),
        patch.object(manager, "capture_volume_identities", side_effect=[volumes, changed]),
        patch.object(manager, "run_capacity_preflight", return_value="capacity.txt"),
        patch.object(manager, "create_postgresql_backup", return_value=args.backup_dir / "backup.dump"),
        patch.object(manager, "verify_transition_runtime", return_value={"status": "verified"}),
        patch.object(manager.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
    ):
        with pytest.raises(manager.VersionManagerFailure, match="volume identities changed"):
            manager.establish_package_authority(args)

    failed_current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert failed_current["deployment_authority"] == manager.SOURCE_DEPLOYMENT_AUTHORITY
    assert failed_current["source_commit"] == current["source_commit"]
    assert failed_current["runtime_state_known"] is False
    assert failed_current["health"] == "verification_failed"


def test_success_commits_catalog_backed_authority_and_preserves_source_evidence(tmp_path: Path) -> None:
    root, target_root, target, current, args, volumes = transition_fixture(tmp_path)
    runtime_evidence = {
        "readiness": {"status": "ready", "database": "ready", "mqtt": "ready"},
        "schema_head": "schema-current",
        "device_agent": {"status": "verified"},
    }
    with (
        patch.object(manager, "verify_staged_bundle", return_value=target),
        patch.object(manager, "source_transition_id", return_value="transition-success"),
        patch.object(manager, "capture_volume_identities", side_effect=[volumes, volumes]),
        patch.object(manager, "run_capacity_preflight", return_value="capacity.txt"),
        patch.object(manager, "create_postgresql_backup", return_value=args.backup_dir / "backup.dump"),
        patch.object(manager, "verify_transition_runtime", return_value=runtime_evidence),
        patch.object(manager.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
    ):
        manager.establish_package_authority(args)

    deployed = json.loads((root / "current.json").read_text(encoding="utf-8"))
    assert deployed["bundle_id"] == "release-current"
    assert deployed["bundle_root"] == str(target_root)
    assert deployed["source_commit"] == current["source_commit"]
    assert deployed["deployment_authority"] == manager.PACKAGED_DEPLOYMENT_AUTHORITY
    assert deployed["runtime_state_known"] is True
    assert deployed["transition_evidence_id"] == "transition-success"
    assert deployed["previous_source_commit"] == current["source_commit"]
    assert deployed["previous_source_deployment_evidence"] == current["source_deployment_evidence"]

    evidence_dir = root / "operation-evidence" / "transition-success"
    assert json.loads((evidence_dir / "source-lineage-before.json").read_text(encoding="utf-8")) == current
    evidence = json.loads((evidence_dir / "transition.json").read_text(encoding="utf-8"))
    assert evidence["status"] == "succeeded"
    assert evidence["result_code"] == "packaged_authority_established"
    assert evidence["backup_evidence_id"].endswith("-postgresql.dump")
    assert evidence["runtime_verification"] == runtime_evidence
    assert evidence["volume_identities_before"] == evidence["volume_identities_after"]
