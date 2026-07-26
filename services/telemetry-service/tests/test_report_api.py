from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Callable

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.model_registry import register_models
from app.reports.api import create_report_router
from app.reports.repository import ReportRepository
from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    effective_permissions,
)
from app.security.dependencies import AuthorizedRequest
from app.security.models import SecurityOrganization
from app.sessions.models import (
    SessionChannelBinding,
    SessionConfigSnapshot,
    TestSession,
)
from app.sessions.telemetry_attribution import (
    ATTRIBUTION_RESOLVER_VERSION,
    TelemetrySessionContext,
)

register_models()

ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"


class TestSecurityDependencies:
    def authorized_request(
        self,
        permission: Permission,
    ) -> Callable[..., AuthorizedRequest]:
        def dependency(
            organization_id: Annotated[
                str,
                Header(alias="X-Organization-ID"),
            ],
            role_value: Annotated[
                str,
                Header(alias="X-Test-Role"),
            ] = Role.ENGINEER.value,
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
                    subject=f"{role.value}-reports-test",
                    organization_id=organization_id,
                    roles=frozenset({role}),
                    provider="reports-test",
                ),
            )

        return dependency


def build_client(tmp_path: Path) -> tuple[TestClient, Database]:
    database = Database(f"sqlite:///{tmp_path / 'reports-api.db'}")
    database.create_schema()
    repository = ReportRepository(database)
    app = FastAPI()
    app.include_router(
        create_report_router(
            repository,
            TestSecurityDependencies(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app), database


def headers(
    organization_id: str = ORGANIZATION_A,
    role: Role = Role.ENGINEER,
) -> dict[str, str]:
    return {
        "X-Organization-ID": organization_id,
        "X-Test-Role": role.value,
    }


def seed_session(
    database: Database,
    *,
    state: str = "completed",
    organization_id: str = ORGANIZATION_A,
    session_id: str = "session-1",
) -> None:
    started_at = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    completed_at = started_at + timedelta(hours=2)
    with Session(database.engine) as session:
        for candidate in (ORGANIZATION_A, ORGANIZATION_B):
            if session.get(SecurityOrganization, candidate) is None:
                session.add(
                    SecurityOrganization(
                        id=candidate,
                        slug=candidate,
                        name=candidate,
                    )
                )
        session.flush()
        test_session = TestSession(
            id=session_id,
            organization_id=organization_id,
            create_idempotency_key=f"create-{session_id}",
            session_number=f"NX-{session_id}",
            node_id="edge-01",
            state=state,
            title="Refrigeration showcase verification",
            test_object="K106",
            standard="ISO 23953",
            method="temperature distribution",
            started_at=started_at,
            completed_at=(
                completed_at if state in {"completed", "archived"} else None
            ),
        )
        session.add(test_session)
        session.flush()
        binding = SessionChannelBinding(
            id=f"binding-{session_id}",
            session_id=session_id,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            binding_metadata={"position": "front-left"},
            activated_at=started_at,
            released_at=(
                completed_at if state in {"completed", "archived"} else None
            ),
        )
        snapshot = SessionConfigSnapshot(
            id=f"snapshot-{session_id}",
            session_id=session_id,
            version=1,
            source="session_start",
            payload={"binding_id": binding.id},
            content_sha256="a" * 64,
            created_by="engineer-reports-test",
            captured_at=started_at,
        )
        session.add_all([binding, snapshot])
        session.flush()
        test_session.active_config_snapshot_id = snapshot.id
        sample = TelemetrySample(
            event_id=f"event-{session_id}",
            node_id="edge-01",
            captured_at=started_at + timedelta(minutes=10),
            metric="temperature.probe",
            value=3.75,
            unit="degC",
            quality="valid",
            source="report-api-test",
            equipment_id="K106",
            channel_id="106-03",
            alarm=None,
            raw_value=375,
            raw_status=0,
            raw_payload={"register": 375},
            raw_payload_retained=True,
        )
        session.add(sample)
        session.flush()
        session.add(
            TelemetrySessionContext(
                telemetry_event_id=sample.event_id,
                session_id=session_id,
                stage_id=None,
                binding_id=binding.id,
                config_snapshot_id=snapshot.id,
                captured_at=sample.captured_at,
                resolver_version=ATTRIBUTION_RESOLVER_VERSION,
            )
        )
        session.commit()


def test_generate_replay_list_and_download_exact_artifact(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    seed_session(database)

    first = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={**headers(), "Idempotency-Key": "report-request-1"},
        json={"reason": "Controlled report generation"},
    )
    replay = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={**headers(), "Idempotency-Key": "report-request-1"},
        json={"reason": "Controlled report generation"},
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert first.json()["generated_by"] == "engineer-reports-test"

    report_id = first.json()["id"]
    listing = client.get("/api/v1/reports", headers=headers())
    detail = client.get(f"/api/v1/reports/{report_id}", headers=headers())
    download = client.get(
        f"/api/v1/reports/{report_id}/artifacts/telemetry.csv",
        headers=headers(),
    )

    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert detail.status_code == 200
    assert download.status_code == 200
    assert download.headers["X-Content-SHA256"] == next(
        item["sha256"]
        for item in detail.json()["artifacts"]
        if item["name"] == "telemetry.csv"
    )
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert b"event-session-1" in download.content
    assert "authorization" not in download.headers["Content-Disposition"].lower()


def test_viewer_is_read_only_and_foreign_organization_is_not_disclosed(
    tmp_path: Path,
) -> None:
    client, database = build_client(tmp_path)
    seed_session(database)

    denied = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={
            **headers(role=Role.VIEWER),
            "Idempotency-Key": "viewer-report",
        },
        json={},
    )
    assert denied.status_code == 403

    generated = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={**headers(), "Idempotency-Key": "report-request-1"},
        json={},
    )
    report_id = generated.json()["id"]
    viewer_list = client.get(
        "/api/v1/reports",
        headers=headers(role=Role.VIEWER),
    )
    foreign_detail = client.get(
        f"/api/v1/reports/{report_id}",
        headers=headers(ORGANIZATION_B),
    )
    foreign_artifact = client.get(
        f"/api/v1/reports/{report_id}/artifacts/manifest.json",
        headers=headers(ORGANIZATION_B),
    )

    assert viewer_list.status_code == 200
    assert viewer_list.json()["count"] == 1
    assert foreign_detail.status_code == 404
    assert foreign_artifact.status_code == 404


def test_running_session_generation_is_a_typed_conflict(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    seed_session(database, state="running")

    response = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={**headers(), "Idempotency-Key": "running-report"},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "report_session_not_reportable"
