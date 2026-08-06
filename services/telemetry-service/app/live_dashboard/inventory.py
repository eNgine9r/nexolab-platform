from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
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

    The catalog rows are independent of telemetry history volume. Latest metadata is
    attached with one correlated, indexed lookup per returned catalog row. A channel
    remains visible when that lookup has no matching sample.
    """

    engine = repository._engine  # Same database boundary as dashboard persistence.
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

    with Session(engine, expire_on_commit=False) as session:
        total = int(
            session.scalar(
                _eligible_catalog_select(organization_id)
                .with_only_columns(func.count(), maintain_column_froms=True)
                .order_by(None)
            )
            or 0
        )
        statement = (
            _eligible_catalog_select(organization_id)
            .with_only_columns(
                MeasurementChannel.id.label("channel_ref_id"),
                MeasurementBus.node_id.label("node_id"),
                MeasurementDevice.business_key.label("equipment_id"),
                MeasurementDevice.display_name.label("equipment_name"),
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
        records: list[InventoryChannelRecord] = []
        for row in session.execute(statement):
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
    """Expose the catalog-only statement for PostgreSQL EXPLAIN evidence."""

    del repository
    return (
        _eligible_catalog_select(organization_id)
        .with_only_columns(
            MeasurementChannel.id,
            MeasurementBus.node_id,
            MeasurementDevice.business_key,
            MeasurementChannel.channel_id,
            MeasurementChannel.metric_type,
        )
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
