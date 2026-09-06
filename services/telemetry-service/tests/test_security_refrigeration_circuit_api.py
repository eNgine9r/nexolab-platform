from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.refrigeration.circuit_api import create_refrigeration_circuit_router
from app.refrigeration.circuit_repository import RefrigerationCircuitRepository
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORG = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


def _token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        SECRET,
        algorithm="HS256",
    )


def _headers(subject: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject)}",
        "X-Organization-ID": organization_id,
    }


def _equipment(equipment_id: str, organization_id: str) -> RefrigerationEquipmentRecord:
    return RefrigerationEquipmentRecord(
        id=equipment_id,
        organization_id=organization_id,
        code=f"CODE-{equipment_id}",
        name=equipment_id,
        location="Lab",
        laboratory="Lab",
        zone=None,
        node_id=None,
        climate_chamber_id=None,
        equipment_type="Холодильна вітрина",
        manufacturer="Test",
        model="Test",
        serial_number=f"SN-{equipment_id}",
        temperature_class="3M1",
        installed_at=None,
        serviced_at=None,
        lifecycle_status="active",
        status="offline",
        average_temperature_c=0.0,
        min_temperature_c=0.0,
        max_temperature_c=0.0,
        online_sensors=0,
        total_sensors=48,
        active_alarms=0,
        last_seen_at=None,
        version=1,
        created_by="test-suite",
        created_at=NOW,
        updated_at=NOW,
        deleted_by=None,
        deleted_at=None,
    )


def _client(tmp_path: Path) -> tuple[TestClient, SecurityRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'rfx06-security.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    for org, slug in ((ORG, "primary"), (OTHER, "other")):
        security.provision_organization(organization_id=org, slug=slug, name=slug)
    for subject, org, roles in (
        ("viewer", ORG, {Role.VIEWER}),
        ("engineer", ORG, {Role.ENGINEER}),
        ("other-engineer", OTHER, {Role.ENGINEER}),
    ):
        security.provision_membership(
            organization_id=org,
            claims=VerifiedIdentityClaims(
                provider="test-oidc",
                subject=subject,
                email=f"{subject}@example.test",
                display_name=subject,
            ),
            roles=roles,
        )
    with Session(database.engine) as session:
        with session.begin():
            session.add_all([_equipment("equipment-1", ORG), _equipment("equipment-2", OTHER)])
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
        default_organization_id=ORG,
    )
    app = FastAPI()
    app.include_router(
        create_refrigeration_circuit_router(
            RefrigerationCircuitRepository(database),
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORG,
        )
    )
    return TestClient(app), security


def _payload() -> dict[str, object]:
    return {
        "equipment_id": "equipment-1",
        "business_key": "SECURE-CIRCUIT",
        "display_name": "Secure circuit",
        "initial_state": "active",
        "valid_from": "2026-09-06T00:00:00Z",
    }


def test_dashboard_read_can_list_but_equipment_manage_is_required_to_create(tmp_path: Path) -> None:
    api, _ = _client(tmp_path)

    assert api.get(
        "/api/v1/refrigeration/circuits",
        headers=_headers("viewer", ORG),
    ).status_code == 200
    viewer_binding_read = api.get(
        "/api/v1/refrigeration/circuits/missing/bindings/missing",
        headers=_headers("viewer", ORG),
    )
    assert viewer_binding_read.status_code == 404
    denied = api.post(
        "/api/v1/refrigeration/circuits",
        headers=_headers("viewer", ORG),
        json=_payload(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def test_circuit_mutation_is_audited_and_cross_org_reads_fail_closed(tmp_path: Path) -> None:
    api, security = _client(tmp_path)

    created = api.post(
        "/api/v1/refrigeration/circuits",
        headers={**_headers("engineer", ORG), "X-Audit-Reason": "RFX-06 setup"},
        json=_payload(),
    )
    assert created.status_code == 201, created.text
    circuit_id = created.json()["id"]

    other_read = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}",
        headers=_headers("other-engineer", OTHER),
    )
    assert other_read.status_code == 404
    assert other_read.json()["detail"]["code"] == "refrigeration_circuit_not_found"

    other_binding_read = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings/missing",
        headers=_headers("other-engineer", OTHER),
    )
    assert other_binding_read.status_code == 404
    assert other_binding_read.json()["detail"]["code"] == "refrigeration_circuit_not_found"

    events = security.list_audit_events(
        organization_id=ORG,
        limit=10,
        entity_type="refrigeration_circuit",
        entity_id=circuit_id,
    )
    assert len(events) == 1
    assert events[0].action == "refrigeration.circuit.created"
    assert events[0].reason == "RFX-06 setup"
