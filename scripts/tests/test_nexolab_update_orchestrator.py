from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-update-orchestrator.py"
SPEC = importlib.util.spec_from_file_location("nexolab_update_orchestrator", SCRIPT)
assert SPEC and SPEC.loader
orchestrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(tmp_path: Path) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    run_git(repo, "config", "user.email", "nexolab-tests@example.invalid")
    run_git(repo, "config", "user.name", "NEXOLAB Tests")
    run_git(repo, "checkout", "-b", "main")
    (repo / "README.md").write_text("one\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "one")
    run_git(repo, "push", "-u", "origin", "main")
    current = run_git(repo, "rev-parse", "HEAD")
    return repo, current


def current_file(root: Path, commit: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "current.json").write_text(
        json.dumps(
            {
                "source_commit": commit,
                "bundle_id": "release-1",
                "release": "1.0.0",
            }
        ),
        encoding="utf-8",
    )


def write_validated_catalog_entry(
    root: Path,
    *,
    bundle_id: str,
    release: str,
    commit: str,
    platform: str = "linux/arm64",
    schema_head: str = "schema-1",
    upgrade_from: tuple[str, ...] = ("schema-1",),
) -> Path:
    bundle_root = root / "catalog" / bundle_id
    bundle_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "bundle_version": release,
        "source_commit": commit,
        "platform": platform,
        "persistent_data_policy": {
            "packaged": False,
            "delete_volumes": False,
            "compose_down_v_allowed": False,
        },
        "version_management": {
            "bundle_id": bundle_id,
            "database_schema": {
                "head": schema_head,
                "upgrade_from": list(upgrade_from),
                "runtime_compatible_schema_heads": [schema_head],
            },
            "backup_required": True,
            "migration_before_readiness": True,
            "preserve_named_volumes": True,
            "preserve_edge_sqlite": True,
        },
    }
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (bundle_root / "manifest.json").write_bytes(raw)
    (bundle_root / ".nexolab-validated.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return bundle_root


def advance_remote(tmp_path: Path, repo: Path) -> str:
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(other)], check=True, capture_output=True)
    run_git(other, "config", "user.email", "nexolab-tests@example.invalid")
    run_git(other, "config", "user.name", "NEXOLAB Tests")
    run_git(other, "checkout", "main")
    (other / "README.md").write_text("two\n", encoding="utf-8")
    run_git(other, "add", "README.md")
    run_git(other, "commit", "-m", "two")
    run_git(other, "push", "origin", "main")
    run_git(repo, "fetch", "origin", "main")
    return run_git(repo, "rev-parse", "origin/main")


def test_policy_defaults_off_and_persists_explicit_enable(tmp_path: Path) -> None:
    root = tmp_path / "versions"

    assert orchestrator.load_policy(root) == {
        "schema_version": 1,
        "automatic_updates_enabled": False,
        "schedule_local_time": "02:00",
        "updated_at": None,
        "updated_by": None,
    }

    saved = orchestrator.save_policy(root, True, "admin@example.invalid")

    assert saved["automatic_updates_enabled"] is True
    assert saved["schedule_local_time"] == "02:00"
    assert saved["updated_by"] == "admin@example.invalid"
    assert orchestrator.load_policy(root)["automatic_updates_enabled"] is True


def test_policy_rejects_schedule_drift(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    root.mkdir()
    (root / "update-policy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "automatic_updates_enabled": True,
                "schedule_local_time": "03:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="fixed at 02:00"):
        orchestrator.load_policy(root)


def test_repository_normalization_accepts_only_expected_github_shapes() -> None:
    assert orchestrator.normalized_repository("git@github.com:eNgine9r/nexolab-platform.git") == (
        "eNgine9r/nexolab-platform"
    )
    assert orchestrator.normalized_repository("https://github.com/eNgine9r/nexolab-platform.git") == (
        "eNgine9r/nexolab-platform"
    )
    assert orchestrator.normalized_repository("https://example.invalid/nexolab-platform.git") is None


def test_up_to_date_discovery_is_non_mutating_and_not_eligible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    current_file(root, current)
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["status"] == "completed"
    assert result["result_code"] == "up_to_date"
    assert result["current_commit"] == current
    assert result["target_commit"] == current
    assert result["candidate_available"] is False
    assert result["activation_eligible"] is False
    assert not (root / "catalog").exists()


def test_newer_fast_forward_revision_is_candidate_but_never_install_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    current_file(root, current)
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )

    target = advance_remote(tmp_path, repo)

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["result_code"] == "candidate_discovered"
    assert result["target_commit"] == target
    assert result["candidate_available"] is True
    assert result["activation_eligible"] is False
    assert result["blocked_reason"] == "validated_package_required"


def test_newer_revision_becomes_eligible_only_with_matching_validated_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    root.mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps(
            {
                "source_commit": current,
                "bundle_id": "release-1",
                "release": "1.0.0",
                "platform": "linux/arm64",
                "schema_head": "schema-1",
            }
        ),
        encoding="utf-8",
    )
    write_validated_catalog_entry(
        root,
        bundle_id="release-1",
        release="1.0.0",
        commit=current,
    )
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )
    target = advance_remote(tmp_path, repo)
    write_validated_catalog_entry(
        root,
        bundle_id="release-2",
        release="2.0.0",
        commit=target,
    )

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["candidate_available"] is True
    assert result["candidate_bundle_id"] == "release-2"
    assert result["activation_eligible"] is True
    assert result["blocked_reason"] is None


def test_tampered_target_validation_marker_never_becomes_activation_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    root.mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps(
            {
                "source_commit": current,
                "bundle_id": "release-1",
                "release": "1.0.0",
                "platform": "linux/arm64",
                "schema_head": "schema-1",
            }
        ),
        encoding="utf-8",
    )
    write_validated_catalog_entry(
        root,
        bundle_id="release-1",
        release="1.0.0",
        commit=current,
    )
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )
    target = advance_remote(tmp_path, repo)
    target_root = write_validated_catalog_entry(
        root,
        bundle_id="release-2",
        release="2.0.0",
        commit=target,
    )
    marker = json.loads((target_root / ".nexolab-validated.json").read_text(encoding="utf-8"))
    marker["manifest_sha256"] = "0" * 64
    (target_root / ".nexolab-validated.json").write_text(json.dumps(marker), encoding="utf-8")

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["candidate_available"] is True
    assert result["candidate_bundle_id"] is None
    assert result["activation_eligible"] is False
    assert result["blocked_reason"] == "validated_package_required"


def test_tracked_local_change_blocks_discovery_without_runtime_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    current_file(root, current)
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["status"] == "blocked"
    assert result["result_code"] == "tracked_worktree_dirty"
    assert result["activation_eligible"] is False


def test_wrong_branch_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    current_file(root, current)
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )
    run_git(repo, "checkout", "-b", "feature")

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=False)

    assert result["result_code"] == "branch_mismatch"
    assert result["candidate_available"] is False


def test_github_unavailable_is_non_destructive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, current = init_repo(tmp_path)
    root = tmp_path / "versions"
    current_file(root, current)
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )
    run_git(repo, "remote", "set-url", "origin", "https://127.0.0.1:9/unavailable.git")
    monkeypatch.setattr(
        orchestrator,
        "normalized_repository",
        lambda _remote: orchestrator.EXPECTED_REPOSITORY,
    )

    result = orchestrator.discover(root, repo, actor="admin", fetch_remote=True)

    assert result["status"] == "blocked"
    assert result["result_code"] == "github_unavailable"
    assert result["activation_eligible"] is False
    assert json.loads((root / "current.json").read_text(encoding="utf-8"))["source_commit"] == current
