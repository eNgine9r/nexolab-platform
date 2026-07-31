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
        "code": f"CS-{chamber_id}-CATALOG-01",
        "name": f"Вітрина {chamber_id}",
        "location": f"Лабораторія 1 · {chamber_id}",
        "laboratory": "Лабораторія 1",
        "zone": chamber_id,
        "climate_chamber_id": chamber_id,
        "equipment_type": "Холодильна вітрина",
        "manufacturer": "NEXOLAB",
        "model": f"NX-{chamber_id}",
        "serial_number": f"NX-{chamber_id}-0001",
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
    assert kk2_channels.json()["items"][-1]["channel_id"] == "114-06"
    kk2_by_id = {
        item["channel_id"]: item for item in kk2_channels.json()["items"]
    }
    assert kk2_by_id["106-03"]["latest_value"] is None
    assert kk2_by_id["106-03"]["quality"] == "no-data"
    assert kk2_by_id["106-04"]["latest_value"] is None
    assert kk2_by_id["106-04"]["quality"] == "no-data"
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


def test_kk2_no_data_channel_can_be_placed_before_physical_installation(
    tmp_path: Path,
) -> None:
    api = build_client(tmp_path)
    created = api.post("/api/v1/equipment", json=equipment_payload("KK2"))
    assert created.status_code == 201

    configured = api.put(
        f"/api/v1/equipment/{created.json()['id']}/sensor-configuration",
        headers={
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Pre-plan KK2 sensor placement before installation",
        },
        json=configuration("106-04"),
    )

    assert configured.status_code == 200
    assert configured.json()["bindings"][0]["channel_id"] == "106-04"
    assert configured.json()["bindings"][0]["node_id"] == "edge-01"
    assert configured.json()["draft"]["placements"] == [
        {"sensor_id": "106-04", "x": 0.2, "y": 0.3}
    ]

    channels = api.get(
        "/api/v1/equipment/options/climate-chambers/KK2/channels"
    )
    item = next(
        row for row in channels.json()["items"] if row["channel_id"] == "106-04"
    )
    assert item["is_bound"] is True
    assert item["bound_equipment_id"] == created.json()["id"]
    assert item["latest_value"] is None
    assert item["quality"] == "no-data"


def test_zero_sensor_capacity_is_normalized_before_configuration(
    tmp_path: Path,
) -> None:
    api = build_client(tmp_path)
    payload = equipment_payload("KK2")
    payload["code"] = "CS-KK2-ZERO-CAPACITY"
    payload["serial_number"] = "NX-KK2-ZERO-CAPACITY"
    payload["total_sensors"] = 0

    created = api.post("/api/v1/equipment", json=payload)

    assert created.status_code == 201
    assert created.json()["total_sensors"] == 48

    configured = api.put(
        f"/api/v1/equipment/{created.json()['id']}/sensor-configuration",
        headers={
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Recover legacy zero sensor slot capacity",
        },
        json=configuration("106-03"),
    )

    assert configured.status_code == 200
    assert configured.json()["bindings"][0]["channel_id"] == "106-03"
