from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.models import (
    AlertEvidenceSample,
    AlertInstance,
    AlertRuleVersion,
)
from app.config import Settings
from app.main import create_app


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def build_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=f"sqlite:///{tmp_path / 'alerts-extended.db'}",
                auto_create_schema=True,
                mqtt_enabled=False,
                retention_enabled=False,
            )
        )
    )


def rule_payload(*, threshold: float = 8.0, enabled: bool | None = None) -> dict:
    payload = {
        "name": "Versioned product temperature",
        "description": "ISO 23953 product package limit",
        "severity": "critical",
        "node_id": "edge-01",
        "equipment_id": "K106",
        "channel_id": "106-03",
        "metric": "temperature.probe",
        "condition": "threshold_high",
        "trigger_threshold": threshold,
        "clear_threshold": threshold - 1.0,
        "minimum_duration_seconds": 60,
        "clear_duration_seconds": 30,
        "debounce_seconds": 10,
        "cooldown_seconds": 120,
        "configuration": {"standard": "ISO 23953"},
    }
    if enabled is not None:
        payload["enabled"] = enabled
    return payload


def create_rule(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/alerts/rules",
        headers={"X-Organization-ID": ORGANIZATION_ID},
        json=rule_payload(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_alert_with_evidence(client: TestClient, rule: dict) -> str:
    now = datetime.now(UTC)
    alert_id = str(uuid4())
    event_id = str(uuid4())
    with Session(client.app.state.database.engine) as session:
        with session.begin():
            session.add(
                AlertInstance(
                    id=alert_id,
                    organization_id=ORGANIZATION_ID,
                    rule_id=rule["id"],
                    rule_version_id=rule["version"]["id"],
                    resource_key="org|-|edge-01|K106|106-03|temperature.probe",
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
                    first_event_id=event_id,
                    last_event_id=event_id,
                    context={"unit": "degC"},
                    triggered_at=now,
                    created_at=now,
                    updated_at=now,
                    lock_version=1,
                )
            )
            session.add(
                AlertEvidenceSample(
                    id=str(uuid4()),
                    alert_id=alert_id,
                    event_id=event_id,
                    captured_at=now,
                    value=9.4,
                    threshold=8.0,
                    deviation=1.4,
                    payload={"reason": "triggered"},
                    created_at=now,
                )
            )
    return alert_id


def test_rule_replace_creates_immutable_revision(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = create_rule(client)
        replaced = client.put(
            f"/api/v1/alerts/rules/{created['id']}",
            headers={"X-Organization-ID": ORGANIZATION_ID},
            json=rule_payload(threshold=9.0, enabled=False),
        )
        assert replaced.status_code == 200, replaced.text
        body = replaced.json()
        assert body["current_version"] == 2
        assert body["enabled"] is False
        assert body["version"]["version"] == 2
        assert body["version"]["trigger_threshold"] == 9.0
        assert body["version"]["id"] != created["version"]["id"]

        with Session(client.app.state.database.engine) as session:
            versions = list(
                session.scalars(
                    select(AlertRuleVersion)
                    .where(AlertRuleVersion.rule_id == created["id"])
                    .order_by(AlertRuleVersion.version)
                )
            )
            assert [item.trigger_threshold for item in versions] == [8.0, 9.0]
            assert session.scalar(
                select(func.count())
                .select_from(AlertRuleVersion)
                .where(AlertRuleVersion.rule_id == created["id"])
            ) == 2


def test_latest_history_and_evidence_are_organization_scoped(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule = create_rule(client)
        alert_id = seed_alert_with_evidence(client, rule)

        latest = client.get(
            "/api/v1/alerts/latest",
            headers={"X-Organization-ID": ORGANIZATION_ID},
        )
        history = client.get(
            "/api/v1/alerts/history",
            headers={"X-Organization-ID": ORGANIZATION_ID},
        )
        evidence = client.get(
            f"/api/v1/alerts/{alert_id}/evidence",
            headers={"X-Organization-ID": ORGANIZATION_ID},
        )
        assert latest.status_code == 200
        assert latest.json()["count"] == 1
        assert history.status_code == 200
        assert history.json()["count"] == 0
        assert evidence.status_code == 200
        assert evidence.json()["count"] == 1
        assert evidence.json()["items"][0]["deviation"] == 1.4

        foreign = client.get(
            f"/api/v1/alerts/{alert_id}/evidence",
            headers={
                "X-Organization-ID": "00000000-0000-0000-0000-000000000002"
            },
        )
        assert foreign.status_code == 404

        now = datetime.now(UTC)
        with Session(client.app.state.database.engine) as session:
            with session.begin():
                alert = session.get(AlertInstance, alert_id)
                assert alert is not None
                alert.state = "closed"
                alert.closed_at = now
                alert.updated_at = now

        latest_after_close = client.get(
            "/api/v1/alerts/latest",
            headers={"X-Organization-ID": ORGANIZATION_ID},
        )
        history_after_close = client.get(
            "/api/v1/alerts/history",
            headers={"X-Organization-ID": ORGANIZATION_ID},
        )
        assert latest_after_close.json()["count"] == 0
        assert history_after_close.json()["count"] == 1
