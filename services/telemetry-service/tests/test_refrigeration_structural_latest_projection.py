from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database, TelemetryLatest, TelemetrySample
from app.model_registry import register_models
from app.refrigeration.sensor_configuration_repository import (
    PostgresSensorConfigurationRepository,
)
from app.security.repository import SecurityRepository

ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def test_catalog_latest_values_use_bounded_projection_not_history(tmp_path: Path) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'refrigeration-latest.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="default",
        name="Default organization",
    )
    catalog = PostgresClimateCatalogRepository(database, security_repository=security)
    assert catalog.seed_default_catalog(organization_id=ORGANIZATION_ID).changed is True

    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                TelemetrySample(
                    event_id=str(uuid4()),
                    node_id="edge-01",
                    captured_at=now - timedelta(minutes=1),
                    metric="temperature",
                    value=99.0,
                    unit="degC",
                    quality="valid",
                    source="modbus",
                    equipment_id="xjp60d-106",
                    channel_id="106-03",
                    alarm=None,
                    raw_value=990,
                    raw_status=0,
                    raw_payload={"channel_id": "106-03"},
                    raw_payload_retained=True,
                    received_at=now - timedelta(minutes=1),
                )
            )
            session.add(
                TelemetryLatest(
                    sample_id=42,
                    event_id=str(uuid4()),
                    node_id="edge-01",
                    captured_at=now,
                    metric="temperature",
                    value=2.5,
                    unit="degC",
                    quality="good",
                    source="modbus",
                    equipment_id="xjp60d-106",
                    channel_id="106-03",
                    alarm=None,
                    raw_value=25,
                    raw_status=0,
                    stale_after_seconds=90.0,
                    received_at=now,
                )
            )

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    event.listen(database.engine, "before_cursor_execute", capture_statement)
    try:
        repository = PostgresSensorConfigurationRepository(
            database,
            climate_catalog_repository=catalog,
        )
        node_id, channels = repository.list_climate_chamber_channels(
            "KK2",
            organization_id=ORGANIZATION_ID,
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", capture_statement)

    assert node_id == "edge-01"
    channel = next(item for item in channels if item.channel_id == "106-03")
    assert channel.latest_value == 2.5
    assert channel.quality == "good"
    assert channel.captured_at.replace(tzinfo=UTC) == now
    assert any("telemetry_latest" in statement for statement in statements)
    assert not any("telemetry_samples" in statement for statement in statements)
