from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app
from app.sessions.production_contract import PRODUCTION_CHANNELS


def build_client(database_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=f"sqlite:///{database_path}",
                auto_create_schema=True,
                mqtt_enabled=False,
                retention_enabled=False,
            )
        )
    )


def command(at: datetime, reason: str) -> dict[str, object]:
    return {
        "actor_id": "operator-recovery",
        "actor_source": "m4-recovery-test",
        "occurred_at": at.isoformat(),
        "reason": reason,
    }


def post(
    client: TestClient,
    path: str,
    *,
    key: str,
    payload: dict[str, object],
    status: int = 200,
) -> dict:
    response = client.post(
        path,
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == status, response.text
    return response.json()


def get(client: TestClient, path: str, **params: object) -> object:
    response = client.get(path, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


def telemetry(
    *,
    captured_at: datetime,
    equipment_id: str,
    channel_id: str,
    metric: str,
    unit: str | None,
    value: float,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit=unit,
        quality="valid",
        source="m4-recovery-test",
        equipment_id=equipment_id,
        channel_id=channel_id,
    )


def persist(client: TestClient, event: TelemetryEvent) -> None:
    assert client.app.state.database.persist(
        event,
        event.normalized_payload(),
    ) is True


def persist_cycle(
    client: TestClient,
    *,
    captured_at: datetime,
    offset: float,
) -> list[TelemetryEvent]:
    events: list[TelemetryEvent] = []
    for index, channel in enumerate(PRODUCTION_CHANNELS):
        event = telemetry(
            captured_at=captured_at,
            equipment_id=channel.equipment_id,
            channel_id=channel.channel_id,
            metric=channel.metric,
            unit=channel.unit,
            value=offset + index,
        )
        persist(client, event)
        events.append(event)
    return events


def evidence(client: TestClient, session_id: str, base: datetime) -> dict[str, object]:
    return {
        "session": get(client, f"/api/v1/sessions/{session_id}"),
        "configuration": get(
            client,
            f"/api/v1/sessions/{session_id}/configuration",
        ),
        "events": get(
            client,
            f"/api/v1/sessions/{session_id}/events",
            limit=500,
        ),
        "audit": get(
            client,
            f"/api/v1/sessions/{session_id}/audit",
            limit=500,
        ),
        "stages": get(client, f"/api/v1/sessions/{session_id}/stages"),
        "history": get(
            client,
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{
                "from": base.isoformat(),
                "to": (base + timedelta(minutes=2)).isoformat(),
                "limit": 200,
            },
        ),
    }


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_running_session_context_and_history_survive_two_restarts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m4-session-recovery.db"
    base = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    pause_payload = command(
        base + timedelta(seconds=50),
        "Pause workflow while telemetry continues",
    )
    complete_payload = command(
        base + timedelta(seconds=90),
        "Complete recovery acceptance session",
    )

    with build_client(database_path) as client:
        created = post(
            client,
            "/api/v1/sessions",
            key="m4-recovery-create",
            status=201,
            payload={
                "session_number": "NXL-M4-RECOVERY-001",
                "title": "M4 restart and offline recovery",
                "test_object": "K106 refrigerated display cabinet",
                "node_id": "edge-01",
                "customer": "NEXOLAB",
                "standard": "ISO 23953",
                "method": "Restart and offline acceptance",
                **command(base, "Create recovery acceptance session"),
            },
        )
        session_id = created["session"]["id"]

        bindings = post(
            client,
            f"/api/v1/sessions/{session_id}/bindings/production",
            key="m4-recovery-bindings",
            status=201,
            payload={
                **command(
                    base + timedelta(seconds=1),
                    "Assign validated production channels",
                ),
                "binding_metadata": {"acceptance": "m4-gate-82"},
            },
        )
        assert bindings["expected_series_count"] == 34
        assert len(bindings["bindings"]) == 34

        limits = post(
            client,
            f"/api/v1/sessions/{session_id}/limits",
            key="m4-recovery-limits-v1",
            status=201,
            payload={
                **command(
                    base + timedelta(seconds=2),
                    "Create acceptance limits",
                ),
                "limits": [
                    {
                        "metric": "temperature.probe",
                        "unit": "degC",
                        "lower_limit": -5.0,
                        "upper_limit": 8.0,
                    },
                    {
                        "metric": "electrical.power.active",
                        "unit": "W",
                        "upper_limit": 5000.0,
                    },
                ],
            },
        )
        assert limits["version"] == 1

        post(
            client,
            f"/api/v1/sessions/{session_id}/prepare",
            key="m4-recovery-prepare",
            payload=command(
                base + timedelta(seconds=10),
                "Prepare acceptance session",
            ),
        )
        started = post(
            client,
            f"/api/v1/sessions/{session_id}/start",
            key="m4-recovery-start",
            payload=command(
                base + timedelta(seconds=20),
                "Start acceptance session",
            ),
        )
        snapshot_id = started["session"]["active_config_snapshot_id"]
        assert snapshot_id

        stage_zero = post(
            client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="m4-recovery-stage-0",
            status=201,
            payload={
                **command(
                    base + timedelta(seconds=30),
                    "Enter stabilization stage",
                ),
                "sequence_index": 0,
                "stage_type": "stabilization",
                "name": "Stabilization",
            },
        )
        first_stage_id = stage_zero["stage"]["id"]
        first_cycle = persist_cycle(
            client,
            captured_at=base + timedelta(seconds=40),
            offset=100.0,
        )

        paused = post(
            client,
            f"/api/v1/sessions/{session_id}/pause",
            key="m4-recovery-pause",
            payload=pause_payload,
        )
        assert paused["session"]["state"] == "paused"
        paused_cycle = persist_cycle(
            client,
            captured_at=base + timedelta(seconds=60),
            offset=200.0,
        )

    with build_client(database_path) as client:
        restored = get(client, f"/api/v1/sessions/{session_id}")
        assert restored["state"] == "paused"
        assert restored["active_config_snapshot_id"] == snapshot_id
        assert restored["current_stage_id"] == first_stage_id

        replayed_pause = post(
            client,
            f"/api/v1/sessions/{session_id}/pause",
            key="m4-recovery-pause",
            payload=pause_payload,
        )
        assert replayed_pause["replayed"] is True
        assert replayed_pause["event"]["id"] == paused["event"]["id"]

        delayed = telemetry(
            captured_at=base + timedelta(seconds=55),
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            value=4.7,
        )
        persist(client, delayed)

        post(
            client,
            f"/api/v1/sessions/{session_id}/resume",
            key="m4-recovery-resume",
            payload=command(
                base + timedelta(seconds=70),
                "Resume after application restart",
            ),
        )
        stage_one = post(
            client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="m4-recovery-stage-1",
            status=201,
            payload={
                **command(
                    base + timedelta(seconds=80),
                    "Enter main test at polling boundary",
                ),
                "sequence_index": 1,
                "stage_type": "main_test",
                "name": "Main test",
            },
        )
        second_stage_id = stage_one["stage"]["id"]

        before_boundary = telemetry(
            captured_at=base + timedelta(seconds=80, microseconds=-1),
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            value=5.0,
        )
        at_boundary = telemetry(
            captured_at=base + timedelta(seconds=80),
            equipment_id="K106",
            channel_id="106-04",
            metric="temperature.probe",
            unit="degC",
            value=5.1,
        )
        persist(client, before_boundary)
        persist(client, at_boundary)

        completed = post(
            client,
            f"/api/v1/sessions/{session_id}/complete",
            key="m4-recovery-complete",
            payload=complete_payload,
        )
        assert completed["session"]["state"] == "completed"

        before_restart = evidence(client, session_id, base)
        history = before_restart["history"]
        assert history["count"] == 71
        by_event = {item["event_id"]: item for item in history["items"]}
        for event in [*first_cycle, *paused_cycle]:
            assert by_event[str(event.event_id)]["config_snapshot_id"] == snapshot_id
        for event in paused_cycle:
            assert by_event[str(event.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(delayed.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(before_boundary.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(at_boundary.event_id)]["stage_id"] == second_stage_id

    with build_client(database_path) as client:
        replayed_complete = post(
            client,
            f"/api/v1/sessions/{session_id}/complete",
            key="m4-recovery-complete",
            payload=complete_payload,
        )
        assert replayed_complete["replayed"] is True
        assert replayed_complete["event"]["id"] == completed["event"]["id"]

        rejected = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"title": "Forbidden post-restart mutation"},
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["code"] == "session_immutable"

        after_restart = evidence(client, session_id, base)
        assert canonical(after_restart) == canonical(before_restart)
        assert after_restart["events"]["count"] == 10
        assert after_restart["audit"]["count"] == 10
