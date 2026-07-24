from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app
from app.sessions.models import SessionStage, TestSession
from app.sessions.production_contract import PRODUCTION_CHANNELS


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'session-attribution.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def create_session(client: TestClient, *, number: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": f"create-{number}"},
        json={
            "session_number": number,
            "title": "Telemetry attribution test",
            "test_object": "K106",
            "node_id": "edge-01",
            "actor_id": "operator-1",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["session"]["id"])


def add_binding(
    client: TestClient,
    session_id: str,
    *,
    occurred_at: datetime,
) -> str:
    response = client.post(
        f"/api/v1/sessions/{session_id}/bindings",
        headers={"Idempotency-Key": f"binding-{session_id}"},
        json={
            "actor_id": "operator-1",
            "occurred_at": occurred_at.isoformat(),
            "node_id": "edge-01",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "metric": "temperature.probe",
            "unit": "degC",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["binding"]["id"])


def apply_production_bindings(
    client: TestClient,
    session_id: str,
    *,
    occurred_at: datetime,
) -> None:
    response = client.post(
        f"/api/v1/sessions/{session_id}/bindings/production",
        headers={"Idempotency-Key": f"production-{session_id}"},
        json={
            "actor_id": "operator-1",
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["bindings"]) == 34


def transition(
    client: TestClient,
    session_id: str,
    action: str,
    *,
    occurred_at: datetime,
) -> dict:
    response = client.post(
        f"/api/v1/sessions/{session_id}/{action}",
        headers={"Idempotency-Key": f"{action}-{session_id}-{occurred_at.isoformat()}"},
        json={
            "actor_id": "operator-1",
            "actor_source": "test",
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def event(
    *,
    captured_at: datetime,
    equipment_id: str = "K106",
    channel_id: str = "106-03",
    metric: str = "temperature.probe",
    unit: str = "degC",
    value: float = 4.2,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit=unit,
        quality="valid",
        source="test-source",
        equipment_id=equipment_id,
        channel_id=channel_id,
    )


def persist(client: TestClient, telemetry: TelemetryEvent) -> bool:
    return bool(
        client.app.state.database.persist(
            telemetry,
            telemetry.normalized_payload(),
        )
    )


def session_history(
    client: TestClient,
    session_id: str,
    *,
    from_at: datetime,
    to_at: datetime,
) -> list[dict]:
    response = client.get(
        f"/api/v1/sessions/{session_id}/telemetry/history",
        params={
            "from": from_at.isoformat(),
            "to": to_at.isoformat(),
            "limit": 200,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_start_pause_resume_and_completion_boundaries(tmp_path: Path) -> None:
    base = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
    start_at = base + timedelta(minutes=1)
    pause_at = base + timedelta(minutes=2)
    resume_at = base + timedelta(minutes=3)
    complete_at = base + timedelta(minutes=4)

    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-ATTR-001")
        binding_id = add_binding(client, session_id, occurred_at=base)
        transition(client, session_id, "prepare", occurred_at=base + timedelta(seconds=10))
        started = transition(client, session_id, "start", occurred_at=start_at)
        snapshot_id = started["session"]["active_config_snapshot_id"]

        before_start = event(captured_at=start_at - timedelta(microseconds=1))
        at_start = event(captured_at=start_at)
        during_pause = event(captured_at=pause_at + timedelta(seconds=1))
        after_resume = event(captured_at=resume_at + timedelta(seconds=1))
        before_complete = event(captured_at=complete_at - timedelta(microseconds=1))
        at_complete = event(captured_at=complete_at)

        assert persist(client, before_start) is True
        assert persist(client, at_start) is True
        transition(client, session_id, "pause", occurred_at=pause_at)
        assert persist(client, during_pause) is True
        transition(client, session_id, "resume", occurred_at=resume_at)
        assert persist(client, after_resume) is True
        assert persist(client, before_complete) is True
        transition(client, session_id, "complete", occurred_at=complete_at)
        assert persist(client, at_complete) is True

        items = session_history(
            client,
            session_id,
            from_at=base,
            to_at=base + timedelta(minutes=5),
        )
        assert {item["event_id"] for item in items} == {
            str(at_start.event_id),
            str(during_pause.event_id),
            str(after_resume.event_id),
            str(before_complete.event_id),
        }
        assert {item["binding_id"] for item in items} == {binding_id}
        assert {item["config_snapshot_id"] for item in items} == {snapshot_id}
        assert all(item["stage_id"] is None for item in items)

        regular = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(minutes=5)).isoformat(),
                "limit": 20,
            },
        )
        assert regular.status_code == 200, regular.text
        assert regular.json()["count"] == 6


def test_stage_attribution_changes_at_committed_transition(tmp_path: Path) -> None:
    base = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)
    start_at = base + timedelta(minutes=1)
    stage_change_at = base + timedelta(minutes=2)

    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-ATTR-002")
        add_binding(client, session_id, occurred_at=base)
        transition(client, session_id, "prepare", occurred_at=base + timedelta(seconds=10))
        transition(client, session_id, "start", occurred_at=start_at)

        first_stage_id = str(uuid4())
        second_stage_id = str(uuid4())
        first_stage = SessionStage(
            id=first_stage_id,
            session_id=session_id,
            sequence_index=0,
            stage_type="preparation",
            name="Preparation",
            entered_at=start_at,
            created_at=base,
        )
        second_stage = SessionStage(
            id=second_stage_id,
            session_id=session_id,
            sequence_index=1,
            stage_type="main_test",
            name="Main test",
            created_at=base,
        )
        with Session(client.app.state.database.engine) as db_session:
            with db_session.begin():
                db_session.add_all([first_stage, second_stage])
                record = db_session.get(TestSession, session_id)
                assert record is not None
                record.current_stage_id = first_stage_id

        before_change = event(
            captured_at=stage_change_at - timedelta(microseconds=1)
        )
        assert persist(client, before_change) is True

        with Session(client.app.state.database.engine) as db_session:
            with db_session.begin():
                stored_first = db_session.get(SessionStage, first_stage_id)
                stored_second = db_session.get(SessionStage, second_stage_id)
                record = db_session.get(TestSession, session_id)
                assert stored_first is not None
                assert stored_second is not None
                assert record is not None
                stored_first.exited_at = stage_change_at
                stored_second.entered_at = stage_change_at
                record.current_stage_id = second_stage_id

        at_change = event(captured_at=stage_change_at)
        assert persist(client, at_change) is True

        items = session_history(
            client,
            session_id,
            from_at=base,
            to_at=base + timedelta(minutes=3),
        )
        by_event = {item["event_id"]: item for item in items}
        assert by_event[str(before_change.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(at_change.event_id)]["stage_id"] == second_stage_id

        filtered = client.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(minutes=3)).isoformat(),
                "stage_id": second_stage_id,
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert [item["event_id"] for item in filtered.json()["items"]] == [
            str(at_change.event_id)
        ]


def test_complete_production_cycle_and_duplicate_are_attributed_once(
    tmp_path: Path,
) -> None:
    base = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    captured_at = base + timedelta(minutes=2)

    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-ATTR-003")
        apply_production_bindings(client, session_id, occurred_at=base)
        transition(client, session_id, "prepare", occurred_at=base + timedelta(seconds=10))
        started = transition(
            client,
            session_id,
            "start",
            occurred_at=base + timedelta(minutes=1),
        )
        snapshot_id = started["session"]["active_config_snapshot_id"]

        events: list[TelemetryEvent] = []
        for index, channel in enumerate(PRODUCTION_CHANNELS):
            telemetry = event(
                captured_at=captured_at,
                equipment_id=channel.equipment_id,
                channel_id=channel.channel_id,
                metric=channel.metric,
                unit=channel.unit,
                value=float(index + 1),
            )
            events.append(telemetry)
            assert persist(client, telemetry) is True

        assert persist(client, events[0]) is False
        items = session_history(
            client,
            session_id,
            from_at=base,
            to_at=base + timedelta(minutes=3),
        )
        assert len(items) == 34
        assert len({item["event_id"] for item in items}) == 34
        assert {item["config_snapshot_id"] for item in items} == {snapshot_id}
        assert {item["resolver_version"] for item in items} == {
            "snapshot-timeline-v1"
        }

        latest = client.get(
            f"/api/v1/sessions/{session_id}/telemetry/latest",
            params={"limit": 100},
        )
        assert latest.status_code == 200, latest.text
        assert latest.json()["count"] == 34


def test_unbound_telemetry_remains_valid_and_sessionless(tmp_path: Path) -> None:
    base = datetime(2026, 7, 24, 13, 0, tzinfo=UTC)

    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-ATTR-004")
        unbound = event(
            captured_at=base,
            equipment_id="K999",
            channel_id="999-01",
        )
        assert persist(client, unbound) is True
        assert client.app.state.database.context_for_event(str(unbound.event_id)) is None

        scoped = session_history(
            client,
            session_id,
            from_at=base - timedelta(minutes=1),
            to_at=base + timedelta(minutes=1),
        )
        assert scoped == []

        regular = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": (base - timedelta(minutes=1)).isoformat(),
                "to": (base + timedelta(minutes=1)).isoformat(),
            },
        )
        assert regular.status_code == 200, regular.text
        returned = regular.json()["items"][0]
        assert returned["event_id"] == str(unbound.event_id)
        assert returned["value"] == unbound.value
        assert returned["quality"] == unbound.quality
        returned_captured_at = datetime.fromisoformat(returned["captured_at"])
        if returned_captured_at.tzinfo is None:
            returned_captured_at = returned_captured_at.replace(tzinfo=UTC)
        assert returned_captured_at == unbound.captured_at
