from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.api import create_climate_catalog_router
from app.climate_catalog.models import MeasurementDevice, PhysicalSensor
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database
from app.model_registry import register_models
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


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


def headers(subject: str, organization_id: str = ORGANIZATION_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": organization_id,
    }


def build_client(
    tmp_path: Path,
    *,
    subject: str = "engineer",
    roles: set[Role] | None = None,
) -> tuple[TestClient, Database, SecurityRepository, PostgresClimateCatalogRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / f'{subject}.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    for organization_id, slug in (
        (ORGANIZATION_ID, "nexolab-lab"),
        (OTHER_ORGANIZATION_ID, "other-lab"),
    ):
        security.provision_organization(
            organization_id=organization_id,
            slug=slug,
            name=slug,
        )
    security.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles or {Role.ENGINEER},
    )
    repository = PostgresClimateCatalogRepository(database, security_repository=security)
    repository.seed_default_catalog(organization_id=ORGANIZATION_ID)
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
        create_climate_catalog_router(
            repository,
            security_dependencies=dependencies,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), database, security, repository


def first_catalog_assets(api: TestClient, subject: str) -> tuple[dict, dict]:
    payload = api.get(
        "/api/v1/climate-chambers/KK1/equipment",
        headers=headers(subject),
    ).json()
    return payload["temperatureControllers"][0], payload["temperatureChannels"][0]["physical_sensors"][0]


def test_device_metadata_update_is_versioned_audited_and_protects_transport_fields(tmp_path: Path) -> None:
    api, database, security, _ = build_client(tmp_path)
    device, _ = first_catalog_assets(api, "engineer")

    updated = api.patch(
        f"/api/v1/climate-chambers/KK1/measurement-devices/{device['id']}",
        headers={
            **headers("engineer"),
            "If-Match": 'W/"measurement-device-v1"',
            "X-Audit-Reason": "Correct passport metadata",
        },
        json={
            "display_name": "  Контролер лабораторний  ",
            "designation": " T-126 ",
            "manufacturer": " Eliwell ",
            "model": " XJP60D ",
        },
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"measurement-device-v2"'
    assert updated.json()["version"] == 2
    assert updated.json()["display_name"] == "Контролер лабораторний"

    stale = api.patch(
        f"/api/v1/climate-chambers/KK1/measurement-devices/{device['id']}",
        headers={**headers("engineer"), "If-Match": 'W/"measurement-device-v1"'},
        json={
            "display_name": "Stale",
            "designation": None,
            "manufacturer": "Eliwell",
            "model": "XJP60D",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "climate_asset_version_conflict"

    protected = api.patch(
        f"/api/v1/climate-chambers/KK1/measurement-devices/{device['id']}",
        headers={**headers("engineer"), "If-Match": 'W/"measurement-device-v2"'},
        json={
            "display_name": "Контролер лабораторний",
            "designation": "T-126",
            "manufacturer": "Eliwell",
            "model": "XJP60D",
            "unit_id": 999,
        },
    )
    assert protected.status_code == 422

    with Session(database.engine) as session:
        row = session.get(MeasurementDevice, device["id"])
        assert row is not None
        assert row.unit_id == device["unit_id"]
        assert row.connection_status == device["connection_status"]
        assert row.status == device["status"]

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="measurement_device",
        entity_id=device["id"],
        limit=10,
    )
    assert len(events) == 1
    event = events[0]
    assert event.action == "measurement_device.metadata_updated"
    assert event.actor_subject == "engineer"
    assert event.reason == "Correct passport metadata"
    assert event.before_snapshot is not None and event.after_snapshot is not None
    assert event.before_snapshot["unit_id"] == event.after_snapshot["unit_id"]
    assert event.before_snapshot["version"] == 1
    assert event.after_snapshot["version"] == 2


def test_sensor_metadata_update_is_versioned_audited_and_rejects_mapping_fields(tmp_path: Path) -> None:
    api, database, security, _ = build_client(tmp_path)
    _, sensor = first_catalog_assets(api, "engineer")

    updated = api.patch(
        f"/api/v1/climate-chambers/KK1/physical-sensors/{sensor['id']}",
        headers={
            **headers("engineer"),
            "If-Match": 'W/"physical-sensor-v1"',
            "X-Audit-Reason": "Register serial and metrology state",
        },
        json={
            "inventory_number": "  LAB-197  ",
            "serial_number": " SN-197 ",
            "calibration_status": "current",
        },
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"physical-sensor-v2"'
    assert updated.json()["version"] == 2
    assert updated.json()["inventory_number"] == "LAB-197"
    assert updated.json()["serial_number"] == "SN-197"
    assert updated.json()["calibration_status"] == "current"

    protected = api.patch(
        f"/api/v1/climate-chambers/KK1/physical-sensors/{sensor['id']}",
        headers={**headers("engineer"), "If-Match": 'W/"physical-sensor-v2"'},
        json={
            "inventory_number": "LAB-197",
            "serial_number": "SN-197",
            "calibration_status": "current",
            "sensor_position": "B",
        },
    )
    assert protected.status_code == 422

    with Session(database.engine) as session:
        row = session.get(PhysicalSensor, sensor["id"])
        assert row is not None
        assert row.sensor_position == sensor["sensor_position"]
        assert row.channel_id
        assert row.status == sensor["status"]

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="physical_sensor",
        entity_id=sensor["id"],
        limit=10,
    )
    assert len(events) == 1
    assert events[0].action == "physical_sensor.metadata_updated"
    assert events[0].before_snapshot["sensor_position"] == events[0].after_snapshot["sensor_position"]


def test_sensor_inventory_conflict_returns_409(tmp_path: Path) -> None:
    api, _, _, _ = build_client(tmp_path)
    payload = api.get("/api/v1/climate-chambers/KK1/equipment", headers=headers("engineer")).json()
    first = payload["temperatureChannels"][0]["physical_sensors"][0]
    second = payload["temperatureChannels"][1]["physical_sensors"][0]

    response = api.patch(
        f"/api/v1/climate-chambers/KK1/physical-sensors/{second['id']}",
        headers={**headers("engineer"), "If-Match": 'W/"physical-sensor-v1"'},
        json={
            "inventory_number": first["inventory_number"],
            "serial_number": None,
            "calibration_status": "untracked",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "physical_sensor_inventory_conflict"


def test_viewer_has_no_climate_asset_metadata_mutation_path(tmp_path: Path) -> None:
    api, _, _, _ = build_client(tmp_path, subject="viewer", roles={Role.VIEWER})
    device, sensor = first_catalog_assets(api, "viewer")

    device_response = api.patch(
        f"/api/v1/climate-chambers/KK1/measurement-devices/{device['id']}",
        headers={**headers("viewer"), "If-Match": 'W/"measurement-device-v1"'},
        json={
            "display_name": device["display_name"],
            "designation": device["designation"],
            "manufacturer": device["manufacturer"],
            "model": device["model"],
        },
    )
    sensor_response = api.patch(
        f"/api/v1/climate-chambers/KK1/physical-sensors/{sensor['id']}",
        headers={**headers("viewer"), "If-Match": 'W/"physical-sensor-v1"'},
        json={
            "inventory_number": sensor["inventory_number"],
            "serial_number": sensor["serial_number"],
            "calibration_status": sensor["calibration_status"],
        },
    )
    assert device_response.status_code == 403
    assert sensor_response.status_code == 403
    assert device_response.json()["detail"]["code"] == "permission_denied"
    assert sensor_response.json()["detail"]["code"] == "permission_denied"


def test_repository_metadata_update_is_organization_scoped(tmp_path: Path) -> None:
    api, _, _, repository = build_client(tmp_path)
    device, sensor = first_catalog_assets(api, "engineer")
    from app.security.repository import AuditEventInput

    audit = AuditEventInput(
        organization_id=OTHER_ORGANIZATION_ID,
        actor_identity_id=None,
        actor_subject="test",
        actor_roles=frozenset({Role.ADMINISTRATOR}),
        action="test",
        entity_type="test",
        entity_id="test",
    )
    with pytest.raises(Exception) as device_error:
        repository.update_measurement_device_metadata(
            "KK1",
            device["id"],
            display_name="Other",
            designation=None,
            manufacturer="Other",
            model="Other",
            expected_version=1,
            organization_id=OTHER_ORGANIZATION_ID,
            audit_event=audit,
        )
    assert getattr(device_error.value, "code", None) == "climate_chamber_not_found"

    with pytest.raises(Exception) as sensor_error:
        repository.update_physical_sensor_metadata(
            "KK1",
            sensor["id"],
            inventory_number="OTHER",
            serial_number=None,
            calibration_status="untracked",
            expected_version=1,
            organization_id=OTHER_ORGANIZATION_ID,
            audit_event=audit,
        )
    assert getattr(sensor_error.value, "code", None) == "climate_chamber_not_found"
