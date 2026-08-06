from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
)
from app.db import Database
from app.nodes.models import CentralNode
from app.security.repository import SecurityRepository


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


def database_with_inventory(
    tmp_path: Path,
    *,
    filename: str = "live-dashboard.db",
) -> tuple[Database, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / filename}")
    database.create_schema()
    security = SecurityRepository(database)
    for organization_id, slug in ((ORG_A, "org-a"), (ORG_B, "org-b")):
        security.provision_organization(
            organization_id=organization_id,
            slug=slug,
            name=slug.upper(),
        )
    provision_inventory(database, ORG_A, "a")
    provision_inventory(database, ORG_B, "b")
    return database, security


def provision_inventory(
    database: Database,
    organization_id: str,
    suffix: str,
) -> None:
    now = datetime.now(UTC)
    node_id = f"edge-{suffix}"
    bus_id = str(uuid4())
    chamber_id = str(uuid4())
    device_id = str(uuid4())
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    node_id=node_id,
                    display_name=f"Edge {suffix}",
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
            session.add(
                MeasurementBus(
                    id=bus_id,
                    organization_id=organization_id,
                    node_id=node_id,
                    bus_key=f"rs485-{suffix}",
                    display_name=f"RS-485 {suffix}",
                    protocol="modbus_rtu",
                    port=f"/dev/serial/by-id/test-{suffix}",
                    baudrate=9600,
                    data_bits=8,
                    parity="N",
                    stop_bits=1,
                    status="active",
                    version=1,
                    created_by="test-suite",
                    updated_by="test-suite",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ClimateChamber(
                    id=chamber_id,
                    organization_id=organization_id,
                    bus_id=bus_id,
                    code=f"KK-{suffix.upper()}",
                    name=f"Камера {suffix}",
                    display_order=1,
                    status="active",
                    version=1,
                    created_by="test-suite",
                    updated_by="test-suite",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                MeasurementDevice(
                    id=device_id,
                    organization_id=organization_id,
                    climate_chamber_id=chamber_id,
                    bus_id=bus_id,
                    business_key=f"controller-{suffix}",
                    device_type="temperature_controller",
                    manufacturer="Test",
                    model="XJP60D",
                    unit_id=1,
                    display_name=f"Controller {suffix}",
                    designation=None,
                    connection_status="connected",
                    status="active",
                    measured_parameters=[],
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add_all(
                [
                    MeasurementChannel(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        climate_chamber_id=chamber_id,
                        bus_id=bus_id,
                        device_id=device_id,
                        channel_id=f"{suffix}-temperature-01",
                        source_channel_id=f"{suffix}-source-01",
                        channel_number=1,
                        logical_sensor_number=1,
                        display_name=f"Temperature 1 {suffix}",
                        physical_sensor_count=1,
                        metric_type="temperature",
                        unit="°C",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    ),
                    MeasurementChannel(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        climate_chamber_id=chamber_id,
                        bus_id=bus_id,
                        device_id=device_id,
                        channel_id=f"{suffix}-temperature-02",
                        source_channel_id=f"{suffix}-source-02",
                        channel_number=2,
                        logical_sensor_number=2,
                        display_name=f"Temperature 2 {suffix}",
                        physical_sensor_count=1,
                        metric_type="temperature",
                        unit="°C",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
