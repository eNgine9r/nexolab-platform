from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.models import CentralNode
from app.refrigeration.equipment_api import create_refrigeration_equipment_router
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
CLIMATE_CHAMBER_ID = "kk2"


def payload(code: str = "CS-P1250-2026-108-01") -> dict[str, object]:
    return {
        "code": code,
        "name": "Вітрина №108-01",
        "location": "Лабораторія 1 · Зона C",
        "node_id": CLIMATE_CHAMBER_ID,
        "equipment_type": "Холодильна вітрина",
        "manufacturer": "NEXOLAB",
        "model": "NX-1250",
        "serial_number": "NX-10801",
        "temperature_class": "3M1 (0…+5 °C)",
        "installed_at": "2026-07-29",
        "serviced_at": None,
        "total_sensors": 48,
    }


def provision_climate_chamber(database: Database, organization_id: str) -> None:
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    node_id=CLIMATE_CHAMBER_ID,
                    display_name="Кліматична камера КК2",
                    state="active",
                    state_reason="test fixture",
                    clock_warning_ms=30_000,
                    clock_critical_ms=120_000,
                    clock_status="ok",
                    created_by="test-suite",
                    created_at=now,
                    updated_at=now,
                )
            )


def development_client(
    tmp_path: Path,
) -> tuple[
    TestClient,
    PostgresRefrigerationEquipmentRepository,
    PostgresRefrigerationLayoutRepository,
]:
    database = Database(f"sqlite:///{tmp_path / 'equipment-api.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=DEFAULT_ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    provision_climate_chamber(database, DEFAULT_ORGANIZATION_ID)
    equipment = PostgresRefrigerationEquipmentRepository(database)
    layouts = PostgresRefrigerationLayoutRepository(database)
    app = FastAPI()
    app.include_router(
        create_refrigeration_equipment_router(
            equipment,
            security_repository=security,
        )
    )
    return TestClient(app), equipment, layouts


def test_create_get_list_and_soft_delete_preserve_layout_draft(tmp_path: Path) -> None:
    api, repository, layouts = development_client(tmp_path)

    empty = api.get("/api/v1/equipment")
    assert empty.status_code == 200
    assert empty.json() == {"items": []}

    created = api.post("/api/v1/equipment", json=payload())
    assert created.status_code == 201
    assert created.headers["etag"] == 'W/"equipment-v1"'
    assert created.headers["location"].endswith(created.json()["id"])
    assert created.json()["status"] == "offline"
    assert created.json()["online_sensors"] == 0
    assert created.json()["total_sensors"] == 48
    assert created.json()["node_id"] == CLIMATE_CHAMBER_ID

    equipment_id = created.json()["id"]
    assert layouts.get_draft(equipment_id).placements == []

    listed = api.get("/api/v1/equipment")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [equipment_id]

    fetched = api.get(f"/api/v1/equipment/{equipment_id}")
    assert fetched.status_code == 200
    assert fetched.headers["etag"] == 'W/"equipment-v1"'

    stale = api.delete(
        f"/api/v1/equipment/{equipment_id}",
        headers={"If-Match": 'W/"equipment-v2"'},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "equipment_version_conflict",
        "message": "equipment version conflict: expected 2, actual 1",
        "expected_version": 2,
        "actual_version": 1,
    }

    deleted = api.delete(
        f"/api/v1/equipment/{equipment_id}",
        headers={"If-Match": created.headers["etag"]},
    )
    assert deleted.status_code == 204
    assert deleted.headers["etag"] == 'W/"equipment-v2"'
    assert api.get("/api/v1/equipment").json() == {"items": []}
    assert api.get(f"/api/v1/equipment/{equipment_id}").status_code == 404
    assert layouts.get_draft(equipment_id).equipment_id == equipment_id
    assert repository.list_active() == []


def test_duplicate_equipment_code_is_rejected(tmp_path: Path) -> None:
    api, _, _ = development_client(tmp_path)

    assert api.post("/api/v1/equipment", json=payload()).status_code == 201
    duplicate = api.post("/api/v1/equipment", json=payload())

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "equipment_code_conflict"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def secured_client(
    tmp_path: Path,
    *,
    subject: str,
    roles: set[Role],
) -> tuple[TestClient, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / f'equipment-{subject}.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    provision_climate_chamber(database, ORGANIZATION_ID)
    security.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles,
    )
    dependencies = SecurityDependencies(
        security,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider="test-oidc",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    app = FastAPI()
    app.include_router(
        create_refrigeration_equipment_router(
            PostgresRefrigerationEquipmentRepository(database),
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), security


def auth_headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


def test_viewer_can_list_but_cannot_create_equipment(tmp_path: Path) -> None:
    api, _ = secured_client(tmp_path, subject="viewer", roles={Role.VIEWER})

    assert api.get("/api/v1/equipment", headers=auth_headers("viewer")).status_code == 200
    denied = api.post(
        "/api/v1/equipment",
        headers=auth_headers("viewer"),
        json=payload(),
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def test_engineer_create_and_delete_use_verified_actor_and_audit(tmp_path: Path) -> None:
    api, security = secured_client(tmp_path, subject="engineer", roles={Role.ENGINEER})

    created = api.post(
        "/api/v1/equipment",
        headers={
            **auth_headers("engineer"),
            "X-Audit-Reason": "Commission new showcase",
        },
        json=payload(),
    )
    assert created.status_code == 201
    equipment_id = created.json()["id"]

    deleted = api.delete(
        f"/api/v1/equipment/{equipment_id}",
        headers={
            **auth_headers("engineer"),
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Remove decommissioned showcase",
        },
    )
    assert deleted.status_code == 204

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="refrigeration_equipment",
        entity_id=equipment_id,
        limit=10,
    )
    assert [event.action for event in events] == ["equipment.deleted", "equipment.created"]
    assert all(event.actor_subject == "engineer" for event in events)
    assert events[0].reason == "Remove decommissioned showcase"
    assert events[1].reason == "Commission new showcase"
