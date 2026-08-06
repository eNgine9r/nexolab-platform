from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementChannel
from app.db import TelemetrySample
from app.live_dashboard.inventory import list_live_dashboard_inventory
from app.live_dashboard.repository import (
    LiveDashboardChannelNotFoundError,
    LiveDashboardRepository,
)
from app.live_dashboard.schemas import LiveDashboardWrite
from app.nodes.models import CentralNode
from tests.live_dashboard_test_support import ORG_A, ORG_B, database_with_inventory


def _payload(channel_id: str) -> LiveDashboardWrite:
    return LiveDashboardWrite.model_validate(
        {
            "name": "Inventory parity",
            "items": [
                {
                    "channel_id": channel_id,
                    "metric": "temperature",
                    "display_unit": "°C",
                }
            ],
        }
    )


def test_inventory_is_organization_scoped_deterministic_and_includes_no_sample_channels(
    tmp_path: Path,
) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)

    first = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_A,
        limit=1,
        offset=0,
    )
    second = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_A,
        limit=1,
        offset=1,
    )
    other = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_B,
        limit=500,
        offset=0,
    )

    assert first.total == second.total == 2
    assert [item.channel_id for item in first.items + second.items] == [
        "a-temperature-01",
        "a-temperature-02",
    ]
    assert all(item.latest is None for item in first.items + second.items)
    assert all(item.quality == "unknown" for item in first.items + second.items)
    assert [item.channel_id for item in other.items] == [
        "b-temperature-01",
        "b-temperature-02",
    ]


def test_inventory_latest_lookup_is_bounded_by_catalog_identity_and_large_history(
    tmp_path: Path,
) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    now = datetime.now(UTC)

    unrelated = [
        {
            "event_id": str(uuid4()),
            "node_id": "unrelated-edge",
            "captured_at": now + timedelta(milliseconds=index),
            "metric": "temperature",
            "value": float(index % 100),
            "unit": "°C",
            "quality": "valid",
            "source": "unrelated-source",
            "equipment_id": "unrelated-equipment",
            "channel_id": f"unrelated-{index % 250}",
            "alarm": None,
            "raw_value": None,
            "raw_status": None,
            "raw_payload": {},
            "raw_payload_retained": True,
            "received_at": now + timedelta(milliseconds=index),
        }
        for index in range(25_000)
    ]
    matching = [
        {
            "event_id": str(uuid4()),
            "node_id": "edge-a",
            "captured_at": now + timedelta(seconds=index),
            "metric": "temperature",
            "value": 2.0 + index,
            "unit": "°C",
            "quality": "valid",
            "source": "dixell-xjp60d",
            "equipment_id": "controller-a",
            "channel_id": "a-temperature-01",
            "alarm": "high" if index == 2 else None,
            "raw_value": None,
            "raw_status": None,
            "raw_payload": {},
            "raw_payload_retained": True,
            "received_at": now + timedelta(seconds=index),
        }
        for index in range(3)
    ]
    with database.engine.begin() as connection:
        connection.execute(TelemetrySample.__table__.insert(), unrelated + matching)

    started = perf_counter()
    page = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_A,
        limit=500,
        offset=0,
    )
    elapsed = perf_counter() - started

    assert elapsed < 8.0
    assert page.total == 2
    by_channel = {item.channel_id: item for item in page.items}
    assert by_channel["a-temperature-01"].latest is not None
    assert by_channel["a-temperature-01"].latest.value == 4.0
    assert by_channel["a-temperature-01"].quality == "valid"
    assert by_channel["a-temperature-01"].alarm == "high"
    assert by_channel["a-temperature-02"].latest is None
    assert by_channel["a-temperature-02"].quality == "unknown"


def test_inventory_and_save_validation_share_active_catalog_eligibility(
    tmp_path: Path,
) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)

    with Session(database.engine) as session:
        with session.begin():
            session.execute(
                update(MeasurementChannel)
                .where(
                    MeasurementChannel.organization_id == ORG_A,
                    MeasurementChannel.channel_id == "a-temperature-02",
                )
                .values(status="inactive")
            )

    page = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_A,
        limit=500,
        offset=0,
    )
    assert [item.channel_id for item in page.items] == ["a-temperature-01"]
    with pytest.raises(LiveDashboardChannelNotFoundError):
        repository.create(
            _payload("a-temperature-02"),
            actor_id="operator-a",
            organization_id=ORG_A,
        )

    with Session(database.engine) as session:
        with session.begin():
            session.execute(
                update(CentralNode)
                .where(
                    CentralNode.organization_id == ORG_A,
                    CentralNode.node_id == "edge-a",
                )
                .values(state="revoked", state_reason="test")
            )

    revoked = list_live_dashboard_inventory(
        repository,
        organization_id=ORG_A,
        limit=500,
        offset=0,
    )
    assert revoked.items == ()
    with pytest.raises(LiveDashboardChannelNotFoundError):
        repository.create(
            _payload("a-temperature-01"),
            actor_id="operator-a",
            organization_id=ORG_A,
        )
