"""Pure/test-directory-only NEXOLAB #1460 offline DR source preflight tests."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "nexolab-offline-backup-preflight.py"
SPEC = importlib.util.spec_from_file_location("nexolab_backup_preflight", SOURCE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def valid_policy() -> dict:
    return {
        "schema_version": 1,
        "bundle": {"encryption": "aes-256-gcm", "key_source": "mounted_file"},
        "assets": [
            {"id": name, "required": True, "kind": "external_file"}
            for name in sorted(module.MANDATORY)
        ],
    }


def test_real_repo_policy_fails_closed_on_incomplete_inventory(tmp_path):
    repo_policy = SOURCE.parents[1] / "security/disaster-recovery-assets.json"
    data = module.evaluate(repo_policy, tmp_path)
    assert data["status"] == "BLOCKED"
    assert "incomplete_mandatory_inventory" in data["reasons"]
    assert "object_storage_source_authority_unreconciled" in data["reasons"]
    assert data["backup_performed"] is False
    assert data["restore_performed"] is False
    assert list(tmp_path.iterdir()) == []


def test_valid_synthetic_inventory_still_does_not_authorize_backup(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(valid_policy()))
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    data = module.evaluate(policy, staging)
    assert "incomplete_mandatory_inventory" not in data["reasons"]
    assert "site_activation_not_approved" in data["reasons"]
    assert "isolated_restore_unverified" in data["reasons"]
    assert data["status"] == "BLOCKED"


def test_space_cap_and_headroom_use_available_not_free_blocks(tmp_path, monkeypatch):
    class Space:
        f_frsize = 4096
        f_bavail = (23 * 1024**3) // 4096
    monkeypatch.setattr(module.os, "statvfs", lambda path: Space())
    free, reasons = module.check_staging(tmp_path)
    assert free == 23 * 1024**3
    assert "insufficient_capacity_for_20gib_reserve_plus_4gib_cap" in reasons


@pytest.mark.parametrize("changed", ["edge-sqlite", "postgresql", "local-auth-private-key"])
def test_missing_mandatory_asset_fail_closed(changed):
    data = valid_policy()
    data["assets"] = [x for x in data["assets"] if x["id"] != changed]
    assert "incomplete_mandatory_inventory" in module.evaluate_policy(data)


def test_duplicate_asset_and_not_required_fail_closed():
    data = valid_policy()
    data["assets"].append(dict(data["assets"][0]))
    data["assets"][1]["required"] = False
    reasons = module.evaluate_policy(data)
    assert "duplicate_asset_identity" in reasons
    assert "mandatory_asset_not_required" in reasons


def test_duplicate_json_keys_not_silently_accepted(tmp_path):
    file = tmp_path / "policy.json"
    file.write_text('{"schema_version":1,"schema_version":1,"assets":[]}')
    with pytest.raises(module.PreflightError, match="duplicate_policy_json_key"):
        module.read_policy(file)


def test_symlink_policy_and_staging_fail_closed(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(valid_policy()))
    link = tmp_path / "policy-link"
    link.symlink_to(policy)
    with pytest.raises(module.PreflightError, match="policy_not_regular_file"):
        module.read_policy(link)
    staging = tmp_path / "staging"
    staging.mkdir()
    other = tmp_path / "staging-link"
    other.symlink_to(staging, target_is_directory=True)
    assert module.check_staging(other)[1] == ["staging_not_regular_directory"]


def test_world_writable_staging_rejected(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    staging.chmod(0o777)
    assert "staging_allows_untrusted_writes" in module.check_staging(staging)[1]


def test_cli_is_read_only_and_exits_blocked(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(valid_policy()))
    before = sorted(x.name for x in tmp_path.iterdir())
    result = subprocess.run(
        [sys.executable, "-B", str(SOURCE), "--check", "--policy", str(policy),
         "--staging-dir", str(tmp_path)],
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 78
    report = json.loads(result.stdout)
    assert report["status"] == "BLOCKED"
    assert report["backup_performed"] is False
    assert sorted(x.name for x in tmp_path.iterdir()) == before


@pytest.mark.parametrize("argument", ["--execute", "--delete", "--force", "--backup"])
def test_unsupported_mutating_flags_refused(tmp_path, argument):
    result = subprocess.run([sys.executable, "-B", str(SOURCE), argument],
                            text=True, capture_output=True, timeout=5, check=False)
    assert result.returncode != 0
