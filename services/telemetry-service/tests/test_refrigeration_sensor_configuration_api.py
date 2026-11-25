from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import Database, TelemetryLatest, TelemetrySample
from app.nodes.models import CentralNode
from app.refrigeration.commissioned_channels import (
    CommissionedTemperatureInventory,
    parse_temperature_inventory,
    section_temperature,
)
from app.refrigeration.lifecycle_repository import PostgresEquipmentLifecycleRepository
from app.refrigeration.structural_api import create_refrigeration_structural_router
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


def build_client(tmp_path: Path, read_commissioned=None) -> tuple[TestClient, Database, SecurityRepository]:
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
    sensor_configuration = PostgresSensorConfigurationRepository(database, read_commissioned=read_commissioned)
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
    app.include_router(
        create_refrigeration_structural_router(
            equipment, PostgresEquipmentLifecycleRepository(database), sensor_configuration,
            layouts, storage, signed_url_seconds=300,
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


def test_active_equipment_can_be_created_without_a_climate_chamber(tmp_path: Path) -> None:
    api, _, _ = build_client(tmp_path)

    response = api.post("/api/v1/equipment", json=equipment_payload(node_id=None))

    assert response.status_code == 201
    assert response.json()["climate_chamber_id"] is None
    assert response.json()["node_id"] is None


def test_commissioned_sections_can_be_placed_without_a_chamber(tmp_path: Path) -> None:
    channels = ("rs485:1-S01", "rs485:7-S02")
    registry = CommissionedTemperatureInventory(
        KK2, tuple(section_temperature(channel) for channel in channels)
    )
    api, database, _ = build_client(tmp_path, lambda: registry)
    created = api.post("/api/v1/equipment", json=equipment_payload(node_id=None))
    equipment_id = created.json()["id"]
    path = f"/api/v1/equipment/{equipment_id}"
    options = api.get(path + "/structural-snapshot").json()["channels"]
    assert [item["channel_id"] for item in options] == list(channels)
    assert all(item["selectable"] and item["latest_value"] is None for item in options)
    assert [item["input_number"] for item in options] == [1, 2]

    first = api.put(
        path + "/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration(("front-01", channels[0], 0.22, 0.31)),
    )
    assert first.status_code == 200, first.text
    assert first.json()["equipment"]["node_id"] == KK2
    assert first.json()["equipment"]["climate_chamber_id"] is None
    reserve = api.put(
        path + "/sensor-configuration",
        headers={"If-Match": first.headers["etag"]},
        json=configuration(("front-01", "rs485:7-S03", 0.22, 0.31), expected_draft_version=2),
    )
    assert reserve.status_code == 422
    replacement = api.put(
        path + "/sensor-configuration",
        headers={"If-Match": first.headers["etag"]},
        json=configuration(("front-01", channels[1], 0.22, 0.31), expected_draft_version=2),
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["draft"]["placements"] == [
        {"sensor_id": channels[1], "x": 0.22, "y": 0.31}
    ]
    assert replacement.json()["bindings"][0]["label"] == first.json()["bindings"][0]["label"]
    with Session(database.engine) as session, session.begin():
        retired = session.scalar(select(EquipmentSensorBinding).where(
            EquipmentSensorBinding.channel_id == channels[0],
        ))
        assert retired.unbound_at is not None
        now = datetime.now(UTC)
        session.add(TelemetryLatest(
            sample_id=1, event_id=str(uuid4()), node_id=KK2, captured_at=now,
            metric="temperature.probe", value=4.5, unit="degC", quality="valid",
            source="dixell-xjp60d-sections", equipment_id="XJP60D-S:rs485:7",
            channel_id=channels[1], received_at=now,
        ))
    reread = api.get(path + "/structural-snapshot").json()
    option = next(item for item in reread["channels"] if item["channel_id"] == channels[1])
    assert option["latest_value"] == 4.5
    card = api.get("/api/v1/equipment").json()["items"][0]
    assert (card["assigned_sensors"], card["online_sensors"], card["average_temperature_c"]) == (1, 1, 4.5)
    assert datetime.fromisoformat(card["sensor_summary_valid_until"]) > now

    registry = None
    during_outage = api.get(path + "/structural-snapshot").json()["channels"]
    retained = next(item for item in during_outage if item["channel_id"] == channels[1])
    assert retained["latest_value"] == 4.5 and retained["selectable"] is False
    assert all(item["channel_id"] != channels[0] for item in during_outage)
    assert retained["sample_state"] == "known"
    assert datetime.fromisoformat(retained["sample_valid_until"]) > now

    with Session(database.engine) as session, session.begin():
        sample = session.scalar(select(TelemetryLatest).where(TelemetryLatest.channel_id == channels[1]))
        sample.captured_at = now - timedelta(hours=1)
    aged_channels = api.get(path + "/structural-snapshot").json()["channels"]
    aged = next(item for item in aged_channels if item["channel_id"] == channels[1])
    assert aged["sample_state"] == "stale"
    assert datetime.fromisoformat(aged["sample_valid_until"]) < now

    with Session(database.engine) as session, session.begin():
        node = session.scalar(select(CentralNode).where(CentralNode.node_id == KK2))
        node.state = "revoked"
        sample = session.scalar(select(TelemetryLatest).where(TelemetryLatest.channel_id == channels[1]))
        sample.captured_at = now
    card = api.get("/api/v1/equipment").json()["items"][0]
    assert (card["assigned_sensors"], card["online_sensors"]) == (1, 0)
    assert card["sensor_summary_valid_until"] is None


def test_registry_channels_cannot_cross_measurement_nodes(tmp_path: Path) -> None:
    channel_id = "rs485:7-S02"
    registry = CommissionedTemperatureInventory(KK2, (section_temperature(channel_id),))
    api, _, _ = build_client(tmp_path, lambda: registry)
    created = api.post("/api/v1/equipment", json=equipment_payload(node_id=KK1))
    equipment_id = created.json()["id"]
    path = f"/api/v1/equipment/{equipment_id}"
    options = api.get(path + "/structural-snapshot").json()["channels"]
    assert channel_id not in [item["channel_id"] for item in options]
    denied = api.put(
        path + "/sensor-configuration", headers={"If-Match": created.headers["etag"]},
        json=configuration(("front-01", channel_id, 0.22, 0.31)),
    )
    assert denied.status_code == 422


def test_sensor_configuration_expands_an_old_passport_with_a_small_slot_count(tmp_path: Path) -> None:
    channels = ("rs485:1-S01", "rs485:7-S02")
    registry = CommissionedTemperatureInventory(
        KK2, tuple(section_temperature(channel) for channel in channels)
    )
    api, _, _ = build_client(tmp_path, lambda: registry)
    created = api.post("/api/v1/equipment", json={**equipment_payload(node_id=None), "total_sensors": 1})
    assert created.status_code == 201, created.text
    assert created.json()["total_sensors"] == 1
    path = f"/api/v1/equipment/{created.json()['id']}"

    response = api.put(
        path + "/sensor-configuration",
        headers={"If-Match": created.headers["etag"]},
        json=configuration(("front-01", channels[0], 0.22, 0.31), ("front-02", channels[1], 0.55, 0.48)),
    )
    assert response.status_code == 200, response.text
    assert response.json()["equipment"]["total_sensors"] == 48
    snapshot = api.get(path + "/structural-snapshot").json()
    assert snapshot["equipment"]["total_sensors"] == 48
    assert {binding["channel_id"] for binding in snapshot["bindings"]} == set(channels)


def test_section_parser_requires_active_parent_and_target() -> None:
    buses = [{"bus_id": "rs485", "protocol": "modbus_rtu", "read_only": True}]
    devices = [{"device_id": f"xjp60d-sections:rs485:{unit}", "device_family": "xjp60d",
                "bus_id": "rs485", "unit_id": unit,
                "lifecycle": "active" if unit != 8 else "discovery_only"}
               for unit in (1, 7, 8)]
    targets = [{"target_id": f"xjp60d-sections:rs485:{unit}-S0{section}",
                "device_id": f"xjp60d-sections:rs485:{unit}",
                "telemetry_channel_id": f"rs485:{unit}-S0{section}",
                "lifecycle": "reserve" if unit == 7 and section > 2 else "active",
                "poll_eligible": True, "function": 3, "metric": "temperature.probe", "unit": "degC"}
               for unit in (1, 7, 8) for section in range(1, 7)]
    inventory = parse_temperature_inventory(
        {"schema_version": 2, "revision": 46, "buses": buses, "devices": devices, "targets": targets},
        {"node_id": KK2, "registry_revision": 46},
    )
    assert [item.channel_id for item in inventory.channels] == [
        *(f"rs485:1-S0{i}" for i in range(1, 7)), "rs485:7-S01", "rs485:7-S02",
    ]


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
