from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.alerts.models import (
    AlertEvaluationState,
    AlertInstance,
    AlertRule,
    AlertRuleVersion,
    AlertTransition,
)
from app.config import Settings
from app.main import create_app


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def build_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=f"sqlite:///{tmp_path / 'alert-immutability.db'}",
                auto_create_schema=True,
                mqtt_enabled=False,
                retention_enabled=False,
            )
        )
    )


def seed_resolved_alert(client: TestClient) -> tuple[str, str]:
    now = datetime.now(UTC)
    rule_id = str(uuid4())
    version_id = str(uuid4())
    alert_id = str(uuid4())
    with Session(client.app.state.database.engine) as session:
        with session.begin():
            session.add(
                AlertRule(
                    id=rule_id,
                    organization_id=ORGANIZATION_ID,
                    name=f"Immutability {uuid4()}",
                    enabled=True,
                    severity="critical",
                    metric="temperature.probe",
                    current_version=1,
                    created_by="test",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AlertRuleVersion(
                    id=version_id,
                    rule_id=rule_id,
                    version=1,
                    condition="threshold_high",
                    trigger_threshold=8.0,
                    clear_threshold=7.0,
                    minimum_duration_seconds=0,
                    clear_duration_seconds=0,
                    debounce_seconds=0,
                    cooldown_seconds=0,
                    configuration={},
                    created_by="test",
                    created_at=now,
                )
            )
            session.add(
                AlertInstance(
                    id=alert_id,
                    organization_id=ORGANIZATION_ID,
                    rule_id=rule_id,
                    rule_version_id=version_id,
                    resource_key="org|-|edge-01|K106|106-03|temperature.probe",
                    node_id="edge-01",
                    equipment_id="K106",
                    channel_id="106-03",
                    metric="temperature.probe",
                    state="resolved",
                    severity="critical",
                    trigger_value=9.0,
                    trigger_threshold=8.0,
                    clear_threshold=7.0,
                    maximum_deviation=1.0,
                    first_event_id=str(uuid4()),
                    last_event_id=str(uuid4()),
                    context={},
                    triggered_at=now,
                    resolved_at=now,
                    lock_version=2,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AlertEvaluationState(
                    id=str(uuid4()),
                    organization_id=ORGANIZATION_ID,
                    rule_id=rule_id,
                    resource_key="org|-|edge-01|K106|106-03|temperature.probe",
                    active_alert_id=alert_id,
                    maximum_deviation=1.0,
                    updated_at=now,
                )
            )
            session.add(
                AlertTransition(
                    id=str(uuid4()),
                    alert_id=alert_id,
                    event_type="alert_resolved",
                    previous_state="active",
                    next_state="resolved",
                    actor_id="nexolab-alert-engine",
                    actor_source="system",
                    idempotency_key=f"resolved-{uuid4()}",
                    payload={},
                    occurred_at=now,
                )
            )
    return alert_id, version_id


def test_close_releases_non_closed_evaluation_identity(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        alert_id, _ = seed_resolved_alert(client)
        response = client.post(
            f"/api/v1/alerts/{alert_id}/close",
            headers={"Idempotency-Key": "close-release-1"},
            json={"reason": "Controlled close"},
        )
        assert response.status_code == 200, response.text
        with Session(client.app.state.database.engine) as session:
            state = session.scalar(
                select(AlertEvaluationState).where(
                    AlertEvaluationState.rule_id
                    == response.json()["alert"]["rule_id"]
                )
            )
            assert state is not None
            assert state.active_alert_id is None
            assert state.maximum_deviation == 0.0


def test_append_only_rule_version_rejects_direct_sql_mutation(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        _, version_id = seed_resolved_alert(client)
        with pytest.raises(DatabaseError):
            with client.app.state.database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE alert_rule_versions "
                        "SET trigger_threshold = 99 "
                        "WHERE id = :version_id"
                    ),
                    {"version_id": version_id},
                )
