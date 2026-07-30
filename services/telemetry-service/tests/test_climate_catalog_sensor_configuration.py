from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database
from app.model_registry import register_models
from app.refrigeration.equipment_api import create_refrigeration_equipment_router
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.sensor_configuration_api import create_sensor_configuration_router
from app.refrigeration.sensor_configuration_repository import PostgresSensorConfigurationRepository
from app.refrigeration.storage import InMemoryObjectStorage
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def build_client(tmp_path: Path) -> TestClient:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'climate-sensor-configuration.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    catalog = PostgresClimateCatalogRepository(
        database,
        security_repository=security,
    )
    seeded = catalog.seed_default_catalog(organization_id=ORGANIZATION_ID)
    assert seeded.changed is True

    equipment = PostgresRefrigerationEquipmentRepository(database)
    layouts = PostgresRefrigerationLayoutRepository(database)
    sensor_configuration = PostgresSensorConfigurationRepository(
        database,
        climate_catalog_repository=catalog,
    )
    app = FastAPI()
    app.include_router(
        create_refrigeration_equipment_router(
            equipment,
            security_repository=security,
        )
    )
    app.include_router(
        create_sensor_configuration_router(
            sensor_configuration,
            layouts,
            InMemoryObjectStorage(),
            signed_url_seconds=300,
            security_repository=security,
        )
    )
    return TestClient(app)


def equipment_payload(chamber_id: str = "KK1") -> dict[str, object]:
    return {
        "code": "CS-KK1-CATALOG-01",
        "name": "Вітрина КК1",
        "location": "Лабораторія 1 · КК1",
        "laboratory": "Лабораторія 1",
        "zone": "КК1",
        "climate_chamber_id": chamber_id,
        "equipment_type": "Холодильна вітрина",
        "manufacturer": "NEXOLAB",
        "model": "NX-KK1",
        "serial_number": "NX-KK1-0001",
        "temperature_class": "3M1 (0…+5 °C)",
        "installed_at": "2026-07-30",
        "serviced_at": None,
        "lifecycle_status": "active",
        "total_sensors": 48,
    }


def configuration(channel_id: str) -> dict[str, object]:
    return {
        "expected_draft_version": 1,
        "bindings": [
            {
                "slot_key": "front-01",
                "channel_id": channel_id,
                "label": "T01",
                "side": "front",
                "shelf": 1,
                "position": 1,
                "x": 0.2,
                "y": 0.3,
            }
        ],
    }


def test_catalog_channels_exist_without_telemetry_and_reject_cross_chamber_binding(
    tmp_path: Path,
) -> None:
    api = build_client(tmp_path)

    kk1_channels = api.get(
        "/api/v1/equipment/options/climate-chambers/KK1/channels"
    )
    kk2_channels = api.get(
        "/api/v1/equipment/options/climate-chambers/KK2/channels"
    )
    assert kk1_channels.status_code == 200
    assert kk2_channels.status_code == 200
    assert kk1_channels.json()["node_id"] == "edge-01"
    assert kk2_channels.json()["node_id"] == "edge-01"
    assert len(kk1_channels.json()["items"]) == 78
    assert len(kk2_channels.json()["items"]) == 84
    assert kk1_channels.json()["items"][0]["channel_id"] == "126-01"
    assert kk1_channels.json()["items"][-1]["channel_id"] == "138-06"
    assert kk2_channels.json()["items"][0]["channel_id"] == "101-01"
    assert all(item["quality"] == "no-data" for item in kk1_channels.json()["items"])

    created = api.post("/api/v1/equipment", json=equipment_payload())
    assert created.status_code == 201
    assert created.json()["climate_chamber_id"] is not None
    assert created.json()["node_id"] == "edge-01"
    equipment_id = created.json()["id"]

    cross_chamber = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration("101-01"),
    )
    assert cross_chamber.status_code == 422
    assert cross_chamber.json()["detail"]["code"] == "sensor_channel_not_found"

    configured = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Bind a deterministic KK1 catalog channel",
        },
        json=configuration("126-01"),
    )
    assert configured.status_code == 200
    assert configured.json()["bindings"][0]["node_id"] == "edge-01"
    assert configured.json()["bindings"][0]["channel_id"] == "126-01"
    assert configured.json()["draft"]["placements"] == [
        {"sensor_id": "126-01", "x": 0.2, "y": 0.3}
    ]
