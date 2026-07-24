from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.model_registry import register_models
from app.sessions.audit_repository import AuditedSessionRepository
from app.sessions.models import AuditLog, SessionEvent, TestSession
from app.sessions.schemas import SessionCreate
from app.sessions.telemetry_attribution import SessionAwareDatabase


def build_client(database_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def create_payload(number: str, occurred_at: datetime) -> dict[str, object]:
    return {
        "session_number": number,
        "title": "Audit workflow",
        "test_object": "K106",
        "node_id": "edge-01",
        "actor_id": "operator-1",
        "actor_source": "dashboard",
        "occurred_at": occurred_at.isoformat(),
        "reason": "Create controlled test session",
    }


def post_command(
    client: TestClient,
    path: str,
    *,
    key: str,
    payload: dict[str, object],
    expected_status: int = 200,
) -> dict:
    response = client.post(
        path,
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == expected_status, response.text
    return response.json()


def create_session(
    client: TestClient,
    *,
    number: str,
    occurred_at: datetime,
    key: str | None = None,
) -> dict:
    return post_command(
        client,
        "/api/v1/sessions",
        key=key or f"create-{number}",
        payload=create_payload(number, occurred_at),
        expected_status=201,
    )


def test_create_replay_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "audit-restart.db"
    occurred_at = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)
    payload = create_payload("NXL-AUDIT-001", occurred_at)

    with build_client(database_path) as first_client:
        first = post_command(
            first_client,
            "/api/v1/sessions",
            key="restart-create-key",
            payload=payload,
            expected_status=201,
        )
        assert first["replayed"] is False

    with build_client(database_path) as restarted_client:
        replay = post_command(
            restarted_client,
            "/api/v1/sessions",
            key="restart-create-key",
            payload=payload,
            expected_status=201,
        )
        assert replay["replayed"] is True
        assert replay["session"]["id"] == first["session"]["id"]
        assert replay["event"]["id"] == first["event"]["id"]

        events = restarted_client.get(
            f"/api/v1/sessions/{first['session']['id']}/events"
        )
        audit = restarted_client.get(
            f"/api/v1/sessions/{first['session']['id']}/audit"
        )
        assert events.status_code == 200, events.text
        assert audit.status_code == 200, audit.text
        assert events.json()["count"] == 1
        assert audit.json()["count"] == 1


def test_create_key_reuse_with_different_payload_is_rejected(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "audit-key-reuse.db"
    base = datetime(2026, 7, 24, 15, 30, tzinfo=UTC)

    with build_client(database_path) as client:
        create_session(
            client,
            number="NXL-AUDIT-002",
            occurred_at=base,
            key="shared-create-key",
        )
        response = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": "shared-create-key"},
            json=create_payload("NXL-AUDIT-003", base),
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "idempotency_key_reused"


def test_lifecycle_key_cannot_be_reused_for_another_action(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "audit-transition-key.db"
    base = datetime(2026, 7, 24, 16, 0, tzinfo=UTC)

    with build_client(database_path) as client:
        created = create_session(
            client,
            number="NXL-AUDIT-004",
            occurred_at=base,
        )
        session_id = created["session"]["id"]
        command_payload = {
            "actor_id": "operator-1",
            "actor_source": "dashboard",
            "occurred_at": (base + timedelta(minutes=1)).isoformat(),
        }
        post_command(
            client,
            f"/api/v1/sessions/{session_id}/prepare",
            key="shared-transition-key",
            payload=command_payload,
        )
        response = client.post(
            f"/api/v1/sessions/{session_id}/start",
            headers={"Idempotency-Key": "shared-transition-key"},
            json={
                **command_payload,
                "occurred_at": (base + timedelta(minutes=2)).isoformat(),
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "idempotency_key_reused"

        stored = client.get(f"/api/v1/sessions/{session_id}")
        assert stored.status_code == 200, stored.text
        assert stored.json()["state"] == "ready"


def test_stage_note_and_audit_history_are_stable_and_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "audit-stage-note.db"
    base = datetime(2026, 7, 24, 17, 0, tzinfo=UTC)

    with build_client(database_path) as client:
        created = create_session(
            client,
            number="NXL-AUDIT-005",
            occurred_at=base,
        )
        session_id = created["session"]["id"]
        for action, minute in (("prepare", 1), ("start", 2)):
            post_command(
                client,
                f"/api/v1/sessions/{session_id}/{action}",
                key=f"{action}-{session_id}",
                payload={
                    "actor_id": "operator-1",
                    "actor_source": "dashboard",
                    "occurred_at": (base + timedelta(minutes=minute)).isoformat(),
                    "reason": f"Controlled {action}",
                },
            )

        first_stage_payload = {
            "actor_id": "operator-1",
            "actor_source": "dashboard",
            "occurred_at": (base + timedelta(minutes=3)).isoformat(),
            "reason": "Begin preparation",
            "sequence_index": 0,
            "stage_type": "preparation",
            "name": "Preparation",
        }
        first_stage = post_command(
            client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="stage-0",
            payload=first_stage_payload,
            expected_status=201,
        )
        first_replay = post_command(
            client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="stage-0",
            payload=first_stage_payload,
            expected_status=201,
        )
        assert first_replay["replayed"] is True
        assert first_replay["event"]["id"] == first_stage["event"]["id"]

        second_stage = post_command(
            client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="stage-1",
            payload={
                "actor_id": "engineer-1",
                "actor_source": "dashboard",
                "occurred_at": (base + timedelta(minutes=4)).isoformat(),
                "reason": "Preparation accepted",
                "sequence_index": 1,
                "stage_type": "main_test",
                "name": "Main test",
            },
            expected_status=201,
        )
        note_payload = {
            "actor_id": "engineer-1",
            "actor_source": "dashboard",
            "occurred_at": (base + timedelta(minutes=5)).isoformat(),
            "reason": "Operator observation",
            "stage_id": second_stage["stage"]["id"],
            "body": "Compressor cycle is stable.",
        }
        note = post_command(
            client,
            f"/api/v1/sessions/{session_id}/notes",
            key="note-1",
            payload=note_payload,
            expected_status=201,
        )
        note_replay = post_command(
            client,
            f"/api/v1/sessions/{session_id}/notes",
            key="note-1",
            payload=note_payload,
            expected_status=201,
        )
        assert note_replay["replayed"] is True
        assert note_replay["note"]["id"] == note["note"]["id"]

        events_response = client.get(
            f"/api/v1/sessions/{session_id}/events",
            params={"limit": 100},
        )
        audit_response = client.get(
            f"/api/v1/sessions/{session_id}/audit",
            params={"limit": 100},
        )
        stages_response = client.get(f"/api/v1/sessions/{session_id}/stages")
        notes_response = client.get(f"/api/v1/sessions/{session_id}/notes")
        for response in (
            events_response,
            audit_response,
            stages_response,
            notes_response,
        ):
            assert response.status_code == 200, response.text

        events = events_response.json()["items"]
        assert [event["event_type"] for event in events] == [
            "session_created",
            "session_prepared",
            "session_started",
            "stage_changed",
            "stage_changed",
            "note_added",
        ]
        assert len({event["id"] for event in events}) == len(events)
        for event in events:
            UUID(event["id"])
            assert event["actor_id"]
            assert event["actor_source"]
            assert event["idempotency_key"]
            assert event["occurred_at"].endswith(("Z", "+00:00"))

        audit_items = audit_response.json()["items"]
        assert len(audit_items) == len(events)
        assert [item["session_event_id"] for item in audit_items] == [
            event["id"] for event in events
        ]
        assert audit_items[-1]["payload"]["reason"] == "Operator observation"
        assert audit_items[-1]["payload"]["event_payload"]["note_id"] == (
            note["note"]["id"]
        )
        assert [stage["sequence_index"] for stage in stages_response.json()] == [
            0,
            1,
        ]
        assert notes_response.json()["count"] == 1


def test_session_events_and_audit_log_are_database_append_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "audit-append-only.db"
    base = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)

    with build_client(database_path) as client:
        created = create_session(
            client,
            number="NXL-AUDIT-006",
            occurred_at=base,
        )
        event_id = created["event"]["id"]
        session_id = created["session"]["id"]
        audit_response = client.get(f"/api/v1/sessions/{session_id}/audit")
        assert audit_response.status_code == 200, audit_response.text
        audit_id = audit_response.json()["items"][0]["id"]
        engine = client.app.state.database.engine

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE session_events SET reason = 'tampered' "
                        "WHERE id = :event_id"
                    ),
                    {"event_id": event_id},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM audit_log WHERE id = :audit_id"),
                    {"audit_id": audit_id},
                )

        with Session(engine) as db_session:
            assert db_session.get(SessionEvent, event_id) is not None
            assert db_session.get(AuditLog, audit_id) is not None


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for concurrent idempotency validation",
)
def test_concurrent_create_commands_commit_one_event() -> None:
    register_models()
    database = SessionAwareDatabase(os.environ["DATABASE_URL"])
    repository_a = AuditedSessionRepository(database)
    repository_b = AuditedSessionRepository(database)
    number = f"NXL-AUDIT-CONCURRENT-{uuid4()}"
    key = f"concurrent-create-{uuid4()}"
    occurred_at = datetime.now(UTC)
    payload = SessionCreate.model_validate(create_payload(number, occurred_at))
    barrier = Barrier(2)

    def execute(repository: AuditedSessionRepository):
        barrier.wait(timeout=10)
        return repository.create(payload, idempotency_key=key)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, (repository_a, repository_b)))

        assert {result.session.id for result in results}.__len__() == 1
        assert {result.event.id for result in results}.__len__() == 1
        assert sorted(result.replayed for result in results) == [False, True]

        with Session(database.engine) as db_session:
            session_id = results[0].session.id
            assert db_session.scalar(
                select(func.count())
                .select_from(SessionEvent)
                .where(
                    SessionEvent.session_id == session_id,
                    SessionEvent.event_type == "session_created",
                )
            ) == 1
            assert db_session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.session_id == session_id)
            ) == 1
            assert db_session.get(TestSession, session_id) is not None
    finally:
        database.dispose()
