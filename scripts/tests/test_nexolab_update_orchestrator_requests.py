from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-update-orchestrator.py"
SPEC = importlib.util.spec_from_file_location("nexolab_update_orchestrator_requests", SCRIPT)
assert SPEC and SPEC.loader
orchestrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator)


def test_scheduled_check_exits_before_discovery_when_policy_is_off(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    discover = Mock()
    monkeypatch.setattr(orchestrator, "discover", discover)

    result = orchestrator.scheduled_check(root, tmp_path / "repo")

    assert result == {
        "status": "skipped",
        "result_code": "automatic_updates_disabled",
        "schedule_local_time": "02:00",
    }
    discover.assert_not_called()
    assert not (root / "update-check.json").exists()


def test_scheduled_check_uses_deterministic_system_actor_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    orchestrator.save_policy(root, True, "admin")
    discover = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(orchestrator, "discover", discover)

    result = orchestrator.scheduled_check(root, tmp_path / "repo")

    assert result == {"status": "completed"}
    discover.assert_called_once_with(
        root,
        tmp_path / "repo",
        actor="system:update-timer",
        fetch_remote=True,
        git_user=None,
    )


def test_scheduled_check_queues_only_an_eligible_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    orchestrator.save_policy(root, True, "admin")
    discovered = {
        "schema_version": 1,
        "status": "completed",
        "source": "scheduled",
        "actor": "system:update-timer",
        "target_commit": "2" * 40,
        "candidate_bundle_id": "release-2",
        "activation_eligible": True,
        "blocked_reason": None,
        "message": "eligible",
    }
    discover = Mock(return_value=discovered)
    enqueue = Mock(return_value={"id": "operation-1", "status": "queued"})
    monkeypatch.setattr(orchestrator, "discover", discover)
    monkeypatch.setattr(orchestrator, "enqueue_scheduled_activation", enqueue)

    result = orchestrator.scheduled_check(root, tmp_path / "repo")

    assert result["automatic_activation_operation_id"] == "operation-1"
    assert result["activation_eligible"] is True
    enqueue.assert_called_once_with(root, discovered)


def test_enqueue_scheduled_activation_uses_existing_version_manager_queue(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    (root / "catalog" / "release-2").mkdir(parents=True)
    (root / "current.json").write_text(
        json.dumps(
            {
                "bundle_id": "release-1",
                "release": "1.0.0",
                "source_commit": "1" * 40,
                "platform": "linux/arm64",
                "schema_head": "schema-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "validated_candidate_bundle",
        lambda _root, _commit: ("release-2", ""),
    )
    monkeypatch.setattr(
        orchestrator,
        "_validated_catalog_manifest",
        lambda _path: {"bundle_version": "2.0.0"},
    )
    check = {
        "source": "scheduled",
        "actor": "system:update-timer",
        "target_commit": "2" * 40,
        "candidate_bundle_id": "release-2",
        "activation_eligible": True,
    }

    operation = orchestrator.enqueue_scheduled_activation(root, check)

    assert operation["actor_subject"] == "system:update-timer"
    assert operation["action"] == "update"
    assert operation["source_bundle_id"] == "release-1"
    assert operation["target_bundle_id"] == "release-2"
    assert operation["target_commit"] == "2" * 40
    assert operation["status"] == "queued"
    request = root / "requests" / f"{operation['id']}.json"
    evidence = root / "operations" / f"{operation['id']}.json"
    assert request.is_file()
    assert evidence.is_file()
    assert json.loads(request.read_text(encoding="utf-8")) == operation
    assert json.loads(evidence.read_text(encoding="utf-8")) == operation


def test_enqueue_scheduled_activation_blocks_when_an_operation_is_active(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    (root / "catalog" / "release-2").mkdir(parents=True)
    (root / "operations").mkdir(parents=True)
    (root / "operations" / "active.json").write_text(
        json.dumps({"status": "running"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "validated_candidate_bundle",
        lambda _root, _commit: ("release-2", ""),
    )
    check = {
        "source": "scheduled",
        "actor": "system:update-timer",
        "target_commit": "2" * 40,
        "candidate_bundle_id": "release-2",
        "activation_eligible": True,
    }

    with pytest.raises(orchestrator.CheckBlocked) as caught:
        orchestrator.enqueue_scheduled_activation(root, check)

    assert caught.value.code == "operation_in_progress"
    assert list((root / "requests").glob("*.json")) == []


def test_manual_request_is_consumed_once_and_keeps_human_actor(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "versions"
    request_dir = root / "update-check-requests"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "check-1.json"
    request_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "check-1",
                "organization_id": "org-1",
                "actor_subject": "admin@example.invalid",
                "source": "manual",
                "status": "queued",
                "requested_at": "2026-08-18T07:20:00Z",
                "reason": None,
            }
        ),
        encoding="utf-8",
    )
    discover = Mock(return_value={"status": "completed", "result_code": "up_to_date"})
    monkeypatch.setattr(orchestrator, "discover", discover)

    result = orchestrator.process_requested_check(root, tmp_path / "repo")

    assert result["request_id"] == "check-1"
    assert result["check"]["result_code"] == "up_to_date"
    discover.assert_called_once_with(
        root,
        tmp_path / "repo",
        actor="admin@example.invalid",
        fetch_remote=True,
        git_user=None,
    )
    assert not request_path.exists()
    assert orchestrator.process_requested_check(root, tmp_path / "repo") == {
        "status": "idle",
        "result_code": "no_pending_update_check",
    }


def test_malformed_request_is_preserved_as_rejected_evidence(tmp_path: Path) -> None:
    root = tmp_path / "versions"
    request_dir = root / "update-check-requests"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "bad.json"
    request_path.write_text(
        json.dumps({"schema_version": 99, "status": "queued"}),
        encoding="utf-8",
    )

    result = orchestrator.process_requested_check(root, tmp_path / "repo")

    assert result["status"] == "failed"
    assert result["result_code"] == "invalid_update_check_request"
    assert not request_path.exists()
    assert (root / "update-check-rejected" / "bad.json").is_file()
    durable = json.loads((root / "update-check.json").read_text(encoding="utf-8"))
    assert durable["blocked_reason"] == "invalid_update_check_request"
    assert durable["activation_eligible"] is False


def test_git_commands_can_run_as_the_repository_owner(tmp_path: Path) -> None:
    command = orchestrator.git_command(tmp_path, "status", git_user="nexolab")

    assert command[:5] == ["runuser", "-u", "nexolab", "--", "git"]
    assert command[5:] == ["-C", str(tmp_path), "status"]
