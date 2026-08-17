from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance
from app.config import Settings
from app.main import create_app


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'alert-telemetry-scope.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def headers(organization_id: str = ORGANIZATION_A) -> dict[str, str]:
    return {"X-Organization-ID": organization_id}


def create_rule(client: TestClient, organization_id: str = ORGANIZATION_A) -> dict:
    response = client.post(
        "/api/v1/alerts/rules",
        headers=headers(organization_id),
        json={
            "name": f"Telemetry scope {organization_id}",
            "severity": "critical",
            "node_id": "edge-01",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "metric": "temperature.probe",
            "condition": "threshold_high",
            "trigger_threshold": 8.0,
            "clear_threshold": 7.0,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_alert(
    client: TestClient,
    rule: dict,
    *,
    node_id: str,
    equipment_id: str,
    channel_id: str,
    metric: str,
    state: str = "active",
    severity: str = "critical",
    triggered_at: datetime,
) -> str:
    alert_id = str(uuid4())
    with Session(client.app.state.database.engine) as session:
        with session.begin():
            session.add(
                AlertInstance(
                    id=alert_id,
                    organization_id=rule["organization_id"],
                    rule_id=rule["id"],
                    rule_version_id=rule["version"]["id"],
                    resource_key=f"{node_id}|{equipment_id}|{channel_id}|{metric}",
                    node_id=node_id,
                    equipment_id=equipment_id,
                    channel_id=channel_id,
                    metric=metric,
                    state=state,
                    severity=severity,
                    trigger_value=9.0,
                    trigger_threshold=8.0,
                    clear_threshold=7.0,
                    maximum_deviation=1.0,
                    first_event_id=str(uuid4()),
                    last_event_id=str(uuid4()),
                    context={"unit": "degC"},
                    triggered_at=triggered_at,
                    created_at=triggered_at,
                    updated_at=triggered_at,
                    lock_version=1,
                )
            )
    return alert_id


def point_key(
    node_id: str,
    equipment_id: str,
    channel_id: str,
    metric: str,
    unit: str = "degC",
) -> str:
    return "|".join(quote(part, safe="") for part in (node_id, equipment_id, channel_id, metric, unit))


def test_exact_multi_point_scope_is_applied_before_pagination(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule = create_rule(client)
        now = datetime.now(UTC)
        newest_unselected = seed_alert(
            client,
            rule,
            node_id="edge-01",
            equipment_id="K999",
            channel_id="999-01",
            metric="temperature.probe",
            triggered_at=now,
        )
        selected_first = seed_alert(
            client,
            rule,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            triggered_at=now - timedelta(seconds=10),
        )
        selected_second = seed_alert(
            client,
            rule,
            node_id="edge-02",
            equipment_id="M200",
            channel_id="200-01",
            metric="energy.active_power",
            triggered_at=now - timedelta(seconds=20),
        )

        response = client.get(
            "/api/v1/alerts",
            headers=headers(),
            params=[
                ("telemetry_point", point_key("edge-01", "K106", "106-03", "temperature.probe")),
                ("telemetry_point", point_key("edge-02", "M200", "200-01", "energy.active_power", "W")),
                ("limit", "1"),
            ],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 2
        assert body["next_offset"] == 1
        assert [item["id"] for item in body["items"]] == [selected_first]
        assert newest_unselected not in [item["id"] for item in body["items"]]

        second_page = client.get(
            "/api/v1/alerts",
            headers=headers(),
            params=[
                ("telemetry_point", point_key("edge-01", "K106", "106-03", "temperature.probe")),
                ("telemetry_point", point_key("edge-02", "M200", "200-01", "energy.active_power", "W")),
                ("limit", "1"),
                ("offset", "1"),
            ],
        )
        assert [item["id"] for item in second_page.json()["items"]] == [selected_second]


def test_telemetry_scope_composes_with_state_severity_and_organization(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule_a = create_rule(client)
        rule_b = create_rule(client, ORGANIZATION_B)
        now = datetime.now(UTC)
        selected_active = seed_alert(
            client,
            rule_a,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            state="active",
            severity="critical",
            triggered_at=now,
        )
        seed_alert(
            client,
            rule_a,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            state="resolved",
            severity="critical",
            triggered_at=now - timedelta(seconds=1),
        )
        seed_alert(
            client,
            rule_b,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            state="active",
            severity="critical",
            triggered_at=now,
        )

        response = client.get(
            "/api/v1/alerts",
            headers=headers(),
            params={
                "telemetry_point": point_key("edge-01", "K106", "106-03", "temperature.probe"),
                "state": "active",
                "severity": "critical",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 1
        assert [item["id"] for item in response.json()["items"]] == [selected_active]


def test_invalid_or_oversized_telemetry_scope_fails_closed(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        malformed = client.get(
            "/api/v1/alerts",
            headers=headers(),
            params={"telemetry_point": "edge-01|K106|106-03"},
        )
        assert malformed.status_code == 422
        assert malformed.json()["detail"]["code"] == "alert_telemetry_scope_invalid"

        oversized = client.get(
            "/api/v1/alerts",
            headers=headers(),
            params=[("telemetry_point", point_key("edge-01", f"K{index}", "01", "temperature.probe")) for index in range(65)],
        )
        assert oversized.status_code == 422
        assert oversized.json()["detail"]["code"] == "alert_telemetry_scope_invalid"


def test_omitted_scope_preserves_existing_feed_behavior(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        rule = create_rule(client)
        now = datetime.now(UTC)
        seed_alert(
            client,
            rule,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            triggered_at=now,
        )
        seed_alert(
            client,
            rule,
            node_id="edge-02",
            equipment_id="M200",
            channel_id="200-01",
            metric="energy.active_power",
            triggered_at=now - timedelta(seconds=1),
        )

        response = client.get("/api/v1/alerts", headers=headers())
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 2
