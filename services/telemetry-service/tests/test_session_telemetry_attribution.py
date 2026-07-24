from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app
from app.sessions.production_contract import PRODUCTION_CHANNELS


def build_client(tmp_path: Path, name: str) -> tuple[TestClient, object]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / name}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        history_max_range_days=31,
        api_max_page_size=1000,
    )
    app = create_app(settings)
    return TestClient(app), app


def create_session(client: TestClient, number: str) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": f"create-{number}"},
        json={
            "session_number": number,
            "title": f"Telemetry attribution {number}",
            "test_object": "K106 display cabinet",
            "node_id": "edge-01",
            "actor_id": "operator-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session"]["id"]


def command(
    client: TestClient,
    session_id: str,
    action: str,
    *,
    key: str,
    occurred_at: datetime,
    reason: str | None = None,
) -> dict:
    payload: dict[str, str] = {
        "actor_id": "operator-1",
        "actor_source": "dashboard",
        "occurred_at": occurred_at.isoformat(),
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


def telemetry_event(
    *,
    captured_at: datetime,
    equipment_id: str = "K106",
    channel_id: str = "106-03",
    metric: str = "temperature.probe",
    unit: str = "degC",
    value: float = 4.0,
    source: str = "dixell-xjp60d",
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit=unit,
        quality="valid",
        source=source,
        equipment_id=equipment_id,
        channel_id=channel_id,
        alarm=None,
        raw_value=int(value * 10),
        raw_status=None,
    )


def test_attribution_follows_pause_stage_and_completion_boundaries(
    tmp_path: Path,
) -> None:
    client, app = build_client(tmp_path, "attribution-boundaries.db")
    base = datetime.now(UTC) + timedelta(seconds=1)

    with client:
        session_id = create_session(client, "NXL-M4-ATTR-001")
        bindings = client.post(
            f"/api/v1/sessions/{session_id}/bindings/production",
            headers={"Idempotency-Key": "attribution-production-bindings"},
            json={"actor_id": "operator-1"},
        )
        assert bindings.status_code == 201, bindings.text
        assert len(bindings.json()["bindings"]) == 34

        stage_plan_payload = {
            "actor_id": "engineer-1",
            "occurred_at": base.isoformat(),
            "stages": [
                {
                    "stage_type": "stabilization",
                    "name": "Stabilization",
                    "planned_duration_seconds": 900,
                },
                {
                    "stage_type": "main_test",
                    "name": "Main test",
                    "planned_duration_seconds": 3600,
                },
            ],
        }
        stage_plan = client.post(
            f"/api/v1/sessions/{session_id}/stages",
            headers={"Idempotency-Key": "stage-plan-1"},
            json=stage_plan_payload,
        )
        stage_plan_replay = client.post(
            f"/api/v1/sessions/{session_id}/stages",
            headers={"Idempotency-Key": "stage-plan-1"},
            json=stage_plan_payload,
        )
        assert stage_plan.status_code == 201, stage_plan.text
        assert stage_plan_replay.status_code == 201
        assert stage_plan_replay.json()["replayed"] is True
        stage_zero_id = stage_plan.json()["stages"][0]["id"]
        stage_one_id = stage_plan.json()["stages"][1]["id"]

        command(
            client,
            session_id,
            "prepare",
            key="prepare-attribution",
            occurred_at=base,
        )
        started = command(
            client,
            session_id,
            "start",
            key="start-attribution",
            occurred_at=base + timedelta(seconds=1),
        )
        assert started["event"]["payload"]["stage_id"] == stage_zero_id
        snapshot_id = started["event"]["payload"]["config_snapshot_id"]

        database = app.state.database
        running_stage_zero = telemetry_event(
            captured_at=base + timedelta(seconds=2),
            value=4.1,
        )
        assert database.persist(
            running_stage_zero,
            running_stage_zero.normalized_payload(),
        )

        command(
            client,
            session_id,
            "pause",
            key="pause-attribution",
            occurred_at=base + timedelta(seconds=3),
        )
        paused_stage_zero = telemetry_event(
            captured_at=base + timedelta(seconds=4),
            value=4.2,
        )
        assert database.persist(
            paused_stage_zero,
            paused_stage_zero.normalized_payload(),
        )

        blocked_advance = client.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            headers={"Idempotency-Key": "advance-while-paused"},
            json={
                "actor_id": "operator-1",
                "occurred_at": (base + timedelta(seconds=4)).isoformat(),
            },
        )
        assert blocked_advance.status_code == 409
        assert blocked_advance.json()["detail"]["code"] == (
            "invalid_stage_transition"
        )

        command(
            client,
            session_id,
            "resume",
            key="resume-attribution",
            occurred_at=base + timedelta(seconds=5),
        )
        advanced = client.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            headers={"Idempotency-Key": "advance-stage-one"},
            json={
                "actor_id": "operator-1",
                "occurred_at": (base + timedelta(seconds=6)).isoformat(),
                "reason": "Stabilization criteria satisfied",
            },
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["current_stage"]["id"] == stage_one_id

        running_stage_one = telemetry_event(
            captured_at=base + timedelta(seconds=7),
            value=4.3,
        )
        assert database.persist(
            running_stage_one,
            running_stage_one.normalized_payload(),
        )

        unbound = telemetry_event(
            captured_at=base + timedelta(seconds=7),
            channel_id="106-99",
            value=9.9,
        )
        assert database.persist(unbound, unbound.normalized_payload())

        command(
            client,
            session_id,
            "complete",
            key="complete-attribution",
            occurred_at=base + timedelta(seconds=8),
        )

        delayed_pre_completion = telemetry_event(
            captured_at=base + timedelta(seconds=7, milliseconds=500),
            value=4.4,
        )
        assert database.persist(
            delayed_pre_completion,
            delayed_pre_completion.normalized_payload(),
        )
        assert not database.persist(
            delayed_pre_completion,
            delayed_pre_completion.normalized_payload(),
        )

        post_completion = telemetry_event(
            captured_at=base + timedelta(seconds=9),
            value=4.5,
        )
        assert database.persist(
            post_completion,
            post_completion.normalized_payload(),
        )

        history = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(seconds=10)).isoformat(),
                "session_id": session_id,
                "limit": 100,
            },
        )
        assert history.status_code == 200, history.text
        items = history.json()["items"]
        assert history.json()["count"] == 4
        assert database.count_attributed_samples(session_id) == 4
        assert {item["config_snapshot_id"] for item in items} == {snapshot_id}
        assert {item["binding_id"] for item in items} == {
            bindings.json()["bindings"][0]["id"]
        }

        by_value = {item["value"]: item for item in items}
        assert by_value[4.1]["session_state"] == "running"
        assert by_value[4.1]["stage_id"] == stage_zero_id
        assert by_value[4.2]["session_state"] == "paused"
        assert by_value[4.2]["stage_id"] == stage_zero_id
        assert by_value[4.3]["session_state"] == "running"
        assert by_value[4.3]["stage_id"] == stage_one_id
        assert by_value[4.4]["session_state"] == "running"
        assert by_value[4.4]["stage_id"] == stage_one_id

        stage_zero_history = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(seconds=10)).isoformat(),
                "session_id": session_id,
                "stage_id": stage_zero_id,
            },
        )
        stage_one_history = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(seconds=10)).isoformat(),
                "session_id": session_id,
                "stage_id": stage_one_id,
            },
        )
        assert stage_zero_history.json()["count"] == 2
        assert stage_one_history.json()["count"] == 2

        latest = client.get(
            "/api/v1/telemetry/latest",
            params={"session_id": session_id},
        )
        assert latest.status_code == 200
        assert latest.json()["count"] == 1
        assert latest.json()["items"][0]["value"] == 4.4

        all_history = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(seconds=10)).isoformat(),
                "limit": 100,
            },
        )
        all_items = {item["event_id"]: item for item in all_history.json()["items"]}
        assert all_items[str(unbound.event_id)]["session_id"] is None
        assert all_items[str(post_completion.event_id)]["session_id"] is None
        assert all_items[str(running_stage_zero.event_id)]["raw_value"] == 41
        assert all_items[str(running_stage_zero.event_id)]["captured_at"] == (
            running_stage_zero.captured_at.isoformat()
        )


def test_complete_34_series_cycle_is_attributed_without_raw_rewrite(
    tmp_path: Path,
) -> None:
    client, app = build_client(tmp_path, "attribution-cycle.db")
    base = datetime.now(UTC) + timedelta(seconds=1)

    with client:
        session_id = create_session(client, "NXL-M4-ATTR-034")
        preset = client.post(
            f"/api/v1/sessions/{session_id}/bindings/production",
            headers={"Idempotency-Key": "production-cycle-bindings"},
            json={"actor_id": "operator-1"},
        )
        assert preset.status_code == 201, preset.text
        command(
            client,
            session_id,
            "prepare",
            key="prepare-cycle",
            occurred_at=base,
        )
        command(
            client,
            session_id,
            "start",
            key="start-cycle",
            occurred_at=base + timedelta(seconds=1),
        )

        database = app.state.database
        captured_at = base + timedelta(seconds=2)
        event_ids: set[str] = set()
        for index, specification in enumerate(PRODUCTION_CHANNELS):
            event = telemetry_event(
                captured_at=captured_at,
                equipment_id=specification.equipment_id,
                channel_id=specification.channel_id,
                metric=specification.metric,
                unit=specification.unit,
                value=float(index + 1),
                source=specification.device_type,
            )
            raw_payload = event.normalized_payload()
            assert database.persist(event, raw_payload)
            event_ids.add(str(event.event_id))

        assert len(event_ids) == 34
        assert database.count_samples() == 34
        assert database.count_attributed_samples(session_id) == 34

        latest = client.get(
            "/api/v1/telemetry/latest",
            params={"session_id": session_id, "limit": 100},
        )
        history = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(seconds=3)).isoformat(),
                "session_id": session_id,
                "limit": 100,
            },
        )
        assert latest.status_code == 200, latest.text
        assert history.status_code == 200, history.text
        assert latest.json()["count"] == 34
        assert history.json()["count"] == 34
        assert {item["event_id"] for item in history.json()["items"]} == event_ids
        assert all(item["session_id"] == session_id for item in history.json()["items"])
        assert all(item["config_snapshot_id"] for item in history.json()["items"])
        assert all(item["stage_id"] is None for item in history.json()["items"])
