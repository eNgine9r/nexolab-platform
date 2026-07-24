from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'sessions.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        cors_allowed_origins="http://127.0.0.1:3000",
    )
    return TestClient(create_app(settings))


def create_session(client: TestClient, *, number: str = "NXL-2026-001") -> dict:
    response = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": f"create-{number}"},
        json={
            "session_number": number,
            "title": "ISO 23953 refrigerated display cabinet",
            "test_object": "K106 display cabinet",
            "node_id": "edge-01",
            "customer": "NEXOLAB",
            "model": "K106",
            "serial_number": "K106-001",
            "standard": "ISO 23953",
            "method": "Temperature and energy performance",
            "operator_id": "operator-1",
            "responsible_engineer_id": "engineer-1",
            "metadata_payload": {"laboratory": "Laboratory 1"},
            "actor_id": "operator-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def transition(
    client: TestClient,
    session_id: str,
    action: str,
    *,
    key: str,
    reason: str | None = None,
) -> dict:
    payload: dict[str, str] = {
        "actor_id": "operator-1",
        "actor_source": "dashboard",
    }
    if reason is not None:
        payload["reason"] = reason

    response = client.post(
        f"/api/v1/sessions/{session_id}/{action}",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_list_get_and_patch_draft_session(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = create_session(client)
        session = created["session"]
        session_id = session["id"]

        assert created["replayed"] is False
        assert created["event"]["event_type"] == "session_created"
        assert session["state"] == "draft"
        assert session["node_id"] == "edge-01"
        assert session["lock_version"] == 1

        listed = client.get("/api/v1/sessions?state=draft&node_id=edge-01")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert listed.json()["items"][0]["id"] == session_id

        fetched = client.get(f"/api/v1/sessions/{session_id}")
        assert fetched.status_code == 200
        assert fetched.json()["session_number"] == "NXL-2026-001"

        patched = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={
                "title": "Updated laboratory session",
                "metadata_payload": {"laboratory": "Laboratory 2"},
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["title"] == "Updated laboratory session"
        assert patched.json()["lock_version"] == 2


def test_complete_lifecycle_and_event_order(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client)["session"]["id"]

        assert transition(
            client,
            session_id,
            "prepare",
            key="prepare-1",
        )["session"]["state"] == "ready"
        assert transition(
            client,
            session_id,
            "start",
            key="start-1",
        )["session"]["state"] == "running"
        assert transition(
            client,
            session_id,
            "pause",
            key="pause-1",
        )["session"]["state"] == "paused"
        assert transition(
            client,
            session_id,
            "resume",
            key="resume-1",
        )["session"]["state"] == "running"
        assert transition(
            client,
            session_id,
            "complete",
            key="complete-1",
        )["session"]["state"] == "completed"
        assert transition(
            client,
            session_id,
            "archive",
            key="archive-1",
        )["session"]["state"] == "archived"

        events = client.get(f"/api/v1/sessions/{session_id}/events")
        assert events.status_code == 200
        assert [item["event_type"] for item in events.json()["items"]] == [
            "session_created",
            "session_prepared",
            "session_started",
            "session_paused",
            "session_resumed",
            "session_completed",
            "session_archived",
        ]


def test_repeated_transition_returns_original_event_without_duplicate(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client)["session"]["id"]
        transition(client, session_id, "prepare", key="prepare-1")
        transition(client, session_id, "start", key="start-1")

        first = transition(client, session_id, "pause", key="pause-1")
        repeated = transition(client, session_id, "pause", key="pause-1")

        assert first["replayed"] is False
        assert repeated["replayed"] is True
        assert repeated["event"]["id"] == first["event"]["id"]
        assert repeated["session"]["state"] == "paused"

        events = client.get(f"/api/v1/sessions/{session_id}/events")
        assert events.status_code == 200
        assert [
            item["event_type"]
            for item in events.json()["items"]
            if item["event_type"] == "session_paused"
        ] == ["session_paused"]


def test_invalid_transition_returns_stable_domain_error(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client)["session"]["id"]

        response = client.post(
            f"/api/v1/sessions/{session_id}/start",
            headers={"Idempotency-Key": "start-before-prepare"},
            json={"actor_id": "operator-1"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "invalid_session_transition",
            "message": "cannot start a session in draft state",
            "current_state": "draft",
            "action": "start",
        }


def test_completed_session_rejects_generic_patch(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client)["session"]["id"]
        transition(client, session_id, "prepare", key="prepare-1")
        transition(client, session_id, "start", key="start-1")
        transition(client, session_id, "complete", key="complete-1")

        response = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"title": "Forbidden rewrite"},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "session_immutable"


def test_cancel_requires_reason_and_is_idempotent(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client)["session"]["id"]

        rejected = client.post(
            f"/api/v1/sessions/{session_id}/cancel",
            headers={"Idempotency-Key": "cancel-1"},
            json={"actor_id": "operator-1"},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "transition_reason_required"

        cancelled = transition(
            client,
            session_id,
            "cancel",
            key="cancel-1",
            reason="Test object was withdrawn",
        )
        replayed = transition(
            client,
            session_id,
            "cancel",
            key="cancel-1",
            reason="Test object was withdrawn",
        )

        assert cancelled["session"]["state"] == "cancelled"
        assert replayed["replayed"] is True
        assert replayed["event"]["id"] == cancelled["event"]["id"]


def test_session_number_conflict_and_not_found_are_typed(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        create_session(client)

        duplicate = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": "duplicate-create"},
            json={
                "session_number": "NXL-2026-001",
                "title": "Duplicate",
                "test_object": "Duplicate object",
                "actor_id": "operator-1",
            },
        )
        missing = client.get("/api/v1/sessions/missing-session")

        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "session_number_conflict"
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "session_not_found"


def test_dashboard_origin_can_preflight_session_mutations(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.options(
            "/api/v1/sessions",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,idempotency-key",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == (
            "http://127.0.0.1:3000"
        )
        assert "POST" in response.headers["access-control-allow-methods"]
