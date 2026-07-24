from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'audit-validation.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def test_create_rejects_blank_actor_and_naive_timestamp(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        blank_actor = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": "blank-actor"},
            json={
                "session_number": "NXL-AUDIT-VALIDATION-001",
                "title": "Audit validation",
                "test_object": "K106",
                "actor_id": "   ",
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
        naive_timestamp = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": "naive-timestamp"},
            json={
                "session_number": "NXL-AUDIT-VALIDATION-002",
                "title": "Audit validation",
                "test_object": "K106",
                "actor_id": "operator-1",
                "occurred_at": "2026-07-24T16:00:00",
            },
        )

        assert blank_actor.status_code == 422, blank_actor.text
        assert naive_timestamp.status_code == 422, naive_timestamp.text


def test_stage_and_note_commands_reject_blank_required_text(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        blank_stage = client.post(
            "/api/v1/sessions/not-used/stages/advance",
            headers={"Idempotency-Key": "blank-stage"},
            json={
                "actor_id": "operator-1",
                "occurred_at": datetime.now(UTC).isoformat(),
                "sequence_index": 0,
                "stage_type": "preparation",
                "name": "   ",
            },
        )
        blank_note = client.post(
            "/api/v1/sessions/not-used/notes",
            headers={"Idempotency-Key": "blank-note"},
            json={
                "actor_id": "operator-1",
                "occurred_at": datetime.now(UTC).isoformat(),
                "body": "   ",
            },
        )

        assert blank_stage.status_code == 422, blank_stage.text
        assert blank_note.status_code == 422, blank_note.text
