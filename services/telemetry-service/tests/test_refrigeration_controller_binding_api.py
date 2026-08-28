from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database, TelemetryLatest
from app.refrigeration.controller_binding_api import create_refrigeration_controller_binding_router
from app.refrigeration.controller_binding_repository import PostgresRefrigerationControllerBindingRepository
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import SecurityRepository

ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
PROFILE = "embraco-sync-fc03-v1.00.04"


def _equipment(equipment_id: str, code: str) -> RefrigerationEquipmentRecord:
    now = datetime.now(UTC)
    return RefrigerationEquipmentRecord(
        id=equipment_id,
        organization_id=ORGANIZATION_ID,
        code=code,
        name=code,
        location="Lab",
        laboratory="Lab",
        zone=None,
        node_id="edge-01",
        climate_chamber_id=None,
        equipment_type="Холодильна вітрина",
        manufacturer="Test",
        model="Test",
        serial_number=code,
        temperature_class="test",
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
        created_at=now,
        updated_at=now,
        deleted_by=None,
        deleted_at=None,
    )


def _client(tmp_path: Path) -> tuple[TestClient, Database]:
    database = Database(f"sqlite:///{tmp_path / 'controller-binding.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    with Session(database.engine) as session:
        with session.begin():
            session.add_all([
                _equipment("equipment-1", "Cool jet"),
                _equipment("equipment-2", "Other"),
            ])
    app = FastAPI()
    app.include_router(
        create_refrigeration_controller_binding_router(
            PostgresRefrigerationControllerBindingRepository(database),
            security_repository=security,
        )
    )
    return TestClient(app), database


def _payload(unit_id: int = 2) -> dict[str, object]:
    return {
        "node_id": "edge-01",
        "controller_family": "embraco",
        "controller_equipment_id": f"EMBRACO-{unit_id}",
        "unit_id": unit_id,
        "profile_version": PROFILE,
    }


def _observe(database: Database, unit_id: int = 2) -> None:
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add_all(
                [
                    TelemetryLatest(
                        sample_id=unit_id * 10,
                        event_id=str(uuid4()),
                        node_id="edge-01",
                        captured_at=now,
                        metric="compressor.speed",
                        value=4500.0,
                        unit="rpm",
                        quality="valid",
                        source="embraco-sync",
                        equipment_id=f"EMBRACO-{unit_id}",
                        channel_id=f"{unit_id}-compressor-speed",
                        alarm=None,
                        raw_value=4500,
                        raw_status=None,
                        stale_after_seconds=90.0,
                        received_at=now,
                    ),
                    TelemetryLatest(
                        sample_id=unit_id * 10 + 1,
                        event_id=str(uuid4()),
                        node_id="edge-01",
                        captured_at=now,
                        metric="refrigeration.control_state",
                        value=5.0,
                        unit="state",
                        quality="valid",
                        source="embraco-sync",
                        equipment_id=f"EMBRACO-{unit_id}",
                        channel_id=f"{unit_id}-control-state",
                        alarm=None,
                        raw_value=5,
                        raw_status=None,
                        stale_after_seconds=90.0,
                        received_at=now,
                    ),
                ]
            )


def test_binding_requires_observed_matching_controller_telemetry(tmp_path: Path) -> None:
    api, _ = _client(tmp_path)

    response = api.put("/api/v1/equipment/equipment-1/controller-binding", json=_payload())

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "controller_binding_unverified"


def test_verified_binding_is_readable_and_idempotent(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    _observe(database)

    created = api.put("/api/v1/equipment/equipment-1/controller-binding", json=_payload())
    repeated = api.put("/api/v1/equipment/equipment-1/controller-binding", json=_payload())
    fetched = api.get("/api/v1/equipment/equipment-1/controller-binding")

    assert created.status_code == 200
    assert repeated.status_code == 200
    assert fetched.status_code == 200
    assert created.json()["id"] == repeated.json()["id"] == fetched.json()["id"]
    assert fetched.json()["controller_equipment_id"] == "EMBRACO-2"
    assert fetched.json()["unit_id"] == 2
    assert fetched.json()["verified_from_telemetry"] is True


def test_controller_summaries_batch_active_binding_state_and_speed(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    _observe(database)
    assert api.put("/api/v1/equipment/equipment-1/controller-binding", json=_payload()).status_code == 200

    response = api.get("/api/v1/equipment/controller-summaries")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "equipment_id": "equipment-1",
                "controller_family": "embraco",
                "controller_equipment_id": "EMBRACO-2",
                "unit_id": 2,
                "profile_version": PROFILE,
                "control_state": 5,
                "compressor_speed_rpm": 4500.0,
                "last_seen_at": response.json()["items"][0]["last_seen_at"],
            }
        ]
    }
    assert response.json()["items"][0]["last_seen_at"] is not None


def test_controller_identity_cannot_be_bound_to_two_assets(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    _observe(database)

    first = api.put("/api/v1/equipment/equipment-1/controller-binding", json=_payload())
    second = api.put("/api/v1/equipment/equipment-2/controller-binding", json=_payload())

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "controller_binding_conflict"


def test_payload_fails_closed_on_incompatible_profile_or_identity(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    _observe(database)

    wrong_profile = api.put(
        "/api/v1/equipment/equipment-1/controller-binding",
        json={**_payload(), "profile_version": "unknown"},
    )
    wrong_identity = api.put(
        "/api/v1/equipment/equipment-1/controller-binding",
        json={**_payload(), "controller_equipment_id": "EMBRACO-96"},
    )

    assert wrong_profile.status_code == 422
    assert wrong_identity.status_code == 422
