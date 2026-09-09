from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
    PhysicalSensor,
)
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.climate_catalog.seed import _seed_catalogs
from app.db import Database
from app.nodes.models import CentralNode
from app.security.repository import SecurityRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for KK2 catalog migration validation",
)


def _alembic(service_root: Path, database_url: str, *args: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=service_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_isolated_database() -> tuple[str, object, str]:
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"nexolab_kk2_{uuid4().hex[:12]}"
    admin_url = source_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    return database_url, admin_engine, database_name


def _drop_isolated_database(admin_engine: object, database_name: str) -> None:
    engine = admin_engine
    with engine.connect() as connection:  # type: ignore[attr-defined]
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    engine.dispose()  # type: ignore[attr-defined]


def _insert_legacy_kk2(database: Database, organization_id: str) -> tuple[str, str]:
    now = datetime.now(UTC)
    SecurityRepository(database).provision_organization(
        organization_id=organization_id,
        slug=f"kk2-migration-{uuid4().hex[:12]}",
        name="KK2 migration acceptance",
    )
    node_id = str(uuid4())
    bus_id = str(uuid4())
    chamber_id = str(uuid4())
    retained_a_id = ""
    deleted_b_id = ""

    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=node_id,
                    organization_id=organization_id,
                    node_id="edge-01",
                    display_name="NEXOLAB Edge 01",
                    state="active",
                    state_reason="KK2 migration fixture",
                    clock_warning_ms=30_000,
                    clock_critical_ms=120_000,
                    last_seen_at=None,
                    last_clock_offset_ms=None,
                    clock_status="unknown",
                    clock_observed_at=None,
                    created_by="test:kk2-migration",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                MeasurementBus(
                    id=bus_id,
                    organization_id=organization_id,
                    node_id="edge-01",
                    bus_key="rs485-main-01",
                    display_name="RS-485 main",
                    protocol="modbus_rtu",
                    port="/dev/serial/by-id/test",
                    baudrate=9600,
                    data_bits=8,
                    parity="N",
                    stop_bits=1,
                    status="active",
                    version=1,
                    created_by="test:kk2-migration",
                    updated_by="test:kk2-migration",
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
                    code="KK2",
                    name="Кліматична камера №2",
                    display_order=2,
                    status="active",
                    version=1,
                    created_by="test:kk2-migration",
                    updated_by="test:kk2-migration",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()

            for unit_id in range(101, 115):
                device_id = str(uuid4())
                session.add(
                    MeasurementDevice(
                        id=device_id,
                        organization_id=organization_id,
                        climate_chamber_id=chamber_id,
                        bus_id=bus_id,
                        business_key=f"DIXELL-{unit_id}",
                        device_type="temperature_controller",
                        manufacturer="Dixell",
                        model="XJP60D",
                        unit_id=unit_id,
                        display_name=f"Dixell №{unit_id}",
                        designation=None,
                        connection_status="unknown",
                        status="active",
                        measured_parameters=[{"metric": "temperature.probe", "unit": "degC"}],
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.flush()
                for input_number in range(1, 7):
                    channel_key = f"{unit_id:03d}-{input_number:02d}"
                    logical = 471 + (unit_id - 101) * 6 + (input_number - 1)
                    channel_id = str(uuid4())
                    session.add(
                        MeasurementChannel(
                            id=channel_id,
                            organization_id=organization_id,
                            climate_chamber_id=chamber_id,
                            bus_id=bus_id,
                            device_id=device_id,
                            channel_id=channel_key,
                            source_channel_id=channel_key,
                            channel_number=input_number,
                            logical_sensor_number=logical,
                            display_name=f"Dixell №{unit_id}_{input_number}",
                            physical_sensor_count=2,
                            metric_type="temperature.probe",
                            unit="degC",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    session.flush()
                    a_id = str(uuid4())
                    b_id = str(uuid4())
                    preserve = unit_id == 101 and input_number == 1
                    session.add_all(
                        [
                            PhysicalSensor(
                                id=a_id,
                                organization_id=organization_id,
                                climate_chamber_id=chamber_id,
                                channel_id=channel_id,
                                sensor_position="A",
                                inventory_number=f"{logical}-A",
                                serial_number="KK2-A-PRESERVE" if preserve else None,
                                calibration_status="current" if preserve else "untracked",
                                status="active",
                                version=3 if preserve else 1,
                                created_at=now,
                                updated_at=now,
                            ),
                            PhysicalSensor(
                                id=b_id,
                                organization_id=organization_id,
                                climate_chamber_id=chamber_id,
                                channel_id=channel_id,
                                sensor_position="B",
                                inventory_number=f"{logical}-B",
                                serial_number=None,
                                calibration_status="untracked",
                                status="active",
                                version=1,
                                created_at=now,
                                updated_at=now,
                            ),
                        ]
                    )
                    if preserve:
                        retained_a_id = a_id
                        deleted_b_id = b_id
            session.flush()

    assert retained_a_id and deleted_b_id
    return retained_a_id, deleted_b_id


def test_kk2_legacy_ab_catalog_migrates_to_numeric_panel_inventory() -> None:
    service_root = Path(__file__).resolve().parents[1]
    database_url, admin_engine, database_name = _create_isolated_database()
    database: Database | None = None
    try:
        _alembic(service_root, database_url, "upgrade", "20260902_0031")
        database = Database(database_url)
        organization_id = str(uuid4())
        retained_a_id, deleted_b_id = _insert_legacy_kk2(database, organization_id)

        with Session(database.engine) as session:
            legacy_101_01 = session.scalar(
                select(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.channel_id == "101-01",
                )
            )
            assert legacy_101_01 is not None
            retained_channel_id = legacy_101_01.id
            assert legacy_101_01.physical_sensor_count == 2

        database.dispose()
        database = None
        _alembic(service_root, database_url, "upgrade", "head")
        database = Database(database_url)

        with Session(database.engine) as session:
            corrected_101_01 = session.scalar(
                select(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.channel_id == "101-01",
                )
            )
            assert corrected_101_01 is not None
            assert corrected_101_01.id == retained_channel_id
            assert corrected_101_01.logical_sensor_number == 471
            assert corrected_101_01.physical_sensor_count == 1

            retained = session.get(PhysicalSensor, retained_a_id)
            assert retained is not None
            assert retained.inventory_number == "471"
            assert retained.serial_number == "KK2-A-PRESERVE"
            assert retained.calibration_status == "current"
            assert retained.version == 4
            assert session.get(PhysicalSensor, deleted_b_id) is None

            kk2 = session.scalar(
                select(ClimateChamber).where(
                    ClimateChamber.organization_id == organization_id,
                    ClimateChamber.code == "KK2",
                )
            )
            assert kk2 is not None
            assert session.scalar(
                select(func.count()).select_from(MeasurementDevice).where(
                    MeasurementDevice.organization_id == organization_id,
                    MeasurementDevice.climate_chamber_id == kk2.id,
                    MeasurementDevice.device_type == "temperature_controller",
                )
            ) == 14
            assert session.scalar(
                select(func.count()).select_from(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.climate_chamber_id == kk2.id,
                )
            ) == 84
            assert session.scalar(
                select(func.count()).select_from(PhysicalSensor).where(
                    PhysicalSensor.organization_id == organization_id,
                    PhysicalSensor.climate_chamber_id == kk2.id,
                )
            ) == 84

        seeded = _seed_catalogs(
            database,
            default_organization_id=str(uuid4()),
        )
        assert seeded.devices_created == 22  # K96..K100 plus 13 KK1 controllers and four LE-01MP meters.
        assert seeded.channels_created == 108  # 30 KK2 plus 78 KK1 channels.
        assert seeded.physical_sensors_created == 108

        with Session(database.engine) as session:
            kk2 = session.scalar(
                select(ClimateChamber).where(
                    ClimateChamber.organization_id == organization_id,
                    ClimateChamber.code == "KK2",
                )
            )
            assert kk2 is not None
            assert session.scalar(
                select(func.count()).select_from(MeasurementDevice).where(
                    MeasurementDevice.organization_id == organization_id,
                    MeasurementDevice.climate_chamber_id == kk2.id,
                    MeasurementDevice.device_type == "temperature_controller",
                )
            ) == 19
            assert session.scalar(
                select(func.count()).select_from(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.climate_chamber_id == kk2.id,
                )
            ) == 114
            assert session.scalar(
                select(func.count()).select_from(PhysicalSensor).where(
                    PhysicalSensor.organization_id == organization_id,
                    PhysicalSensor.climate_chamber_id == kk2.id,
                )
            ) == 114

            first_channel = session.scalar(
                select(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.channel_id == "96-01",
                )
            )
            assert first_channel is not None
            assert first_channel.logical_sensor_number == 441
            first_sensor = session.scalar(
                select(PhysicalSensor).where(
                    PhysicalSensor.organization_id == organization_id,
                    PhysicalSensor.channel_id == first_channel.id,
                )
            )
            assert first_sensor is not None
            assert first_sensor.inventory_number == "441"

            last_channel = session.scalar(
                select(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.channel_id == "114-06",
                )
            )
            assert last_channel is not None
            assert last_channel.logical_sensor_number == 554
            last_sensor = session.scalar(
                select(PhysicalSensor).where(
                    PhysicalSensor.organization_id == organization_id,
                    PhysicalSensor.channel_id == last_channel.id,
                )
            )
            assert last_sensor is not None
            assert last_sensor.inventory_number == "554"
    finally:
        if database is not None:
            database.dispose()
        _drop_isolated_database(admin_engine, database_name)


def test_kk2_migration_refuses_synthetic_b_sensor_with_user_metadata() -> None:
    service_root = Path(__file__).resolve().parents[1]
    database_url, admin_engine, database_name = _create_isolated_database()
    database: Database | None = None
    try:
        _alembic(service_root, database_url, "upgrade", "20260902_0031")
        database = Database(database_url)
        organization_id = str(uuid4())
        retained_a_id, protected_b_id = _insert_legacy_kk2(database, organization_id)

        with Session(database.engine) as session:
            with session.begin():
                protected_b = session.get(PhysicalSensor, protected_b_id)
                assert protected_b is not None
                protected_b.serial_number = "USER-METADATA-MUST-NOT-BE-DELETED"
                protected_b.version = 2

        database.dispose()
        database = None
        environment = {**os.environ, "DATABASE_URL": database_url}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=service_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "synthetic A/B sensor rows contain non-reconcilable state" in (
            result.stdout + result.stderr
        )

        database = Database(database_url)
        with database.engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                "20260902_0031"
            )
        with Session(database.engine) as session:
            retained_a = session.get(PhysicalSensor, retained_a_id)
            protected_b = session.get(PhysicalSensor, protected_b_id)
            assert retained_a is not None and retained_a.inventory_number == "471-A"
            assert protected_b is not None
            assert protected_b.inventory_number == "471-B"
            assert protected_b.serial_number == "USER-METADATA-MUST-NOT-BE-DELETED"
    finally:
        if database is not None:
            database.dispose()
        _drop_isolated_database(admin_engine, database_name)
