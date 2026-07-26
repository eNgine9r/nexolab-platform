from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.domain import AlertEvaluationDecision
from app.alerts.models import (
    AlertEvaluationState,
    AlertEvidenceSample,
    AlertInstance,
    AlertTransition,
)
from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'alert-processor.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def create_rule(
    client: TestClient,
    *,
    minimum_duration_seconds: int = 0,
    clear_duration_seconds: int = 30,
) -> dict:
    response = client.post(
        "/api/v1/alerts/rules",
        json={
            "name": f"High temperature {uuid4()}",
            "severity": "critical",
            "node_id": "edge-01",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "metric": "temperature.probe",
            "condition": "threshold_high",
            "trigger_threshold": 8.0,
            "clear_threshold": 7.0,
            "minimum_duration_seconds": minimum_duration_seconds,
            "clear_duration_seconds": clear_duration_seconds,
            "cooldown_seconds": 120,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def telemetry(
    captured_at: datetime,
    value: float,
    *,
    event_id: str | None = None,
) -> tuple[TelemetryEvent, dict]:
    event = TelemetryEvent(
        event_id=event_id or uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=value,
        unit="degC",
        quality="valid",
        source="processor-test",
        equipment_id="K106",
        channel_id="106-03",
    )
    payload = event.normalized_payload()
    payload["organization_id"] = ORGANIZATION_ID
    return event, payload


def persist_and_process(
    client: TestClient,
    captured_at: datetime,
    value: float,
) -> tuple[TelemetryEvent, object]:
    event, payload = telemetry(captured_at, value)
    assert client.app.state.database.persist(event, payload) is True
    return event, client.app.state.alert_processor.process_payload(payload)


def test_sustained_rule_trigger_is_idempotent(tmp_path: Path) -> None:
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    with build_client(tmp_path) as client:
        create_rule(client, minimum_duration_seconds=60)

        first_event, first = persist_and_process(client, base, 8.5)
        assert first.decisions == (
            AlertEvaluationDecision.START_TRIGGER_PENDING,
        )

        second_event, triggered = persist_and_process(
            client,
            base + timedelta(seconds=60),
            9.2,
        )
        assert triggered.decisions == (AlertEvaluationDecision.TRIGGER,)

        duplicate = client.app.state.alert_processor.process_payload(
            {
                **second_event.normalized_payload(),
                "organization_id": ORGANIZATION_ID,
            }
        )
        assert duplicate.decisions == (
            AlertEvaluationDecision.IGNORE_DUPLICATE,
        )

        listed = client.get("/api/v1/alerts")
        assert listed.status_code == 200, listed.text
        assert listed.json()["count"] == 1
        alert = listed.json()["items"][0]
        assert alert["state"] == "active"
        assert alert["first_event_id"] == str(second_event.event_id)
        assert alert["maximum_deviation"] == 1.2

        with Session(client.app.state.database.engine) as session:
            state = session.scalar(select(AlertEvaluationState))
            assert state is not None
            assert state.last_event_id == str(second_event.event_id)
            assert state.active_alert_id == alert["id"]
            assert session.scalar(
                select(AlertEvidenceSample).where(
                    AlertEvidenceSample.alert_id == alert["id"]
                )
            ) is not None
            transitions = list(
                session.scalars(
                    select(AlertTransition).where(
                        AlertTransition.alert_id == alert["id"]
                    )
                )
            )
            assert [item.event_type for item in transitions] == ["alert_triggered"]
        assert first_event.event_id != second_event.event_id


def test_acknowledged_alert_resolves_after_clear_duration(tmp_path: Path) -> None:
    base = datetime(2026, 7, 26, 13, 0, tzinfo=UTC)
    with build_client(tmp_path) as client:
        create_rule(client, clear_duration_seconds=30)
        _, triggered = persist_and_process(client, base, 9.0)
        assert triggered.decisions == (AlertEvaluationDecision.TRIGGER,)
        alert_id = client.get("/api/v1/alerts").json()["items"][0]["id"]

        acknowledged = client.post(
            f"/api/v1/alerts/{alert_id}/acknowledge",
            headers={"Idempotency-Key": "ack-processor-1"},
            json={"reason": "Operator inspected the cabinet"},
        )
        assert acknowledged.status_code == 200, acknowledged.text

        _, hysteresis = persist_and_process(
            client,
            base + timedelta(seconds=5),
            7.5,
        )
        assert hysteresis.decisions == (AlertEvaluationDecision.NONE,)

        _, pending = persist_and_process(
            client,
            base + timedelta(seconds=10),
            6.9,
        )
        assert pending.decisions == (
            AlertEvaluationDecision.START_CLEAR_PENDING,
        )

        _, resolved = persist_and_process(
            client,
            base + timedelta(seconds=40),
            6.8,
        )
        assert resolved.decisions == (AlertEvaluationDecision.RESOLVE,)

        detail = client.get(f"/api/v1/alerts/{alert_id}")
        assert detail.status_code == 200
        assert detail.json()["state"] == "resolved"
        assert detail.json()["resolved_at"] is not None

        transitions = client.get(f"/api/v1/alerts/{alert_id}/transitions")
        assert transitions.status_code == 200
        assert {
            item["event_type"] for item in transitions.json()["items"]
        } == {
            "alert_triggered",
            "alert_acknowledged",
            "alert_resolved",
        }
        resolved_transition = next(
            item
            for item in transitions.json()["items"]
            if item["event_type"] == "alert_resolved"
        )
        assert resolved_transition["previous_state"] == "acknowledged"
        assert resolved_transition["actor_id"] == "nexolab-alert-engine"


def test_unmatched_identity_does_not_create_alert(tmp_path: Path) -> None:
    base = datetime(2026, 7, 26, 14, 0, tzinfo=UTC)
    with build_client(tmp_path) as client:
        create_rule(client)
        event = TelemetryEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=base,
            metric="temperature.probe",
            value=12.0,
            unit="degC",
            quality="valid",
            source="processor-test",
            equipment_id="K999",
            channel_id="999-01",
        )
        payload = event.normalized_payload()
        payload["organization_id"] = ORGANIZATION_ID
        assert client.app.state.database.persist(event, payload) is True
        result = client.app.state.alert_processor.process_payload(payload)
        assert result.matched_rules == 0
        with Session(client.app.state.database.engine) as session:
            assert session.scalar(select(AlertInstance)) is None
