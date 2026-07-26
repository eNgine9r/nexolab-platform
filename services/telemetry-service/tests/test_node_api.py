from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.api import create_node_router
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from tests.test_report_api import ORGANIZATION_A, ORGANIZATION_B, TestSecurityDependencies, headers


def build_client(tmp_path: Path) -> tuple[TestClient, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'node-api.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add_all(
            [
                SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A"),
                SecurityOrganization(id=ORGANIZATION_B, slug="org-b", name="Org B"),
            ]
        )
        session.commit()
    app = FastAPI()
    app.include_router(
        create_node_router(
            NodeRepository(database),
            TestSecurityDependencies(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app), database


def test_node_api_permissions_replay_lifecycle_and_isolation(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    payload = {
        "node_id": "edge-01",
        "display_name": "Primary edge node",
        "clock_warning_ms": 30_000,
        "clock_critical_ms": 120_000,
    }

    denied = client.post(
        "/api/v1/nodes",
        headers={**headers(role=Role.ENGINEER), "Idempotency-Key": "node-1"},
        json=payload,
    )
    assert denied.status_code == 403

    created = client.post(
        "/api/v1/nodes",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "node-1",
        },
        json=payload,
    )
    replay = client.post(
        "/api/v1/nodes",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "node-1",
        },
        json=payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["provisioning_secret"].startswith("nxl_node_")
    assert created.json()["node"]["state"] == "pending"
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["provisioning_secret"] is None
    assert replay.json()["credential"]["id"] == created.json()["credential"]["id"]

    listing = client.get("/api/v1/nodes", headers=headers(role=Role.VIEWER))
    assert listing.status_code == 200
    assert [row["node_id"] for row in listing.json()] == ["edge-01"]

    foreign = client.get(
        "/api/v1/nodes/edge-01",
        headers=headers(ORGANIZATION_B, role=Role.VIEWER),
    )
    assert foreign.status_code == 404

    activated = client.post(
        "/api/v1/nodes/edge-01/activate",
        headers=headers(role=Role.LABORATORY_MANAGER),
        json={"reason": "commissioning complete"},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["state"] == "active"

    rotated = client.post(
        "/api/v1/nodes/edge-01/credentials/rotate",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "node-rotate-2",
        },
        json={"reason": "scheduled rotation"},
    )
    assert rotated.status_code == 201, rotated.text
    assert rotated.json()["credential"]["generation"] == 2
    assert rotated.json()["provisioning_secret"].startswith("nxl_node_")

    suspended = client.post(
        "/api/v1/nodes/edge-01/suspend",
        headers=headers(role=Role.LABORATORY_MANAGER),
        json={"reason": "maintenance"},
    )
    revoked = client.post(
        "/api/v1/nodes/edge-01/revoke",
        headers=headers(role=Role.LABORATORY_MANAGER),
        json={"reason": "retired"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["state"] == "suspended"
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    database.dispose()


def test_node_api_validates_clock_threshold_order(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    response = client.post(
        "/api/v1/nodes",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": "invalid-thresholds",
        },
        json={
            "node_id": "edge-01",
            "display_name": "Invalid clock policy",
            "clock_warning_ms": 120_000,
            "clock_critical_ms": 30_000,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "node_domain_error"
    database.dispose()
