from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.nodes.models import CentralNode
from app.refrigeration.equipment_api import create_refrigeration_equipment_router
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.lifecycle_api import create_equipment_lifecycle_router
from app.refrigeration.lifecycle_repository import PostgresEquipmentLifecycleRepository
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.storage import InMemoryObjectStorage
from app.security.repository import SecurityRepository

ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
NODE_ID = "edge-lab-01"


def equipment_payload(*, lifecycle_status: str = "active") -> dict[str, object]:
    return {
        "code": "CS-GATE-B-01",
        "name": "Вітрина Gate B",
        "location": "Лабораторія 1 · Зона A",
        "laboratory": "Лабораторія 1",
        "zone": "Зона A",
        "node_id": NODE_ID,
        "equipment_type": "Холодильна вітрина",
        "manufacturer": "NEXOLAB",
        "model": "NX-GATE-B",
        "serial_number": "NX-GATE-B-0001",
        "temperature_class": "3M1 (0…+5 °C)",
        "installed_at": "2026-07-29",
        "serviced_at": None,
        "lifecycle_status": lifecycle_status,
        "total_sensors": 48,
    }


def build_client(tmp_path: Path) -> tuple[TestClient, Database, InMemoryObjectStorage, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / 'equipment-gate-b.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=str(uuid4()),
                    organization_id=ORGANIZATION_ID,
                    node_id=NODE_ID,
                    display_name="Edge laboratory 01",
                    state="active",
                    state_reason="acceptance fixture",
                    clock_warning_ms=30_000,
                    clock_critical_ms=120_000,
                    clock_status="ok",
                    created_by="test-suite",
                    created_at=now,
                    updated_at=now,
                )
            )
            for index, channel_id in enumerate(("sensor-01", "sensor-02"), start=1):
                session.add(
                    TelemetrySample(
                        event_id=str(uuid4()),
                        node_id=NODE_ID,
                        captured_at=now,
                        metric="temperature",
                        value=float(index + 1),
                        unit="degC",
                        quality="good",
                        source="modbus",
                        equipment_id="unassigned",
                        channel_id=channel_id,
                        alarm=None,
                        raw_value=200 + index,
                        raw_status=0,
                        raw_payload={"channel_id": channel_id},
                        raw_payload_retained=True,
                        received_at=now,
                    )
                )
    equipment = PostgresRefrigerationEquipmentRepository(database)
    layouts = PostgresRefrigerationLayoutRepository(database)
    lifecycle = PostgresEquipmentLifecycleRepository(database)
    storage = InMemoryObjectStorage()
    app = FastAPI()
    app.include_router(
        create_refrigeration_equipment_router(
            equipment,
            security_repository=security,
        )
    )
    app.include_router(
        create_equipment_lifecycle_router(
            lifecycle,
            layouts,
            storage,
            signed_url_seconds=300,
            security_repository=security,
        )
    )
    return TestClient(app), database, storage, security


def test_complete_passport_sensor_replacement_and_retirement(tmp_path: Path) -> None:
    api, _, _, security = build_client(tmp_path)

    created = api.post("/api/v1/equipment", json=equipment_payload())
    assert created.status_code == 201
    equipment_id = created.json()["id"]
    assert created.json()["lifecycle_status"] == "active"
    assert created.json()["laboratory"] == "Лабораторія 1"
    assert created.json()["zone"] == "Зона A"
    assert created.json()["node_id"] == NODE_ID

    options = api.get("/api/v1/equipment/options/nodes")
    assert options.status_code == 200
    assert options.json()["items"] == [
        {
            "node_id": NODE_ID,
            "display_name": "Edge laboratory 01",
            "state": "active",
            "last_seen_at": None,
        }
    ]

    available = api.get(f"/api/v1/equipment/{equipment_id}/available-sensors")
    assert available.status_code == 200
    assert [item["channel_id"] for item in available.json()["items"]] == [
        "sensor-01",
        "sensor-02",
    ]

    bound = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-bindings/front-01",
        headers={"If-Match": created.headers["etag"]},
        json={
            "channel_id": "sensor-01",
            "label": "01F",
            "side": "front",
            "shelf": 1,
            "position": 1,
        },
    )
    assert bound.status_code == 200
    assert bound.headers["etag"] == 'W/"equipment-v2"'
    first_coordinates = bound.json()["draft"]["placements"][0]
    assert first_coordinates["sensor_id"] == "sensor-01"

    replaced = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-bindings/front-01",
        headers={"If-Match": bound.headers["etag"]},
        json={
            "channel_id": "sensor-02",
            "label": "01F replacement",
            "side": "front",
            "shelf": 1,
            "position": 1,
        },
    )
    assert replaced.status_code == 200
    assert replaced.headers["etag"] == 'W/"equipment-v3"'
    replacement = replaced.json()["draft"]["placements"]
    assert replacement == [
        {
            "sensor_id": "sensor-02",
            "x": first_coordinates["x"],
            "y": first_coordinates["y"],
        }
    ]

    stale = api.delete(
        f"/api/v1/equipment/{equipment_id}/sensor-bindings/front-01",
        headers={"If-Match": bound.headers["etag"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "equipment_version_conflict"

    maintenance = api.put(
        f"/api/v1/equipment/{equipment_id}",
        headers={"If-Match": replaced.headers["etag"]},
        json=equipment_payload(lifecycle_status="maintenance"),
    )
    assert maintenance.status_code == 200
    assert maintenance.json()["lifecycle_status"] == "maintenance"

    retired = api.put(
        f"/api/v1/equipment/{equipment_id}",
        headers={"If-Match": maintenance.headers["etag"]},
        json=equipment_payload(lifecycle_status="retired"),
    )
    assert retired.status_code == 200
    assert retired.json()["lifecycle_status"] == "retired"
    assert retired.json()["status"] == "offline"

    active_bindings = api.get(f"/api/v1/equipment/{equipment_id}/sensor-bindings")
    assert active_bindings.json() == {"items": []}
    history = api.get(
        f"/api/v1/equipment/{equipment_id}/sensor-bindings?include_history=true"
    )
    assert len(history.json()["items"]) == 2
    assert all(item["unbound_at"] is not None for item in history.json()["items"])

    denied = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-bindings/front-02",
        headers={"If-Match": retired.headers["etag"]},
        json={
            "channel_id": "sensor-01",
            "label": "02F",
            "side": "front",
            "shelf": 1,
            "position": 2,
        },
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "equipment_retired"

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        limit=20,
    )
    actions = [event.action for event in events]
    assert "equipment.sensor.bound" in actions
    assert "equipment.updated" in actions


def test_image_retirement_preserves_storage_and_rejects_active_draft_image(tmp_path: Path) -> None:
    api, database, storage, _ = build_client(tmp_path)
    created = api.post("/api/v1/equipment", json=equipment_payload())
    equipment_id = created.json()["id"]
    layouts = PostgresRefrigerationLayoutRepository(database)

    for image_id in ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"):
        key = f"equipment-images/{ORGANIZATION_ID}/{image_id}.png"
        storage.put(key=key, content=b"png", media_type="image/png", checksum_sha256=image_id.replace("-", ""))
        layouts.create_image(
            image_id=image_id,
            organization_id=ORGANIZATION_ID,
            equipment_id=equipment_id,
            storage_key=key,
            original_filename=f"{image_id}.png",
            media_type="image/png",
            size_bytes=3,
            width_px=1,
            height_px=1,
            checksum_sha256=image_id.replace("-", ""),
            object_etag=None,
            created_by="test-suite",
        )

    draft = layouts.get_draft(equipment_id, organization_id=ORGANIZATION_ID)
    attached = layouts.save_draft(
        equipment_id=equipment_id,
        expected_version=draft.version,
        image_id="22222222-2222-2222-2222-222222222222",
        placements=[],
        organization_id=ORGANIZATION_ID,
    )
    assert attached.image_id == "22222222-2222-2222-2222-222222222222"

    active_denied = api.delete(
        f"/api/v1/equipment/{equipment_id}/images/22222222-2222-2222-2222-222222222222",
        headers={"If-Match": created.headers["etag"]},
    )
    assert active_denied.status_code == 409
    assert active_denied.json()["detail"]["code"] == "equipment_image_conflict"

    retired = api.delete(
        f"/api/v1/equipment/{equipment_id}/images/11111111-1111-1111-1111-111111111111",
        headers={"If-Match": created.headers["etag"]},
    )
    assert retired.status_code == 200
    assert retired.headers["etag"] == 'W/"equipment-v2"'
    assert retired.json()["retired_at"] is not None
    assert len(storage.objects) == 2

    inventory = api.get(f"/api/v1/equipment/{equipment_id}/images")
    assert inventory.status_code == 200
    assert len(inventory.json()["items"]) == 2
