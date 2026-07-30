from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.domain import (
    CLIMATE_CHAMBERS,
    MeasurementDeviceType,
    iter_temperature_channels,
)
from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementChannel,
    MeasurementDevice,
)
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.nodes.models import CentralNode
from app.security.models import SecurityOrganization
from app.sessions.telemetry_attribution import SessionAwareDatabase


SEED_ACTOR = "system:climate-catalog-seed"


def main() -> int:
    settings = Settings()
    database = SessionAwareDatabase(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    organization_id = settings.auth_default_organization_id
    try:
        organization_created = _ensure_default_organization(
            database,
            organization_id=organization_id,
        )
        nodes_created = _ensure_default_nodes(
            database,
            organization_id=organization_id,
        )
        chambers_created = _ensure_default_chambers(
            database,
            organization_id=organization_id,
        )
        devices_created = _ensure_default_devices(
            database,
            organization_id=organization_id,
        )
        channels_created = _ensure_default_channels(
            database,
            organization_id=organization_id,
        )
        result = PostgresClimateCatalogRepository(database).seed_default_catalog(
            organization_id=organization_id,
            actor_subject=SEED_ACTOR,
        )
        changed = any(
            (
                organization_created,
                nodes_created,
                chambers_created,
                devices_created,
                channels_created,
                result.changed,
            )
        )
        print(
            json.dumps(
                {
                    "status": "skipped" if result.skipped else "seeded",
                    "changed": changed,
                    "organization_created": organization_created,
                    "nodes_created": nodes_created + result.nodes_created,
                    "chambers_created": chambers_created + result.chambers_created,
                    "devices_created": devices_created + result.devices_created,
                    "channels_created": channels_created + result.channels_created,
                    "physical_sensors_created": result.physical_sensors_created,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.dispose()


def _ensure_default_organization(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> bool:
    with Session(database.engine) as session:
        with session.begin():
            organization = session.get(SecurityOrganization, organization_id)
            if organization is not None:
                return False
            session.add(
                SecurityOrganization(
                    id=organization_id,
                    slug="default",
                    name="NEXOLAB",
                    is_active=True,
                )
            )
            return True


def _ensure_default_nodes(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> int:
    now = datetime.now(UTC)
    created = 0
    with Session(database.engine) as session:
        with session.begin():
            existing = {
                item.node_id
                for item in session.scalars(
                    select(CentralNode).where(
                        CentralNode.organization_id == organization_id,
                        CentralNode.node_id.in_(
                            [definition.node_id for definition in CLIMATE_CHAMBERS]
                        ),
                    )
                )
            }
            for definition in CLIMATE_CHAMBERS:
                if definition.node_id in existing:
                    continue
                session.add(
                    CentralNode(
                        id=_stable_uuid(
                            f"central-node:{organization_id}:{definition.node_id}"
                        ),
                        organization_id=organization_id,
                        node_id=definition.node_id,
                        display_name=definition.name,
                        state="active",
                        state_reason="Created by climate chamber catalog seed",
                        clock_warning_ms=30_000,
                        clock_critical_ms=120_000,
                        last_seen_at=None,
                        last_clock_offset_ms=None,
                        clock_status="unknown",
                        clock_observed_at=None,
                        created_by=SEED_ACTOR,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1
    return created


def _ensure_default_chambers(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> int:
    now = datetime.now(UTC)
    created = 0
    with Session(database.engine) as session:
        with session.begin():
            existing = {
                item.code: item
                for item in session.scalars(
                    select(ClimateChamber).where(
                        ClimateChamber.organization_id == organization_id
                    )
                )
            }
            for definition in CLIMATE_CHAMBERS:
                code = definition.code.value
                if code in existing:
                    continue
                session.add(
                    ClimateChamber(
                        id=_stable_uuid(
                            f"climate-chamber:{organization_id}:{code}"
                        ),
                        organization_id=organization_id,
                        node_id=definition.node_id,
                        code=code,
                        name=definition.name,
                        display_order=definition.display_order,
                        status="active",
                        version=1,
                        created_by=SEED_ACTOR,
                        updated_by=SEED_ACTOR,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1
    return created


def _ensure_default_devices(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> int:
    now = datetime.now(UTC)
    created = 0
    with Session(database.engine) as session:
        with session.begin():
            chambers = {
                item.code: item
                for item in session.scalars(
                    select(ClimateChamber).where(
                        ClimateChamber.organization_id == organization_id
                    )
                )
            }
            existing = {
                item.business_key
                for item in session.scalars(
                    select(MeasurementDevice).where(
                        MeasurementDevice.organization_id == organization_id
                    )
                )
            }
            for definition in CLIMATE_CHAMBERS:
                code = definition.code.value
                chamber = chambers[code]
                for unit_id in range(
                    definition.controller_start,
                    definition.controller_end + 1,
                ):
                    business_key = f"{code}-DIXELL-{unit_id}"
                    if business_key in existing:
                        continue
                    session.add(
                        MeasurementDevice(
                            id=_stable_uuid(
                                f"measurement-device:{organization_id}:{business_key}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            business_key=business_key,
                            device_type=(
                                MeasurementDeviceType.TEMPERATURE_CONTROLLER.value
                            ),
                            manufacturer="Dixell",
                            model="Dixell temperature controller",
                            unit_id=unit_id,
                            display_name=f"Dixell №{unit_id}",
                            designation=None,
                            connection_status="unknown",
                            status="active",
                            measured_parameters=[
                                {"metric": "temperature", "unit": "degC"}
                            ],
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    existing.add(business_key)
                    created += 1

                for meter in definition.energy_meters:
                    business_key = f"{code}-ENERGY-{meter.designation}"
                    if business_key in existing:
                        continue
                    session.add(
                        MeasurementDevice(
                            id=_stable_uuid(
                                f"measurement-device:{organization_id}:{business_key}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            business_key=business_key,
                            device_type=MeasurementDeviceType.ENERGY_METER.value,
                            manufacturer="F&F",
                            model="LE-01MP",
                            unit_id=meter.unit_id,
                            display_name=(
                                f"{meter.designation} — LE-01MP №{meter.unit_id}"
                            ),
                            designation=meter.designation,
                            connection_status="unknown",
                            status="active",
                            measured_parameters=[
                                {"metric": "active_energy", "unit": "kWh"},
                                {"metric": "active_power", "unit": "W"},
                            ],
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    existing.add(business_key)
                    created += 1
    return created


def _ensure_default_channels(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> int:
    now = datetime.now(UTC)
    created = 0
    with Session(database.engine) as session:
        with session.begin():
            chambers = {
                item.code: item
                for item in session.scalars(
                    select(ClimateChamber).where(
                        ClimateChamber.organization_id == organization_id
                    )
                )
            }
            devices = {
                item.business_key: item
                for item in session.scalars(
                    select(MeasurementDevice).where(
                        MeasurementDevice.organization_id == organization_id,
                        MeasurementDevice.device_type
                        == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value,
                    )
                )
            }
            existing = {
                item.channel_id
                for item in session.scalars(
                    select(MeasurementChannel).where(
                        MeasurementChannel.organization_id == organization_id
                    )
                )
            }
            for definition in CLIMATE_CHAMBERS:
                code = definition.code.value
                chamber = chambers[code]
                for channel_definition in iter_temperature_channels(definition.code):
                    if channel_definition.channel_id in existing:
                        continue
                    device_key = (
                        f"{code}-DIXELL-"
                        f"{channel_definition.controller_unit_id}"
                    )
                    session.add(
                        MeasurementChannel(
                            id=_stable_uuid(
                                "measurement-channel:"
                                f"{organization_id}:"
                                f"{channel_definition.channel_id}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            device_id=devices[device_key].id,
                            channel_id=channel_definition.channel_id,
                            channel_number=channel_definition.channel_number,
                            logical_sensor_number=(
                                channel_definition.logical_sensor_number
                            ),
                            display_name=channel_definition.display_name,
                            physical_sensor_count=(
                                channel_definition.physical_sensor_count
                            ),
                            metric_type="temperature",
                            unit="degC",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    existing.add(channel_definition.channel_id)
                    created += 1
    return created


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://nexolab.local/{value}"))


if __name__ == "__main__":
    raise SystemExit(main())
