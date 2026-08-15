from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
)
from app.db import TelemetrySample
from app.live_dashboard.repository import LiveDashboardRepository
from app.nodes.models import CentralNode
from app.refrigeration.models import RefrigerationEquipmentRecord


@dataclass(frozen=True, slots=True)
class InventoryLatestRecord:
    event_id: str
    captured_at: datetime
    value: float | None
    unit: str
    quality: str
    source: str
    alarm: str | None
    received_at: datetime


@dataclass(frozen=True, slots=True)
class InventoryChannelRecord:
    channel_ref_id: str
    node_id: str
    equipment_id: str
    equipment_name: str
    climate_chamber_id: str
    climate_chamber_code: str
    climate_chamber_name: str
    equipment_type: str
    laboratory: str | None
    zone: str | None
    channel_id: str
    channel_name: str
    metric: str
    native_unit: str
    source: str
    quality: str
    alarm: str | None
    latest: InventoryLatestRecord | None


@dataclass(frozen=True, slots=True)
class InventoryPage:
    items: tuple[InventoryChannelRecord, ...]
    total: int


def list_live_dashboard_inventory(
    repository: LiveDashboardRepository,
    *,
    organization_id: str,
    limit: int,
    offset: int,
) -> InventoryPage:
    """Return the bounded canonical catalog used by Live Dashboard save validation.

    Catalog discovery is independent of telemetry history volume. Latest metadata is
    attached with one correlated indexed lookup per returned catalog row. A channel
    remains visible when that lookup has no matching sample.
    """

    with Session(repository._engine, expire_on_commit=False) as session:
        total = int(
            session.scalar(
                _eligible_catalog_select(organization_id)
                .with_only_columns(func.count(), maintain_column_froms=True)
                .order_by(None)
            )
            or 0
        )
        records: list[InventoryChannelRecord] = []
        for row in session.execute(
            inventory_query_plan_statement(
                repository,
                organization_id=organization_id,
                limit=limit,
                offset=offset,
            )
        ):
            mapping = row._mapping
            latest = None
            if mapping["latest_event_id"] is not None:
                latest = InventoryLatestRecord(
                    event_id=mapping["latest_event_id"],
                    captured_at=mapping["latest_captured_at"],
                    value=mapping["latest_value"],
                    unit=mapping["latest_unit"],
                    quality=mapping["latest_quality"],
                    source=mapping["latest_source"],
                    alarm=mapping["latest_alarm"],
                    received_at=mapping["latest_received_at"],
                )
            records.append(
                InventoryChannelRecord(
                    channel_ref_id=mapping["channel_ref_id"],
                    node_id=mapping["node_id"],
                    equipment_id=mapping["equipment_id"],
                    equipment_name=mapping["equipment_name"],
                    climate_chamber_id=mapping["climate_chamber_id"],
                    climate_chamber_code=mapping["climate_chamber_code"],
                    climate_chamber_name=mapping["climate_chamber_name"],
                    equipment_type=mapping["equipment_type"],
                    laboratory=mapping["laboratory"],
                    zone=mapping["zone"],
                    channel_id=mapping["channel_id"],
                    channel_name=mapping["channel_name"],
                    metric=mapping["metric"],
                    native_unit=mapping["native_unit"],
                    source=(
                        mapping["latest_source"]
                        if mapping["latest_source"] is not None
                        else mapping["catalog_source"]
                    ),
                    quality=(
                        mapping["latest_quality"]
                        if mapping["latest_quality"] is not None
                        else "unknown"
                    ),
                    alarm=mapping["latest_alarm"],
                    latest=latest,
                )
            )
        return InventoryPage(items=tuple(records), total=total)


def inventory_query_plan_statement(
    repository: LiveDashboardRepository,
    *,
    organization_id: str,
    limit: int,
    offset: int = 0,
):
    """Return the exact full query used for PostgreSQL EXPLAIN evidence."""

    del repository
    sample_candidate = aliased(TelemetrySample, name="inventory_sample_candidate")
    latest_sample = aliased(TelemetrySample, name="inventory_latest_sample")
    latest_sample_id = (
        select(sample_candidate.id)
        .where(
            sample_candidate.node_id == MeasurementBus.node_id,
            sample_candidate.equipment_id == MeasurementDevice.business_key,
            sample_candidate.channel_id == MeasurementChannel.channel_id,
            sample_candidate.metric == MeasurementChannel.metric_type,
        )
        .order_by(
            sample_candidate.captured_at.desc(),
            sample_candidate.event_id.desc(),
        )
        .limit(1)
        .correlate(MeasurementBus, MeasurementDevice, MeasurementChannel)
        .scalar_subquery()
    )
    taxonomy = _equipment_taxonomy_subquery(organization_id)
    return (
        _eligible_catalog_select(organization_id)
        .outerjoin(
            taxonomy,
            (taxonomy.c.organization_id == MeasurementChannel.organization_id)
            & (taxonomy.c.climate_chamber_id == MeasurementChannel.climate_chamber_id),
        )
        .with_only_columns(
            MeasurementChannel.id.label("channel_ref_id"),
            MeasurementBus.node_id.label("node_id"),
            MeasurementDevice.business_key.label("equipment_id"),
            MeasurementDevice.display_name.label("equipment_name"),
            ClimateChamber.id.label("climate_chamber_id"),
            ClimateChamber.code.label("climate_chamber_code"),
            ClimateChamber.name.label("climate_chamber_name"),
            MeasurementDevice.device_type.label("equipment_type"),
            taxonomy.c.laboratory.label("laboratory"),
            taxonomy.c.zone.label("zone"),
            MeasurementChannel.channel_id.label("channel_id"),
            MeasurementChannel.display_name.label("channel_name"),
            MeasurementChannel.metric_type.label("metric"),
            MeasurementChannel.unit.label("native_unit"),
            MeasurementDevice.device_type.label("catalog_source"),
            latest_sample.event_id.label("latest_event_id"),
            latest_sample.captured_at.label("latest_captured_at"),
            latest_sample.value.label("latest_value"),
            latest_sample.unit.label("latest_unit"),
            latest_sample.quality.label("latest_quality"),
            latest_sample.source.label("latest_source"),
            latest_sample.alarm.label("latest_alarm"),
            latest_sample.received_at.label("latest_received_at"),
        )
        .outerjoin(latest_sample, latest_sample.id == latest_sample_id)
        .order_by(
            MeasurementBus.node_id.asc(),
            MeasurementDevice.business_key.asc(),
            MeasurementChannel.channel_id.asc(),
            MeasurementChannel.metric_type.asc(),
            MeasurementChannel.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )


def _equipment_taxonomy_subquery(organization_id: str):
    """Return only unambiguous chamber-level operator taxonomy.

    Multiple active/maintenance equipment records may share a climate chamber.
    A laboratory or zone is exposed only when all known values agree. Missing or
    conflicting metadata remains NULL so the frontend can present it truthfully.
    """

    return (
        select(
            RefrigerationEquipmentRecord.organization_id.label("organization_id"),
            RefrigerationEquipmentRecord.climate_chamber_id.label("climate_chamber_id"),
            case(
                (
                    func.count(func.distinct(RefrigerationEquipmentRecord.laboratory)) == 1,
                    func.min(RefrigerationEquipmentRecord.laboratory),
                ),
                else_=None,
            ).label("laboratory"),
            case(
                (
                    func.count(func.distinct(RefrigerationEquipmentRecord.zone)) == 1,
                    func.min(RefrigerationEquipmentRecord.zone),
                ),
                else_=None,
            ).label("zone"),
        )
        .where(
            RefrigerationEquipmentRecord.organization_id == organization_id,
            RefrigerationEquipmentRecord.deleted_at.is_(None),
            RefrigerationEquipmentRecord.lifecycle_status != "retired",
            RefrigerationEquipmentRecord.climate_chamber_id.is_not(None),
        )
        .group_by(
            RefrigerationEquipmentRecord.organization_id,
            RefrigerationEquipmentRecord.climate_chamber_id,
        )
        .subquery("live_dashboard_equipment_taxonomy")
    )


def _eligible_catalog_select(organization_id: str):
    """Mirror the active catalog and non-revoked node predicate used on save."""

    return (
        select(MeasurementChannel)
        .join(
            MeasurementDevice,
            (MeasurementDevice.organization_id == MeasurementChannel.organization_id)
            & (MeasurementDevice.id == MeasurementChannel.device_id),
        )
        .join(
            MeasurementBus,
            (MeasurementBus.organization_id == MeasurementChannel.organization_id)
            & (MeasurementBus.id == MeasurementChannel.bus_id),
        )
        .join(
            ClimateChamber,
            (ClimateChamber.organization_id == MeasurementChannel.organization_id)
            & (ClimateChamber.id == MeasurementChannel.climate_chamber_id),
        )
        .join(
            CentralNode,
            (CentralNode.organization_id == MeasurementBus.organization_id)
            & (CentralNode.node_id == MeasurementBus.node_id),
        )
        .where(
            MeasurementChannel.organization_id == organization_id,
            MeasurementChannel.status == "active",
            MeasurementDevice.status == "active",
            MeasurementBus.status == "active",
            ClimateChamber.status == "active",
            CentralNode.state != "revoked",
        )
    )
