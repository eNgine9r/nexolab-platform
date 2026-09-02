from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Callable

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.daily_reports.api import create_daily_report_router
from app.daily_reports.repository import DailyReportRepository
from app.db import Database
from app.model_registry import register_models
from app.nodes.models import CentralNode
from app.refrigeration.models import EquipmentSensorBinding, RefrigerationEquipmentRecord
from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    effective_permissions,
)
from app.security.dependencies import AuthorizedRequest
from app.security.models import SecurityOrganization

register_models()

ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"


class TestSecurityDependencies:
    def authorized_request(
        self,
        permission: Permission,
    ) -> Callable[..., AuthorizedRequest]:
        def dependency(
            organization_id: Annotated[str, Header(alias="X-Organization-ID")],
            role_value: Annotated[str, Header(alias="X-Test-Role")] = Role.ENGINEER.value,
        ) -> AuthorizedRequest:
            role = Role(role_value)
            if permission not in effective_permissions({role}):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "permission_denied"},
                )
            return AuthorizedRequest(
                identity_id=None,
                principal=AuthenticatedPrincipal(
                    subject=f"{role.value}-daily-report-test",
                    organization_id=organization_id,
                    roles=frozenset({role}),
                    provider="daily-report-test",
                ),
            )

        return dependency


def headers(
    organization_id: str = ORGANIZATION_A,
    role: Role = Role.ENGINEER,
) -> dict[str, str]:
    return {
        "X-Organization-ID": organization_id,
        "X-Test-Role": role.value,
    }


def payload(name: str = "Morning report") -> dict[str, object]:
    return {
        "name": name,
        "equipment_id": "showcase-1",
        "timezone": "Europe/Kyiv",
        "report_hour": 7,
        "report_minute": 50,
        "weekdays": [0, 1, 2, 3, 4],
        "analysis_window_minutes": 720,
        "m_packet_channels": [
            {
                "node_id": "edge-01",
                "equipment_id": "K108",
                "channel_id": "M1",
                "metric": "temperature.probe",
                "label": "M1",
            }
        ],
    }


def build_client(tmp_path: Path) -> TestClient:
    database = Database(f"sqlite:///{tmp_path / 'daily-report-api.db'}")
    database.create_schema()
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        for organization_id in (ORGANIZATION_A, ORGANIZATION_B):
            session.add(
                SecurityOrganization(
                    id=organization_id,
                    slug=organization_id,
                    name=organization_id,
                )
            )
        session.add(
            CentralNode(
                id="node-a",
                organization_id=ORGANIZATION_A,
                node_id="edge-01",
                display_name="Edge 01",
                state="active",
                created_by="test-suite",
            )
        )
        session.add(
            RefrigerationEquipmentRecord(
                id="showcase-1",
                organization_id=ORGANIZATION_A,
                code="TEST-SHOWCASE",
                name="Test refrigeration showcase",
                location="Test lab",
                laboratory="Test lab",
                zone=None,
                node_id="edge-01",
                climate_chamber_id=None,
                equipment_type="Холодильна вітрина",
                manufacturer="Test manufacturer",
                model="Test model",
                serial_number="TEST-0001",
                temperature_class="M1",
                installed_at=None,
                serviced_at=None,
                lifecycle_status="active",
                status="normal",
                average_temperature_c=0.0,
                min_temperature_c=0.0,
                max_temperature_c=0.0,
                online_sensors=0,
                total_sensors=1,
                active_alarms=0,
                last_seen_at=None,
                version=1,
                created_by="test-suite",
                created_at=now,
                updated_at=now,
                deleted_by=None,
                deleted_at=None,
            )
        )
        session.flush()
        session.add(
            EquipmentSensorBinding(
                id="binding-m1",
                organization_id=ORGANIZATION_A,
                equipment_id="showcase-1",
                node_id="edge-01",
                channel_id="M1",
                slot_key="front-1-1",
                label="M1",
                side="front",
                shelf=1,
                position=1,
                version=1,
                bound_by="test-suite",
                bound_at=now,
            )
        )
        session.commit()
    app = FastAPI()
    app.include_router(
        create_daily_report_router(
            DailyReportRepository(database),
            TestSecurityDependencies(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app)


def test_profile_etag_update_and_organization_isolation(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    created = client.post("/api/v1/daily-reports/profiles", headers=headers(), json=payload())

    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]
    assert created.headers["etag"] == 'W/"daily-report-profile-v1"'

    fetched = client.get(f"/api/v1/daily-reports/profiles/{profile_id}", headers=headers())
    foreign = client.get(
        f"/api/v1/daily-reports/profiles/{profile_id}",
        headers=headers(ORGANIZATION_B),
    )
    updated = client.put(
        f"/api/v1/daily-reports/profiles/{profile_id}",
        headers={**headers(), "If-Match": fetched.headers["etag"]},
        json=payload("Morning report v2"),
    )
    stale = client.put(
        f"/api/v1/daily-reports/profiles/{profile_id}",
        headers={**headers(), "If-Match": fetched.headers["etag"]},
        json=payload("Stale update"),
    )

    assert fetched.status_code == 200
    assert foreign.status_code == 404
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"daily-report-profile-v2"'
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "daily_report_profile_version_conflict"


def test_viewer_cannot_mutate_profile_but_can_read_snapshot(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    denied = client.post(
        "/api/v1/daily-reports/profiles",
        headers=headers(role=Role.VIEWER),
        json=payload(),
    )
    assert denied.status_code == 403

    created = client.post("/api/v1/daily-reports/profiles", headers=headers(), json=payload())
    profile_id = created.json()["id"]
    generated = client.post(
        f"/api/v1/daily-reports/profiles/{profile_id}/generate",
        headers=headers(),
        json={"local_report_date": "2026-09-02", "reason": "controlled test"},
    )
    replay = client.post(
        f"/api/v1/daily-reports/profiles/{profile_id}/generate",
        headers=headers(),
        json={"local_report_date": "2026-09-02"},
    )
    listing = client.get(
        "/api/v1/daily-reports/snapshots",
        headers=headers(role=Role.VIEWER),
    )

    assert generated.status_code == 201, generated.text
    assert generated.json()["status"] == "incomplete"
    assert generated.json()["payload"]["defrost"] == {
        "reason": "controller_not_bound",
        "status": "unavailable",
    }
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["id"] == generated.json()["id"]
    assert listing.status_code == 200
    assert listing.json()["count"] == 1


def test_invalid_timezone_and_duplicate_m_packet_identity_are_rejected(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    malformed = payload()
    malformed["timezone"] = "Not/AZone"
    invalid_timezone = client.post(
        "/api/v1/daily-reports/profiles",
        headers=headers(),
        json=malformed,
    )
    duplicate = payload()
    duplicate["m_packet_channels"] = duplicate["m_packet_channels"] * 2  # type: ignore[operator]
    duplicate_response = client.post(
        "/api/v1/daily-reports/profiles",
        headers=headers(),
        json=duplicate,
    )

    assert invalid_timezone.status_code == 422
    assert duplicate_response.status_code == 422
