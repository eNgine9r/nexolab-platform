from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.reports.api import create_report_router
from app.reports.output_api import create_report_output_router
from app.reports.output_queries import ReportOutputQueryRepository
from app.reports.output_repository import ReportOutputRepository
from app.reports.repository import ReportRepository
from app.security.authorization import Role
from tests.test_report_api import (
    ORGANIZATION_A,
    ORGANIZATION_B,
    TestSecurityDependencies,
    headers,
    seed_session,
)


def build_client(tmp_path: Path) -> tuple[TestClient, Database]:
    database = Database(f"sqlite:///{tmp_path / 'report-output-api.db'}")
    database.create_schema()
    reports = ReportRepository(database)
    outputs = ReportOutputRepository(database)
    queries = ReportOutputQueryRepository(database)
    security = TestSecurityDependencies()
    app = FastAPI()
    app.include_router(
        create_report_router(
            reports,
            security,  # type: ignore[arg-type]
        )
    )
    app.include_router(
        create_report_output_router(
            outputs,
            queries,
            security,  # type: ignore[arg-type]
        )
    )
    return TestClient(app), database


def generate(client: TestClient, key: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/reports/sessions/session-1",
        headers={**headers(), "Idempotency-Key": key},
        json={},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_render_state_replay_and_exact_download(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    seed_session(database)
    report = generate(client, "report-version-1")
    report_id = str(report["id"])
    manifest_sha = str(report["manifest_sha256"])

    xlsx = client.post(
        f"/api/v1/reports/{report_id}/renders/xlsx",
        headers={**headers(), "Idempotency-Key": "render-xlsx-1"},
        json={"expected_manifest_sha256": manifest_sha},
    )
    replay = client.post(
        f"/api/v1/reports/{report_id}/renders/xlsx",
        headers={**headers(), "Idempotency-Key": "render-xlsx-1"},
        json={"expected_manifest_sha256": manifest_sha},
    )
    pdf = client.post(
        f"/api/v1/reports/{report_id}/renders/pdf",
        headers={**headers(), "Idempotency-Key": "render-pdf-1"},
        json={"expected_manifest_sha256": manifest_sha},
    )

    assert xlsx.status_code == 201, xlsx.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["id"] == xlsx.json()["id"]
    assert replay.json()["sha256"] == xlsx.json()["sha256"]
    assert pdf.status_code == 201, pdf.text

    state = client.get(
        f"/api/v1/reports/{report_id}/outputs",
        headers=headers(role=Role.VIEWER),
    )
    assert state.status_code == 200, state.text
    assert state.json()["approval"]["state"] == "generated"
    assert {item["format"] for item in state.json()["renders"]} == {"xlsx", "pdf"}

    render = xlsx.json()
    download = client.get(
        f"/api/v1/reports/{report_id}/renders/{render['id']}",
        headers=headers(role=Role.VIEWER),
    )
    assert download.status_code == 200
    assert download.headers["X-Content-SHA256"] == render["sha256"]
    assert download.headers["X-Manifest-SHA256"] == manifest_sha
    assert download.headers["ETag"] == f'"{render["sha256"]}"'
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert len(download.content) == render["size_bytes"]


def test_permissions_approval_replay_and_supersede(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    seed_session(database)
    first = generate(client, "report-version-1")
    second = generate(client, "report-version-2")
    first_id = str(first["id"])
    occurred_at = datetime(2026, 7, 26, 20, 0, tzinfo=UTC).isoformat()

    denied_render = client.post(
        f"/api/v1/reports/{first_id}/renders/xlsx",
        headers={
            **headers(role=Role.VIEWER),
            "Idempotency-Key": "viewer-render",
        },
        json={},
    )
    denied_approve = client.post(
        f"/api/v1/reports/{first_id}/approve",
        headers={
            **headers(role=Role.ENGINEER),
            "Idempotency-Key": "engineer-approve",
        },
        json={
            "expected_manifest_sha256": first["manifest_sha256"],
            "reason": "Engineer must not approve",
            "occurred_at": occurred_at,
        },
    )
    assert denied_render.status_code == 403
    assert denied_approve.status_code == 403

    approval_payload = {
        "expected_manifest_sha256": first["manifest_sha256"],
        "reason": "Laboratory manager reviewed immutable evidence",
        "occurred_at": occurred_at,
    }
    approved = client.post(
        f"/api/v1/reports/{first_id}/approve",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "approve-report-1",
        },
        json=approval_payload,
    )
    replay = client.post(
        f"/api/v1/reports/{first_id}/approve",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "approve-report-1",
        },
        json=approval_payload,
    )

    assert approved.status_code == 201, approved.text
    assert approved.json()["decision"] == "approve"
    assert approved.json()["approval"]["state"] == "approved"
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["event_id"] == approved.json()["event_id"]

    superseded = client.post(
        f"/api/v1/reports/{first_id}/supersede",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "supersede-report-1",
        },
        json={
            "expected_manifest_sha256": first["manifest_sha256"],
            "reason": "A later immutable version replaces this protocol",
            "replacement_report_id": second["id"],
            "occurred_at": datetime(2026, 7, 26, 20, 5, tzinfo=UTC).isoformat(),
        },
    )
    assert superseded.status_code == 201, superseded.text
    assert superseded.json()["decision"] == "supersede"
    assert superseded.json()["approval"]["state"] == "superseded"
    assert superseded.json()["approval"]["superseded_by_report_id"] == second["id"]


def test_foreign_organization_cannot_discover_outputs(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    seed_session(database)
    report = generate(client, "report-version-1")
    report_id = str(report["id"])
    rendered = client.post(
        f"/api/v1/reports/{report_id}/renders/xlsx",
        headers={**headers(), "Idempotency-Key": "render-xlsx-1"},
        json={},
    )
    assert rendered.status_code == 201

    foreign_state = client.get(
        f"/api/v1/reports/{report_id}/outputs",
        headers=headers(ORGANIZATION_B),
    )
    foreign_download = client.get(
        f"/api/v1/reports/{report_id}/renders/{rendered.json()['id']}",
        headers=headers(ORGANIZATION_B),
    )
    assert foreign_state.status_code == 404
    assert foreign_download.status_code == 404
