from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.climate_catalog.api import create_climate_catalog_router
from app.climate_catalog.domain import (
    DEFAULT_EDGE_NODE_ID,
    DEFAULT_RS485_BUS_KEY,
    ClimateCatalogError,
    iter_temperature_channels,
    logical_sensor_number,
    temperature_channel_id,
)
from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
    PhysicalSensor,
)
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database
from app.model_registry import register_models
from app.nodes.models import CentralNode
from app.security.models import SecurityAuditEvent
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    ("chamber", "controller", "channel", "expected"),
    [
        ("KK1", 126, 1, 197),
        ("KK1", 126, 6, 202),
        ("KK1", 127, 1, 203),
        ("KK1", 138, 6, 274),
        ("KK2", 101, 1, 471),
        ("KK2", 101, 6, 476),
        ("KK2", 102, 1, 477),
        ("KK2", 114, 6, 554),
    ],
)
def test_logical_sensor_number_formula(
    chamber: str,
    controller: int,
    channel: int,
    expected: int,
) -> None:
    assert logical_sensor_number(chamber, controller, channel) == expected


def test_temperature_channel_business_keys_and_bounds() -> None:
    assert temperature_channel_id("KK1", 126, 1) == "126-01"
    assert temperature_channel_id("KK2", 114, 6) == "114-06"
    with pytest.raises(ClimateCatalogError):
        logical_sensor_number("KK1", 125, 1)
    with pytest.raises(ClimateCatalogError):
        logical_sensor_number("KK2", 101, 7)


def test_domain_catalog_has_exact_channel_ranges() -> None:
    kk1 = list(iter_temperature_channels("KK1"))
    kk2 = list(iter_temperature_channels("KK2"))
    assert len(kk1) == 78
    assert len(kk2) == 84
    assert (kk1[0].logical_sensor_number, kk1[-1].logical_sensor_number) == (
        197,
        274,
    )
    assert (kk2[0].logical_sensor_number, kk2[-1].logical_sensor_number) == (
        471,
        554,
    )
    assert kk1[0].channel_id == kk1[0].source_channel_id == "126-01"
    assert kk2[0].channel_id == kk2[0].source_channel_id == "101-01"
    assert kk1[0].physical_sensor_inventory_numbers == ("197",)
    assert kk2[0].physical_sensor_inventory_numbers == ("471-A", "471-B")


def build_catalog(
    tmp_path: Path,
) -> tuple[Database, SecurityRepository, PostgresClimateCatalogRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'climate-catalog.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    repository = PostgresClimateCatalogRepository(
        database,
        security_repository=security,
    )
    return database, security, repository


def test_seed_is_idempotent_and_creates_exact_catalog(tmp_path: Path) -> None:
    database, _, repository = build_catalog(tmp_path)

    first = repository.seed_default_catalog(organization_id=ORGANIZATION_ID)
    second = repository.seed_default_catalog(organization_id=ORGANIZATION_ID)

    assert first.skipped is False
    assert first.nodes_created == 1
    assert first.buses_created == 1
    assert first.chambers_created == 2
    assert first.devices_created == 31
    assert first.channels_created == 162
    assert first.physical_sensors_created == 246
    assert first.changed is True
    assert second.skipped is False
    assert second.changed is False
    assert second.nodes_created == 0
    assert second.buses_created == 0
    assert second.chambers_created == 0
    assert second.devices_created == 0
    assert second.channels_created == 0
    assert second.physical_sensors_created == 0

    with Session(database.engine) as session:
        assert session.scalar(select(func.count()).select_from(CentralNode)) == 1
        assert session.scalar(select(func.count()).select_from(MeasurementBus)) == 1
        assert session.scalar(select(func.count()).select_from(ClimateChamber)) == 2
        assert session.scalar(select(func.count()).select_from(MeasurementDevice)) == 31
        assert session.scalar(select(func.count()).select_from(MeasurementChannel)) == 162
        assert session.scalar(select(func.count()).select_from(PhysicalSensor)) == 246
        node = session.scalar(select(CentralNode))
        bus = session.scalar(select(MeasurementBus))
        assert node is not None and node.node_id == DEFAULT_EDGE_NODE_ID
        assert bus is not None
        assert bus.bus_key == DEFAULT_RS485_BUS_KEY
        assert bus.node_id == DEFAULT_EDGE_NODE_ID
        assert bus.baudrate == 9600
        assert bus.data_bits == 8
        assert bus.parity == "N"
        assert bus.stop_bits == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(SecurityAuditEvent)
                .where(SecurityAuditEvent.action == "climate_chamber.catalog.seeded")
            )
            == 2
        )


def test_catalog_api_isolates_kk1_and_kk2(tmp_path: Path) -> None:
    _, _, repository = build_catalog(tmp_path)
    repository.seed_default_catalog(organization_id=ORGANIZATION_ID)
    app = FastAPI()
    app.include_router(create_climate_catalog_router(repository))
    api = TestClient(app)

    chambers = api.get("/api/v1/climate-chambers")
    assert chambers.status_code == 200
    chamber_items = chambers.json()["items"]
    assert [item["code"] for item in chamber_items] == ["KK1", "KK2"]
    assert [item["name"] for item in chamber_items] == [
        "Кліматична камера №1",
        "Кліматична камера №2",
    ]
    assert {item["node_id"] for item in chamber_items} == {DEFAULT_EDGE_NODE_ID}
    assert {item["bus_key"] for item in chamber_items} == {DEFAULT_RS485_BUS_KEY}
    assert len({item["id"] for item in chamber_items}) == 2

    kk1 = api.get("/api/v1/climate-chambers/KK1/equipment")
    kk2 = api.get("/api/climate-chambers/KK2/equipment")
    assert kk1.status_code == 200
    assert kk2.status_code == 200

    kk1_payload = kk1.json()
    kk2_payload = kk2.json()
    assert len(kk1_payload["temperatureControllers"]) == 13
    assert len(kk1_payload["temperatureChannels"]) == 78
    assert len(kk1_payload["energyMeters"]) == 4
    assert [item["designation"] for item in kk1_payload["energyMeters"]] == [
        "W1",
        "W2",
        "W3",
        "W4",
    ]
    assert kk1_payload["temperatureChannels"][0]["channel_id"] == "126-01"
    assert kk1_payload["temperatureChannels"][0]["source_channel_id"] == "126-01"
    assert kk1_payload["temperatureChannels"][0]["logical_sensor_number"] == 197
    assert kk1_payload["temperatureChannels"][-1]["logical_sensor_number"] == 274
    assert kk1_payload["temperatureChannels"][0]["physical_sensors"][0][
        "inventory_number"
    ] == "197"
    assert all(
        item["physical_sensor_count"] == 1
        for item in kk1_payload["temperatureChannels"]
    )

    assert len(kk2_payload["temperatureControllers"]) == 14
    assert len(kk2_payload["temperatureChannels"]) == 84
    assert kk2_payload["energyMeters"] == []
    assert kk2_payload["energyMeterEmptyMessage"] == (
        "До цієї кліматичної камери лічильники електроенергії ще не підключені."
    )
    assert kk2_payload["temperatureChannels"][0]["channel_id"] == "101-01"
    assert kk2_payload["temperatureChannels"][0]["source_channel_id"] == "101-01"
    assert kk2_payload["temperatureChannels"][0]["logical_sensor_number"] == 471
    assert kk2_payload["temperatureChannels"][-1]["logical_sensor_number"] == 554
    assert all(
        item["physical_sensor_count"] == 2
        for item in kk2_payload["temperatureChannels"]
    )
    assert all(
        len(item["physical_sensors"]) == 2
        for item in kk2_payload["temperatureChannels"]
    )
    assert {
        item["channel_id"] for item in kk1_payload["temperatureChannels"]
    }.isdisjoint(
        {item["channel_id"] for item in kk2_payload["temperatureChannels"]}
    )

    missing = api.get("/api/v1/climate-chambers/KK3/equipment")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "climate_chamber_not_found"


def test_chamber_update_is_versioned_and_audited(tmp_path: Path) -> None:
    database, security, repository = build_catalog(tmp_path)
    repository.seed_default_catalog(organization_id=ORGANIZATION_ID)
    app = FastAPI()
    app.include_router(create_climate_catalog_router(repository))
    api = TestClient(app)

    updated = api.patch(
        "/api/v1/climate-chambers/KK1",
        headers={
            "If-Match": 'W/"climate-chamber-v1"',
            "X-Audit-Reason": "Rename chamber for operator display",
        },
        json={"name": "Кліматична камера №1 — лабораторна", "status": "active"},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"climate-chamber-v2"'
    assert updated.json()["version"] == 2
    assert updated.json()["node_id"] == DEFAULT_EDGE_NODE_ID
    assert updated.json()["bus_key"] == DEFAULT_RS485_BUS_KEY

    stale = api.patch(
        "/api/v1/climate-chambers/KK1",
        headers={"If-Match": 'W/"climate-chamber-v1"'},
        json={"name": "Stale update", "status": "active"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "climate_chamber_version_conflict"

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="climate_chamber",
        limit=10,
    )
    update_event = next(item for item in events if item.action == "climate_chamber.updated")
    assert update_event.reason == "Rename chamber for operator display"
    assert update_event.before_snapshot is not None
    assert update_event.after_snapshot is not None
    assert update_event.before_snapshot["version"] == 1
    assert update_event.after_snapshot["version"] == 2

    with Session(database.engine) as session:
        kk1 = session.scalar(
            select(ClimateChamber).where(ClimateChamber.code == "KK1")
        )
        assert kk1 is not None
        assert kk1.name == "Кліматична камера №1 — лабораторна"
