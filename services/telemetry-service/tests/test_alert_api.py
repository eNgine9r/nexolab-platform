from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance, AlertTransition
from app.config import Settings
from app.main import create_app


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'alerts.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def headers(organization_id: str = ORGANIZATION_A) -> dict[str, str]:
    return {"X-Organization-ID": organization_id}


def create_rule(
    client: TestClient,
    *,
    organization_id: str = ORGANIZATION_A,
    name: str = "High product temperature",
) -> dict:
    response = client.post(
        "/api/v1/alerts/rules",
        headers=headers(organization_id),
        json={
            "name": name,
            "severity": "critical",
            "node_id": "edge-01",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "metric": "temperature.probe",
            "condition": "threshold_high",
            "trigger_threshold": 8.0,
            "clear_threshold": 7.0,
            "minimum_duration_seconds": 60,
            "clear_duration_seconds": 30,
            "debounce_seconds": 10,
            "cooldown_seconds": 120,
            "configuration": {"standard": "ISO 23953"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_alert(client: TestClient, rule: dict) -> str:
    alert_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(client.app.state.database.engine) as session:
        with session.begin():
            session.add(
                AlertInstance(
                    id=alert_id,
                    organization_id=rule["organization_id"],
                    rule_id=rule["id"],
                    rule_version_id=rule["version"]["id"],
                    resource_key="edge-01|K106|106-03|temperature.probe",
                    node_id="edge-01",
                    equipment_id="K106",
                    channel_id="106-03",
                    metric="temperature.probe",
                    state="active",
                    severity="critical",
                    trigger_value=9.4,
                    trigger_threshold=8.0,
                    clear_threshold=7.0,
                    maximum_deviation=1.4,
                    first_event_id=str(uuid4()),
                    last_event_id=str(uuid4()),
                    context={"source": "test"},
                    triggered_at=now,
                    created_at=now,
                    updated_at=now,
                    lock_version=1,
                )
            )
    return alert_id


def test_rule_create_list_get_and_organization_isolation(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule_a = create_rule(client)
        rule_b = create_rule(
            client,
            organization_id=ORGANIZATION_B,
            name="High product temperature",
        )

        assert rule_a["organization_id"] == ORGANIZATION_A
        assert rule_b["organization_id"] == ORGANIZATION_B
        assert rule_a["id"] != rule_b["id"]
        assert rule_a["version"]["trigger_threshold"] == 8.0

        list_a = client.get("/api/v1/alerts/rules", headers=headers())
        list_b = client.get(
            "/api/v1/alerts/rules",
            headers=headers(ORGANIZATION_B),
        )
        assert list_a.status_code == 200
        assert list_b.status_code == 200
        assert [item["id"] for item in list_a.json()["items"]] == [rule_a["id"]]
        assert [item["id"] for item in list_b.json()["items"]] == [rule_b["id"]]

        foreign = client.get(
            f"/api/v1/alerts/rules/{rule_a['id']}",
            headers=headers(ORGANIZATION_B),
        )
        assert foreign.status_code == 404
        assert foreign.json()["detail"]["code"] == "alert_rule_not_found"


def test_acknowledge_is_idempotent_and_actor_is_server_derived(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule = create_rule(client)
        alert_id = seed_alert(client, rule)

        first = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            headers={**headers(), "Idempotency-Key": "ack-1"},
            json={"reason": "Equipment inspected"},
        )
        repeated = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            headers={**headers(), "Idempotency-Key": "ack-1"},
            json={"reason": "Equipment inspected"},
        )
        assert first.status_code == 200, first.text
        assert repeated.status_code == 200, repeated.text
        assert first.json()["alert"]["state"] == "acknowledged"
        assert first.json()["replayed"] is False
        assert repeated.json()["replayed"] is True
        assert repeated.json()["transition"]["id"] == first.json()["transition"]["id"]
        assert first.json()["transition"]["actor_id"] == "development-system"
        assert first.json()["transition"]["actor_source"] == "disabled"

        second_key = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            headers={**headers(), "Idempotency-Key": "ack-2"},
            json={"reason": "Duplicate operator command"},
        )
        assert second_key.status_code == 409
        assert second_key.json()["detail"]["code"] == "alert_conflict"

        with Session(client.app.state.database.engine) as session:
            transitions = list(
                session.scalars(
                    select(AlertTransition).where(
                        AlertTransition.alert_id == alert_id
                    )
                )
            )
            assert len(transitions) == 1


def test_close_requires_resolved_state_and_replays(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule = create_rule(client)
        alert_id = seed_alert(client, rule)

        rejected = client.post(
            f"/api/v1/alerts/{alert_id}/close",
            headers={**headers(), "Idempotency-Key": "close-1"},
            json={"reason": "Condition is still active"},
        )
        assert rejected.status_code == 409

        now = datetime.now(UTC)
        with Session(client.app.state.database.engine) as session:
            with session.begin():
                alert = session.get(AlertInstance, alert_id)
                assert alert is not None
                alert.state = "resolved"
                alert.resolved_at = now
                alert.updated_at = now

        closed = client.post(
            f"/api/v1/alerts/{alert_id}/close",
            headers={**headers(), "Idempotency-Key": "close-1"},
            json={"reason": "Verified stable clear condition"},
        )
        replayed = client.post(
            f"/api/v1/alerts/{alert_id}/close",
            headers={**headers(), "Idempotency-Key": "close-1"},
            json={"reason": "Verified stable clear condition"},
        )
        assert closed.status_code == 200, closed.text
        assert replayed.status_code == 200, replayed.text
        assert closed.json()["alert"]["state"] == "closed"
        assert replayed.json()["replayed"] is True


def test_invalid_hysteresis_is_rejected_at_api_boundary(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/alerts/rules",
            headers=headers(),
            json={
                "name": "Invalid rule",
                "severity": "warning",
                "metric": "temperature.probe",
                "condition": "threshold_high",
                "trigger_threshold": 8.0,
                "clear_threshold": 9.0,
            },
        )
        assert response.status_code == 422
