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
from app.live_dashboard.telemetry_identity import (
    LiveDashboardTelemetryIdentityError,
    telemetry_equipment_id,
)
from app.nodes.models import CentralNode


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
    # Additive fields: the original persisted `value` and `quality` remain unchanged.
    "raw_value",
    "raw_signed_int16",
    "operator_celsius_degC",
    "operator_scale_degC_per_count",
    "operator_scale_basis",
)
DEFAULT_EXPORT_MAX_ROWS = 100_000
EXPORT_PAGE_SIZE = 1_000

# Operator-confirmed convention for these two physical Embraco Sync Unit 2 probes;
# NOT independently verified calibration or a change to persisted telemetry.
_EMBRACO_OPERATOR_PROBES = frozenset(
    {
        ("2-cabinet-temperature", "temperature.cabinet"),
        ("2-evaporator-temperature", "temperature.evaporator"),
    }
)
_EMBRACO_OPERATOR_SCALE = "0.1"
_EMBRACO_OPERATOR_BASIS = "operator_confirmed_hardware_unverified"

# Chromium/WebKit installations can still surface historical IANA link names.
# Normalize only explicit compatibility aliases; unknown identifiers must remain
# fail-closed instead of silently falling back to UTC.
_TIMEZONE_ALIASES: dict[str, str] = {
    "Europe/Kiev": "Europe/Kyiv",
}


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


def _operator_embraco_probe_columns(row: dict[str, object]) -> dict[str, str]:
    """Strictly scoped CSV *presentation*, never update source `quality`/`value`.

    Only exact Embraco Sync Unit 2 physical probe samples with a valid 16-bit
    unsigned raw register and original `unknown` quality may be interpreted.
    """
    if (
        row.get("node_id") != "edge-01"
        or row.get("equipment_id") != "EMBRACO-2"
        or (row.get("channel_id"), row.get("metric")) not in _EMBRACO_OPERATOR_PROBES
        or row.get("source") != "embraco-sync"
        or row.get("unit") != "degC"
        or row.get("quality") != "unknown"
        or row.get("value") is not None
    ):
        return {}
    raw = row.get("raw_value")
    if type(raw) is not int or not 0 <= raw <= 0xFFFF:
        return {}
    signed = raw if raw < 0x8000 else raw - 0x10000
    return {
        "raw_signed_int16": str(signed),
        "operator_celsius_degC": _value_cell(signed / 10),
        "operator_scale_degC_per_count": _EMBRACO_OPERATOR_SCALE,
        "operator_scale_basis": _EMBRACO_OPERATOR_BASIS,
    }


def _source_raw_cell(value: object) -> str:
    return str(value) if type(value) is int else ""


def _resolve_timezone(name: str) -> ZoneInfo:
    normalized = name.strip()
    if not normalized:
        raise LiveDashboardExportTimezoneError("timezone must not be empty")
    canonical = _TIMEZONE_ALIASES.get(normalized, normalized)
    try:
        return ZoneInfo(canonical)
    except ZoneInfoNotFoundError as error:
        raise LiveDashboardExportTimezoneError(
            f"Unsupported IANA timezone: {normalized}"
        ) from error


def _series_scope(
    database: Database,
    dashboard: DashboardRecord,
    item: DashboardItemRecord,
) -> tuple[str, str]:
    if item.node_id is not None and item.equipment_id is not None:
        with Session(database.engine) as session:
            allowed_node = session.scalar(
                select(CentralNode.node_id).where(
                    CentralNode.organization_id == dashboard.organization_id,
                    CentralNode.node_id == item.node_id,
                    CentralNode.state != "revoked",
                )
            )
        if allowed_node is None:
            raise LiveDashboardExportError("Saved dashboard node is unavailable in this organization")
        return item.node_id, item.equipment_id
    with Session(database.engine) as session:
        row = session.execute(
            select(
                MeasurementBus.node_id,
                MeasurementDevice.device_type,
                MeasurementDevice.unit_id,
            )
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
    try:
        equipment_id = telemetry_equipment_id(
            device_type=str(row.device_type),
            unit_id=int(row.unit_id),
        )
    except LiveDashboardTelemetryIdentityError as error:
        raise LiveDashboardExportError(str(error)) from error
    return str(row.node_id), equipment_id


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
                "raw_value": _source_raw_cell(row.get("raw_value")),
                **_operator_embraco_probe_columns(row),
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
