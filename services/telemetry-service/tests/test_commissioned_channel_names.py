"""Read-only commissioned inventory and organization-scoped presentation labels."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.models import CentralNode
from app.refrigeration.channel_labels import (
    ChannelNameStore,
    CommissionedChannelName,
    create_channel_names_router,
)
from app.refrigeration.commissioned_channels import (
    CommissionedTemperatureInventory, section_temperature,
)
from app.security.authorization import Permission
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository

ORG = "00000000-0000-0000-0000-000000000001"
NODE = "edge-01"


def rig(tmp_path: Path, *, unavailable: bool = False):
    db = Database(f"sqlite:///{tmp_path / 'channels.db'}")
    db.create_schema()
    security = SecurityRepository(db)
    security.provision_organization(organization_id=ORG, slug="nexolab", name="NEXOLAB")
    now = datetime.now(UTC)
    with Session(db.engine) as session:
        with session.begin():
            session.add(CentralNode(
                id=str(uuid4()), organization_id=ORG, node_id=NODE,
                display_name="Edge 01", state="active", state_reason="test",
                clock_warning_ms=30000, clock_critical_ms=120000, clock_status="ok",
                created_by="test", created_at=now, updated_at=now,
            ))
    channels = tuple(
        section_temperature(f"rs485-sdm120:{unit}-S0{input_number}")
        for unit, length in ((1, 6), (7, 2))
        for input_number in range(1, length + 1)
    )
    assert all(channels)
    inventory = CommissionedTemperatureInventory(NODE, channels)
    store = ChannelNameStore(
        db, read_commissioned=(lambda: None if unavailable else inventory),
        commissioned_organization_id=ORG,
    )
    dependencies = SecurityDependencies(
        security, mode="disabled", authenticator=None, default_organization_id=ORG,
    )
    api = FastAPI()
    api.include_router(create_channel_names_router(store, dependencies, security))
    return TestClient(api), db, store, security


def test_eight_active_inputs_and_stable_identifier_with_rename_and_reset(tmp_path: Path) -> None:
    client, db, _store, _security = rig(tmp_path)
    url = "/api/v1/equipment/commissioned-channels"
    first = client.get(url)
    assert first.status_code == 200
    assert first.json()["state"] == "available"
    items = first.json()["items"]
    assert len(items) == 8
    assert len([item for item in items if ":1-S" in item["channel_id"]]) == 6
    assert len([item for item in items if ":7-S" in item["channel_id"]]) == 2
    channel_id = "rs485-sdm120:1-S01"
    update_url = url + "/" + channel_id + "/display-name"
    changed = client.put(update_url, json={"node_id": NODE, "display_name": "Температура продукту"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["channel_id"] == channel_id
    assert changed.json()["display_name"] == "Температура продукту"
    assert next(item for item in client.get(url).json()["items"] if item["channel_id"] == channel_id)["display_name"] == "Температура продукту"
    assert client.put(update_url, json={"node_id": NODE, "display_name": None}).status_code == 200
    assert next(item for item in client.get(url).json()["items"] if item["channel_id"] == channel_id)["display_name"] == "Dixell №1 · Вхід 1"
    with Session(db.engine) as session:
        assert session.scalars(select(CommissionedChannelName)).all() == []


def test_unavailable_inventory_is_not_equated_with_inactive(tmp_path: Path) -> None:
    client, _, _, _ = rig(tmp_path, unavailable=True)
    url = "/api/v1/equipment/commissioned-channels"
    result = client.get(url)
    assert result.status_code == 200
    assert result.json() == {"state": "unavailable", "node_id": None, "items": []}
    changed = client.put(url + "/rs485-sdm120:1-S01/display-name", json={
        "node_id": NODE, "display_name": "Test",
    })
    assert changed.status_code == 503


def test_foreign_node_and_uncommissioned_input_are_rejected(tmp_path: Path) -> None:
    client, _, store, _ = rig(tmp_path)
    url = "/api/v1/equipment/commissioned-channels/"
    assert client.put(url + "rs485-sdm120:1-S01/display-name", json={
        "node_id": "other-node", "display_name": "Unsafe",
    }).status_code == 404
    assert client.put(url + "rs485-sdm120:7-S03/display-name", json={
        "node_id": NODE, "display_name": "Uncommissioned",
    }).status_code == 404
    assert store.list("00000000-0000-0000-0000-000000000002").state == "unavailable"


def test_manage_permission_denial(tmp_path: Path) -> None:
    client, _, store, security = rig(tmp_path)
    class ReadOnlySecurity:
        def authorized_request(self, permission: Permission):
            def check():
                if permission == Permission.MANAGE_EQUIPMENT:
                    raise HTTPException(status_code=403, detail="equipment.manage required")
                return None
            return check
    api = FastAPI()
    api.include_router(create_channel_names_router(store, ReadOnlySecurity(), security))
    response = TestClient(api).put(
        "/api/v1/equipment/commissioned-channels/rs485-sdm120:1-S01/display-name",
        json={"node_id": NODE, "display_name": "Blocked"},
    )
    assert response.status_code == 403


def test_live_inventory_uses_name_without_rewriting_telemetry_identity(tmp_path: Path) -> None:
    from app.db import TelemetryLatest
    from app.live_dashboard.inventory import list_live_dashboard_inventory
    from app.live_dashboard.repository import LiveDashboardRepository

    client, db, _, _ = rig(tmp_path)
    now = datetime.now(UTC)
    channel_id = "rs485-sdm120:1-S01"
    equipment_id = section_temperature(channel_id).equipment_id
    with Session(db.engine) as session:
        with session.begin():
            session.add(TelemetryLatest(
                sample_id=1, event_id=str(uuid4()), node_id=NODE,
                equipment_id=equipment_id, channel_id=channel_id,
                metric="temperature.probe", value=3.5, unit="degC",
                quality="valid", source="dixell", alarm=None,
                captured_at=now, received_at=now,
            ))
    inventory = LiveDashboardRepository(db)
    initial = list_live_dashboard_inventory(
        inventory, organization_id=ORG, include_observed=True, limit=100, offset=0,
    )
    assert next(item for item in initial.items if item.channel_id == channel_id).channel_name == "Dixell №1 · Вхід 1"
    response = client.put(
        "/api/v1/equipment/commissioned-channels/" + channel_id + "/display-name",
        json={"node_id": NODE, "display_name": "Продукт зліва"},
    )
    assert response.status_code == 200, response.text
    after = list_live_dashboard_inventory(
        inventory, organization_id=ORG, include_observed=True, limit=100, offset=0,
    )
    renamed = next(item for item in after.items if item.channel_id == channel_id)
    assert renamed.channel_name == "Продукт зліва"
    assert renamed.node_id == NODE
    assert renamed.equipment_id == equipment_id
    assert renamed.latest is not None and renamed.latest.value == 3.5
    with Session(db.engine) as session:
        sample = session.scalar(select(TelemetryLatest).where(TelemetryLatest.channel_id == channel_id))
        assert sample is not None and sample.value == 3.5
