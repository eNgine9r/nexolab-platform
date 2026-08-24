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
SPEC = importlib.util.spec_from_file_location("nexolab_version_manager_source_transition", SCRIPT)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


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
