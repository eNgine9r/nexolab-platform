from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import TelemetrySample
from app.live_dashboard.repository import (
    LiveDashboardChannelNotFoundError,
    LiveDashboardNotFoundError,
    LiveDashboardRepository,
    LiveDashboardVersionConflictError,
)
from app.live_dashboard.schemas import LiveDashboardWrite
from tests.live_dashboard_test_support import ORG_A, ORG_B, database_with_inventory


def dashboard_payload(
    channels: list[tuple[str, str]],
    *,
    name: str = "Контроль температури",
    refresh_seconds: int = 5,
    time_window: str = "15m",
) -> LiveDashboardWrite:
    return LiveDashboardWrite.model_validate(
        {
            "name": name,
            "description": "Операторський набір каналів",
            "refresh_seconds": refresh_seconds,
            "time_window": time_window,
            "items": [
                {
                    "channel_id": channel_id,
                    "metric": metric,
                    "visualization": "line",
                    "color": "#123ABC",
                    "display_unit": "°C",
                }
                for channel_id, metric in channels
            ],
        }
    )


def test_ordered_items_round_trip_and_stale_writer_is_rejected(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)

    created = repository.create(
        dashboard_payload(
            [
                ("a-temperature-02", "temperature"),
                ("a-temperature-01", "temperature"),
            ]
        ),
        actor_id="operator-a",
        organization_id=ORG_A,
    )
    assert [item.position for item in created.items] == [1, 2]
    assert [item.channel_id for item in created.items] == [
        "a-temperature-02",
        "a-temperature-01",
    ]

    updated = repository.update(
        created.id,
        dashboard_payload(
            [("a-temperature-01", "temperature")],
            name="Оновлений графік",
            refresh_seconds=10,
            time_window="1h",
        ),
        expected_version=1,
        actor_id="operator-a",
        organization_id=ORG_A,
    )
    assert updated.version == 2
    assert updated.refresh_seconds == 10
    assert updated.time_window == "1h"
    assert [item.channel_id for item in updated.items] == ["a-temperature-01"]

    with pytest.raises(LiveDashboardVersionConflictError):
        repository.update(
            created.id,
            dashboard_payload([("a-temperature-02", "temperature")]),
            expected_version=1,
            actor_id="operator-a",
            organization_id=ORG_A,
        )


def test_organization_isolation_and_active_inventory_validation(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)

    created = repository.create(
        dashboard_payload([("a-temperature-01", "temperature")]),
        actor_id="operator-a",
        organization_id=ORG_A,
    )
    with pytest.raises(LiveDashboardNotFoundError):
        repository.get(created.id, organization_id=ORG_B)
    with pytest.raises(LiveDashboardChannelNotFoundError):
        repository.create(
            dashboard_payload([("b-temperature-01", "temperature")]),
            actor_id="operator-a",
            organization_id=ORG_A,
        )


def test_archive_preserves_items_and_telemetry_history(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    created = repository.create(
        dashboard_payload([("a-temperature-01", "temperature")]),
        actor_id="operator-a",
        organization_id=ORG_A,
    )
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                TelemetrySample(
                    event_id=str(uuid4()),
                    node_id="edge-a",
                    captured_at=now,
                    metric="temperature",
                    value=2.5,
                    unit="°C",
                    quality="good",
                    source="test",
                    equipment_id="equipment-a",
                    channel_id="a-temperature-01",
                    alarm=None,
                    raw_value=None,
                    raw_status=None,
                    raw_payload={},
                    raw_payload_retained=True,
                    received_at=now,
                )
            )

    archived = repository.archive(
        created.id,
        expected_version=1,
        actor_id="operator-a",
        organization_id=ORG_A,
    )
    assert archived.status == "archived"
    assert [item.channel_id for item in archived.items] == ["a-temperature-01"]
    assert database.count_samples() == 1
    assert repository.list(
        organization_id=ORG_A,
        include_archived=False,
        limit=50,
        offset=0,
    ).total == 0
    assert repository.list(
        organization_id=ORG_A,
        include_archived=True,
        limit=50,
        offset=0,
    ).total == 1


def test_pagination_is_deterministic(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    for index in range(3):
        repository.create(
            dashboard_payload(
                [("a-temperature-01", "temperature")],
                name=f"Dashboard {index}",
            ),
            actor_id="operator-a",
            organization_id=ORG_A,
        )

    first = repository.list(
        organization_id=ORG_A,
        limit=2,
        offset=0,
    )
    second = repository.list(
        organization_id=ORG_A,
        limit=2,
        offset=2,
    )
    assert first.total == second.total == 3
    assert len(first.items) == 2
    assert len(second.items) == 1
    assert {item.id for item in first.items}.isdisjoint(
        {item.id for item in second.items}
    )
