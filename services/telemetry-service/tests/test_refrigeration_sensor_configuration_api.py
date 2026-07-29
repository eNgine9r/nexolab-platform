from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.nodes.models import CentralNode
from app.refrigeration.equipment_api import create_refrigeration_equipment_router
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.models import EquipmentSensorBinding
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.schemas import RefrigerationEquipmentCreate
from app.refrigeration.sensor_configuration_api import create_sensor_configuration_router
from app.refrigeration.sensor_configuration_repository import PostgresSensorConfigurationRepository
from app.refrigeration.storage import InMemoryObjectStorage
from app.security.repository import SecurityRepository

ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
KK1 = "kk1"
KK2 = "kk2"


def build_client(tmp_path: Path) -> tuple[TestClient, Database, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / 'sensor-configuration.db'}")
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
            for node_id, display_name in ((KK1, "Кліматична камера КК1"), (KK2, "Кліматична камера КК2")):
                session.add(
                    CentralNode(
                        id=str(uuid4()),
                        organization_id=ORGANIZATION_ID,
                        node_id=node_id,
                        display_name=display_name,
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
            for node_id, channel_ids in (
                (KK1, ("kk1-temperature-01", "kk1-temperature-02")),
                (KK2, ("kk2-temperature-01", "kk2-temperature-02", "kk2-humidity-01")),
            ):
                for index, channel_id in enumerate(channel_ids, start=1):
                    metric = "humidity" if "humidity" in channel_id else "temperature"
                    session.add(
                        TelemetrySample(
                            event_id=str(uuid4()),
                            node_id=node_id,
                            captured_at=now,
                            metric=metric,
                            value=float(index + 1),
                            unit="%RH" if metric == "humidity" else "degC",
                            quality="valid",
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
    sensor_configuration = PostgresSensorConfigurationRepository(database)
    storage = InMemoryObjectStorage()
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
            storage,
            signed_url_seconds=300,
            security_repository=security,
        )
    )
    return TestClient(app), database, security


def equipment_payload(*, node_id: str | None = KK2) -> dict[str, object]:
    return {
        "code": "CS-KK2-BATCH-01",
        "name": "Вітрина КК2",
        "location": "Лабораторія 2 · КК2",
        "laboratory": "Лабораторія 2",
        "zone": "КК2",
        "node_id": node_id,
        "equipment_type": "Холодильна вітрина",
        "manufacturer": "NEXOLAB",
        "model": "NX-KK2",
        "serial_number": "NX-KK2-0001",
        "temperature_class": "3M1 (0…+5 °C)",
        "installed_at": "2026-07-29",
        "serviced_at": None,
        "lifecycle_status": "active",
        "total_sensors": 48,
    }


def configuration(
    *items: tuple[str, str, float, float],
    expected_draft_version: int = 1,
) -> dict[str, object]:
    return {
        "expected_draft_version": expected_draft_version,
        "bindings": [
            {
                "slot_key": slot_key,
                "channel_id": channel_id,
                "label": slot_key.upper(),
                "side": "front",
                "shelf": 1,
                "position": index,
                "x": x,
                "y": y,
            }
            for index, (slot_key, channel_id, x, y) in enumerate(items, start=1)
        ],
    }


def test_active_equipment_requires_a_climate_chamber(tmp_path: Path) -> None:
    api, _, _ = build_client(tmp_path)

    response = api.post("/api/v1/equipment", json=equipment_payload(node_id=None))

    assert response.status_code == 422
    assert "climate chamber is required" in response.text


def test_channels_are_scoped_to_the_selected_climate_chamber(tmp_path: Path) -> None:
    api, _, _ = build_client(tmp_path)

    kk2 = api.get(f"/api/v1/equipment/options/nodes/{KK2}/channels")

    assert kk2.status_code == 200
    assert kk2.json()["node_id"] == KK2
    channel_ids = [item["channel_id"] for item in kk2.json()["items"]]
    assert channel_ids == [
        "kk2-humidity-01",
        "kk2-temperature-01",
        "kk2-temperature-02",
    ]
    assert all(not channel_id.startswith("kk1-") for channel_id in channel_ids)


def test_replaces_bindings_and_coordinates_in_one_atomic_mutation(tmp_path: Path) -> None:
    api, database, security = build_client(tmp_path)
    created = api.post("/api/v1/equipment", json=equipment_payload())
    assert created.status_code == 201
    equipment_id = created.json()["id"]

    configured = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Configure the complete KK2 measurement layout",
        },
        json=configuration(
            ("front-01", "kk2-temperature-01", 0.22, 0.31),
            ("front-02", "kk2-humidity-01", 0.68, 0.33),
        ),
    )

    assert configured.status_code == 200
    assert configured.headers["etag"] == 'W/"equipment-v2"'
    assert configured.json()["equipment"]["version"] == 2
    assert configured.json()["draft"]["version"] == 2
    assert configured.json()["draft"]["placements"] == [
        {"sensor_id": "kk2-temperature-01", "x": 0.22, "y": 0.31},
        {"sensor_id": "kk2-humidity-01", "x": 0.68, "y": 0.33},
    ]
    assert [item["channel_id"] for item in configured.json()["bindings"]] == [
        "kk2-temperature-01",
        "kk2-humidity-01",
    ]

    stale = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration(
            ("front-01", "kk2-temperature-02", 0.25, 0.35),
            expected_draft_version=1,
        ),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "equipment_version_conflict"

    replaced = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={"If-Match": configured.headers["etag"]},
        json=configuration(
            ("front-01", "kk2-temperature-02", 0.26, 0.36),
            expected_draft_version=2,
        ),
    )
    assert replaced.status_code == 200
    assert replaced.headers["etag"] == 'W/"equipment-v3"'
    assert replaced.json()["draft"]["version"] == 3
    assert [item["channel_id"] for item in replaced.json()["bindings"]] == [
        "kk2-temperature-02"
    ]

    with Session(database.engine) as session:
        active = list(
            session.scalars(
                select(EquipmentSensorBinding).where(
                    EquipmentSensorBinding.equipment_id == equipment_id,
                    EquipmentSensorBinding.unbound_at.is_(None),
                )
            )
        )
        history = list(
            session.scalars(
                select(EquipmentSensorBinding).where(
                    EquipmentSensorBinding.equipment_id == equipment_id
                )
            )
        )
    assert [item.channel_id for item in active] == ["kk2-temperature-02"]
    assert len(history) == 3
    assert len([item for item in history if item.unbound_at is not None]) == 2

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="refrigeration_sensor_configuration",
        entity_id=equipment_id,
        limit=10,
    )
    assert [event.action for event in events] == [
        "equipment.sensor_configuration.updated",
        "equipment.sensor_configuration.updated",
    ]


def test_bound_channel_remains_visible_when_its_latest_sample_is_absent(tmp_path: Path) -> None:
    api, database, _ = build_client(tmp_path)
    created = api.post("/api/v1/equipment", json=equipment_payload())
    equipment_id = created.json()["id"]
    configured = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration(("front-01", "kk2-temperature-01", 0.22, 0.31)),
    )
    assert configured.status_code == 200

    with Session(database.engine) as session:
        with session.begin():
            session.execute(
                delete(TelemetrySample).where(
                    TelemetrySample.node_id == KK2,
                    TelemetrySample.channel_id == "kk2-temperature-01",
                )
            )

    channels = api.get(f"/api/v1/equipment/options/nodes/{KK2}/channels")
    item = next(
        candidate
        for candidate in channels.json()["items"]
        if candidate["channel_id"] == "kk2-temperature-01"
    )
    assert item["is_bound"] is True
    assert item["bound_equipment_id"] == equipment_id
    assert item["latest_value"] is None
    assert item["quality"] == "no-data"


def test_batch_payload_rejects_duplicate_channels_before_repository_mutation(tmp_path: Path) -> None:
    api, _, _ = build_client(tmp_path)
    created = api.post("/api/v1/equipment", json=equipment_payload())
    equipment_id = created.json()["id"]

    duplicate = api.put(
        f"/api/v1/equipment/{equipment_id}/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration(
            ("front-01", "kk2-temperature-01", 0.2, 0.3),
            ("front-02", "kk2-temperature-01", 0.6, 0.3),
        ),
    )

    assert duplicate.status_code == 422
    assert "duplicate channel ids" in duplicate.text
