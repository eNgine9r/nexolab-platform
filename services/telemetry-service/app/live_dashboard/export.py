from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementBus, MeasurementChannel, MeasurementDevice
from app.db import Database, TelemetryQuery
from app.delivery import PersistedTelemetryReadModel
from app.live_dashboard.repository import DashboardItemRecord, DashboardRecord


EXPORT_MEDIA_TYPE = "text/csv; charset=utf-8"
EXPORT_FIELDS = (
    "timestamp_utc",
    "timestamp_local",
    "node",
    "device",
    "channel",
    "metric",
    "value",
    "unit",
    "quality",
    "event_id",
)
DEFAULT_EXPORT_MAX_ROWS = 100_000
EXPORT_PAGE_SIZE = 1_000


class LiveDashboardExportError(RuntimeError):
    pass


class LiveDashboardExportTooLargeError(LiveDashboardExportError):
    def __init__(self, maximum_rows: int) -> None:
        super().__init__(
            f"Saved Dashboard export exceeds the safe limit of {maximum_rows} rows. "
            "Select a shorter time range or fewer dashboard series."
        )
        self.maximum_rows = maximum_rows


class LiveDashboardExportTimezoneError(LiveDashboardExportError):
    pass


@dataclass(frozen=True, slots=True)
class LiveDashboardCsvExport:
    content: bytes
    filename: str
    row_count: int
    snapshot_at: datetime


def _timestamp(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        # SQLite drops timezone metadata for DateTime(timezone=True); NEXOLAB persists
        # canonical telemetry timestamps in UTC, matching Database normalization paths.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _value_cell(value: object) -> str:
    if value is None:
        return ""
    numeric = float(value)
    if not math.isfinite(numeric):
        raise LiveDashboardExportError("Persisted telemetry contains a non-finite value")
    if numeric == 0:
        return "0"
    return format(numeric, ".15g")


def _resolve_timezone(name: str) -> ZoneInfo:
    normalized = name.strip()
    if not normalized:
        raise LiveDashboardExportTimezoneError("timezone must not be empty")
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise LiveDashboardExportTimezoneError(
            f"Unsupported IANA timezone: {normalized}"
        ) from error


def _series_scope(
    database: Database,
    dashboard: DashboardRecord,
    item: DashboardItemRecord,
) -> tuple[str, str]:
    with Session(database.engine) as session:
        row = session.execute(
            select(MeasurementBus.node_id, MeasurementDevice.business_key)
            .select_from(MeasurementChannel)
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
            .where(
                MeasurementChannel.organization_id == dashboard.organization_id,
                MeasurementChannel.id == item.channel_ref_id,
            )
        ).one_or_none()
    if row is None:
        raise LiveDashboardExportError(
            f"Saved Dashboard channel reference {item.channel_ref_id!r} no longer exists "
            "in this organization"
        )
    return str(row.node_id), str(row.business_key)


def build_live_dashboard_csv_export(
    database: Database,
    dashboard: DashboardRecord,
    *,
    from_at: datetime,
    to_at: datetime,
    timezone_name: str,
    maximum_rows: int = DEFAULT_EXPORT_MAX_ROWS,
) -> LiveDashboardCsvExport:
    if maximum_rows < 1:
        raise ValueError("maximum_rows must be positive")
    if from_at.tzinfo is None or to_at.tzinfo is None:
        raise LiveDashboardExportError("Export range must use timezone-aware timestamps")
    if from_at >= to_at:
        raise LiveDashboardExportError("Export start must be earlier than export end")

    timezone = _resolve_timezone(timezone_name)
    read_model = PersistedTelemetryReadModel(database)
    snapshot_at: datetime | None = None
    rows: list[dict[str, object]] = []

    for item in sorted(dashboard.items, key=lambda current: (current.position, current.id)):
        node_id, equipment_id = _series_scope(database, dashboard, item)
        offset = 0
        while True:
            page_limit = min(EXPORT_PAGE_SIZE, maximum_rows - len(rows) + 1)
            page, resolved_snapshot = read_model.history_snapshot_samples(
                query=TelemetryQuery(
                    node_id=node_id,
                    equipment_id=equipment_id,
                    channel_id=item.channel_id,
                    metric=item.metric,
                    from_at=from_at,
                    to_at=to_at,
                ),
                limit=page_limit,
                offset=offset,
                snapshot_at=snapshot_at,
            )
            if snapshot_at is None:
                snapshot_at = resolved_snapshot
            elif resolved_snapshot != snapshot_at:
                raise LiveDashboardExportError(
                    "Persisted telemetry snapshot changed during Saved Dashboard export"
                )

            rows.extend(page)
            if len(rows) > maximum_rows:
                raise LiveDashboardExportTooLargeError(maximum_rows)
            if len(page) < page_limit:
                break
            offset += len(page)

    if snapshot_at is None:
        snapshot_at = datetime.now(UTC)

    rows.sort(
        key=lambda row: (
            _timestamp(row["captured_at"]),
            str(row["node_id"]),
            str(row["equipment_id"]),
            str(row["channel_id"]),
            str(row["metric"]),
            str(row["event_id"]),
        )
    )

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPORT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        captured_at = _timestamp(row["captured_at"])
        writer.writerow(
            {
                "timestamp_utc": _utc_iso(captured_at),
                "timestamp_local": captured_at.astimezone(timezone).isoformat(),
                "node": str(row["node_id"]),
                "device": str(row["equipment_id"]),
                "channel": str(row["channel_id"]),
                "metric": str(row["metric"]),
                "value": _value_cell(row["value"]),
                "unit": str(row["unit"]),
                "quality": str(row["quality"]),
                "event_id": str(row["event_id"]),
            }
        )

    from_date = from_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    to_date = to_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return LiveDashboardCsvExport(
        content=stream.getvalue().encode("utf-8"),
        filename=f"live-dashboard-{dashboard.id}-{from_date}-{to_date}.csv",
        row_count=len(rows),
        snapshot_at=snapshot_at,
    )
