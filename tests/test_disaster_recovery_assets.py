from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "security" / "disaster-recovery-assets.json"
MODULE_PATH = ROOT / "scripts" / "validate-disaster-recovery-assets.py"
SPEC = importlib.util.spec_from_file_location("disaster_recovery_policy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def write_policy(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_policy_is_valid() -> None:
    payload = MODULE.validate_policy(POLICY_PATH)

    assert [asset["id"] for asset in payload["assets"]] == [
        "postgresql",
        "object-storage",
        "mqtt-dynamic-security",
        "local-auth-private-key",
        "local-auth-public-key",
    ]
    assert payload["bundle"]["encryption"] == "aes-256-gcm"


def test_policy_requires_complete_asset_set(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"] = payload["assets"][:-1]

    with pytest.raises(MODULE.ValidationFailure, match="exactly the required"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_duplicate_restore_order(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][1]["restore_order"] = 10

    with pytest.raises(MODULE.ValidationFailure, match="restore_order values"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_unsafe_backup_path(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][0]["backup_path"] = "../postgres.dump"

    with pytest.raises(MODULE.ValidationFailure, match="unsafe path component"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_restore_prefix_overlapping_source(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][0]["restore_volume_prefix"] = (
        "nexolab-central-postgres-data-"
    )

    with pytest.raises(MODULE.ValidationFailure, match="overlaps the source"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_volume_fields_for_external_key(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][3]["source_volume"] = "unexpected-secret-volume"

    with pytest.raises(MODULE.ValidationFailure, match="valid only for volume assets"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_versioned_secret_or_command(tmp_path: Path) -> None:
    for key, value in (
        ("password", "not-allowed"),
        ("backup_command", "pg_dump --password=not-allowed"),
    ):
        payload = policy()
        payload["assets"][0][key] = value

        with pytest.raises(MODULE.ValidationFailure, match="is forbidden"):
            MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_requires_mounted_key_source(tmp_path: Path) -> None:
    payload = policy()
    payload["bundle"]["key_source"] = "environment"

    with pytest.raises(MODULE.ValidationFailure, match="mounted_file"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_duplicate_output_path(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][2]["backup_path"] = payload["assets"][0]["backup_path"]

    with pytest.raises(MODULE.ValidationFailure, match="backup paths must be unique"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_reordered_restore_plan(tmp_path: Path) -> None:
    payload = policy()
    assets = payload["assets"]
    payload["assets"] = [assets[1], assets[0], *assets[2:]]

    with pytest.raises(MODULE.ValidationFailure, match="declared in restore_order"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_rejects_non_object_storage_bucket_fields(tmp_path: Path) -> None:
    payload = policy()
    payload["assets"][0]["bucket"] = "unexpected"

    with pytest.raises(MODULE.ValidationFailure, match="valid only for object storage"):
        MODULE.validate_policy(write_policy(tmp_path, payload))


def test_policy_copy_is_independent() -> None:
    first = policy()
    second = copy.deepcopy(first)
    second["assets"][0]["id"] = "changed"

    assert first["assets"][0]["id"] == "postgresql"
