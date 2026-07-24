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
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


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


def actor_command(occurred_at: datetime, reason: str) -> dict[str, object]:
    return {
        "actor_id": "operator-recovery",
        "actor_source": "m4-recovery-test",
        "occurred_at": occurred_at.isoformat(),
        "reason": reason,
    }


def persist(client: TestClient, event: TelemetryEvent) -> bool:
    return bool(
        client.app.state.database.persist(
            event,
            event.normalized_payload(),
        )
    )


def telemetry_event(
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


def persist_production_cycle(
    client: TestClient,
    *,
    captured_at: datetime,
    value_offset: float,
) -> list[TelemetryEvent]:
    events: list[TelemetryEvent] = []
    for index, channel in enumerate(PRODUCTION_CHANNELS):
        event = telemetry_event(
            captured_at=captured_at,
            equipment_id=channel.equipment_id,
            channel_id=channel.channel_id,
            metric=channel.metric,
            unit=channel.unit,
            value=value_offset + index,
        )
        assert persist(client, event) is True
        events.append(event)
    return events


def get_json(client: TestClient, path: str, **params: object) -> object:
    response = client.get(path, params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_running_session_context_and_history_survive_two_restarts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m4-session-recovery.db"
    base = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    create_payload = {
        "session_number": "NXL-M4-RECOVERY-001",
        "title": "M4 restart and offline recovery",
        "test_object": "K106 refrigerated display cabinet",
        "node_id": "edge-01",
        "customer": "NEXOLAB",
        "standard": "ISO 23953",
        "method": "Restart and offline acceptance",
        **actor_command(base, "Create recovery acceptance session"),
    }
    pause_payload = actor_command(base + timedelta(seconds=50), "Pause workflow while telemetry continues")
    complete_payload = actor_command(base + timedelta(seconds=90), "Complete recovery acceptance session")

    with build_client(database_path) as first_client:
        created = post_command(
            first_client,
            "/api/v1/sessions",
            key="m4-recovery-create",
            payload=create_payload,
            expected_status=201,
        )
        session_id = created["session"]["id"]

        bindings = post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/bindings/production",
            key="m4-recovery-production-bindings",
            payload={
                **actor_command(base + timedelta(seconds=1), "Assign validated production channels"),
                "binding_metadata": {"acceptance": "m4-gate-82"},
            },
            expected_status=201,
        )
        assert bindings["expected_series_count"] == 34
        assert len(bindings["bindings"]) == 34

        limits = post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/limits",
            key="m4-recovery-limits-v1",
            payload={
                **actor_command(base + timedelta(seconds=2), "Create acceptance limits"),
                "limits": [
                    {
                        "metric": "temperature.probe",
                        "unit": "degC",
                        "lower_limit": -5.0,
                        "upper_limit": 8.0,
                        "hysteresis": 0.5,
                        "duration_seconds": 60,
                    },
                    {
                        "metric": "electrical.power.active",
                        "unit": "W",
                        "upper_limit": 5000.0,
                    },
                ],
            },
            expected_status=201,
        )
        assert limits["version"] == 1

        post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/prepare",
            key="m4-recovery-prepare",
            payload=actor_command(base + timedelta(seconds=10), "Prepare acceptance session"),
        )
        started = post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/start",
            key="m4-recovery-start",
            payload=actor_command(base + timedelta(seconds=20), "Start acceptance session"),
        )
        snapshot_id = started["session"]["active_config_snapshot_id"]
        assert snapshot_id

        first_stage = post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="m4-recovery-stage-0",
            payload={
                **actor_command(base + timedelta(seconds=30), "Enter stabilization stage"),
                "sequence_index": 0,
                "stage_type": "stabilization",
                "name": "Stabilization",
            },
            expected_status=201,
        )
        first_stage_id = first_stage["stage"]["id"]

        first_cycle = persist_production_cycle(
            first_client,
            captured_at=base + timedelta(seconds=40),
            value_offset=100.0,
        )

        paused = post_command(
            first_client,
            f"/api/v1/sessions/{session_id}/pause",
            key="m4-recovery-pause",
            payload=pause_payload,
        )
        assert paused["session"]["state"] == "paused"

        paused_cycle = persist_production_cycle(
            first_client,
            captured_at=base + timedelta(seconds=60),
            value_offset=200.0,
        )

    with build_client(database_path) as restarted_client:
        restarted_session = get_json(restarted_client, f"/api/v1/sessions/{session_id}")
        assert restarted_session["state"] == "paused"
        assert restarted_session["active_config_snapshot_id"] == snapshot_id
        assert restarted_session["current_stage_id"] == first_stage_id

        replayed_pause = post_command(
            restarted_client,
            f"/api/v1/sessions/{session_id}/pause",
            key="m4-recovery-pause",
            payload=pause_payload,
        )
        assert replayed_pause["replayed"] is True
        assert replayed_pause["event"]["id"] == paused["event"]["id"]

        delayed_during_pause = telemetry_event(
            captured_at=base + timedelta(seconds=55),
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            value=4.7,
        )
        assert persist(restarted_client, delayed_during_pause) is True

        post_command(
            restarted_client,
            f"/api/v1/sessions/{session_id}/resume",
            key="m4-recovery-resume",
            payload=actor_command(base + timedelta(seconds=70), "Resume after application restart"),
        )

        second_stage = post_command(
            restarted_client,
            f"/api/v1/sessions/{session_id}/stages/advance",
            key="m4-recovery-stage-1",
            payload={
                **actor_command(base + timedelta(seconds=80), "Enter main test at polling boundary"),
                "sequence_index": 1,
                "stage_type": "main_test",
                "name": "Main test",
            },
            expected_status=201,
        )
        second_stage_id = second_stage["stage"]["id"]

        before_stage_boundary = telemetry_event(
            captured_at=base + timedelta(seconds=80, microseconds=-1),
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            value=5.0,
        )
        at_stage_boundary = telemetry_event(
            captured_at=base + timedelta(seconds=80),
            equipment_id="K106",
            channel_id="106-04",
            metric="temperature.probe",
            unit="degC",
            value=5.1,
        )
        assert persist(restarted_client, before_stage_boundary) is True
        assert persist(restarted_client, at_stage_boundary) is True

        completed = post_command(
            restarted_client,
            f"/api/v1/sessions/{session_id}/complete",
            key="m4-recovery-complete",
            payload=complete_payload,
        )
        assert completed["session"]["state"] == "completed"

        history = get_json(
            restarted_client,
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{
                "from": base.isoformat(),
                "to": (base + timedelta(minutes=2)).isoformat(),
                "limit": 200,
            },
        )
        assert history["count"] == 71
        by_event = {item["event_id"]: item for item in history["items"]}

        first_and_paused_ids = {
            str(event.event_id) for event in [*first_cycle, *paused_cycle]
        }
        assert first_and_paused_ids <= set(by_event)
        assert {
            by_event[str(event.event_id)]["config_snapshot_id"]
            for event in [*first_cycle, *paused_cycle]
        } == {snapshot_id}
        assert {
            by_event[str(event.event_id)]["stage_id"]
            for event in paused_cycle
        } == {first_stage_id}
        assert by_event[str(delayed_during_pause.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(before_stage_boundary.event_id)]["stage_id"] == first_stage_id
        assert by_event[str(at_stage_boundary.event_id)]["stage_id"] == second_stage_id

        evidence_before_second_restart = {
            "session": get_json(restarted_client, f"/api/v1/sessions/{session_id}"),
            "configuration": get_json(
                restarted_client,
                f"/api/v1/sessions/{session_id}/configuration",
            ),
            "events": get_json(restarted_client, f"/api/v1/sessions/{session_id}/events", limit=500),
            "audit": get_json(restarted_client, f"/api/v1/sessions/{session_id}/audit", limit=500),
            "stages": get_json(restarted_client, f"/api/v1/sessions/{session_id}/stages"),
            "history": history,
        }

    with build_client(database_path) as second_restart_client:
        replayed_complete = post_command(
            second_restart_client,
            f"/api/v1/sessions/{session_id}/complete",
            key="m4-recovery-complete",
            payload=complete_payload,
        )
        assert replayed_complete["replayed"] is True
        assert replayed_complete["event"]["id"] == completed["event"]["id"]

        rejected_patch = second_restart_client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"title": "Forbidden post-restart mutation"},
        )
        assert rejected_patch.status_code == 409, rejected_patch.text
        assert rejected_patch.json()["detail"]["code"] == "session_immutable"

        evidence_after_second_restart = {
            "session": get_json(second_restart_client, f"/api/v1/sessions/{session_id}"),
            "configuration": get_json(
                second_restart_client,
                f"/api/v1/sessions/{session_id}/configuration",
            ),
            "events": get_json(second_restart_client, f"/api/v1/sessions/{session_id}/events", limit=500),
            "audit": get_json(second_restart_client, f"/api/v1/sessions/{session_id}/audit", limit=500),
            "stages": get_json(second_restart_client, f"/api/v1/sessions/{session_id}/stages"),
            "history": get_json(
                second_restart_client,
                f"/api/v1/sessions/{session_id}/telemetry/history",
                **{
                    "from": base.isoformat(),
                    "to": (base + timedelta(minutes=2)).isoformat(),
                    "limit": 200,
                },
            ),
        }

        assert stable_json(evidence_after_second_restart) == stable_json(
            evidence_before_second_restart
        )
        assert evidence_after_second_restart["events"]["count"] == 9
        assert evidence_after_second_restart["audit"]["count"] == 9
