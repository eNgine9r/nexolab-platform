from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock


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
    )


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
