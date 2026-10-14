from __future__ import annotations

import math
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased, load_only
from app.climate_catalog.models import ClimateChamber, MeasurementBus, MeasurementDevice

from app.db import Database, TELEMETRY_HISTORY_ADVISORY_LOCK_ID, TelemetryLatest, TelemetrySample
from app.energy_export.schemas import COUNTER, METRICS, CatalogSeries, ExportError, ExportOptions, SeriesSelection, iso, utc
from app.nodes.models import CentralNode


PAGE_SIZE = 1000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def micros(value: datetime | str) -> int:
    delta = utc(value) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def catalog(database: Database, organization_id: str) -> list[CatalogSeries]:
    other = aliased(CentralNode)
    statement = (
        select(TelemetryLatest, CentralNode.display_name)
        .join(CentralNode, CentralNode.node_id == TelemetryLatest.node_id)
        .where(
            CentralNode.organization_id == organization_id,
            CentralNode.state == "active",
            ~exists(select(other.id).where(other.node_id == CentralNode.node_id, other.organization_id != organization_id)),
            TelemetryLatest.metric.in_(METRICS),
        )
        .order_by(TelemetryLatest.node_id, TelemetryLatest.equipment_id, TelemetryLatest.metric, TelemetryLatest.channel_id)
        .limit(1025)
    )
    with Session(database.engine) as session:
        rows = session.execute(statement).all()
        device_names = session.execute(select(MeasurementBus.node_id, MeasurementDevice.unit_id, MeasurementDevice.model, MeasurementDevice.display_name, MeasurementDevice.designation, ClimateChamber.name)
            .join(MeasurementBus, and_(MeasurementBus.id == MeasurementDevice.bus_id, MeasurementBus.organization_id == MeasurementDevice.organization_id))
            .join(ClimateChamber, and_(ClimateChamber.id == MeasurementDevice.climate_chamber_id, ClimateChamber.organization_id == MeasurementDevice.organization_id))
            .where(MeasurementDevice.organization_id == organization_id, MeasurementDevice.device_type == "energy_meter", MeasurementDevice.status == "active", MeasurementBus.status == "active").limit(1025)).all()
    if len(rows) > 1024:
        raise ExportError("catalog_too_large", "Каталог перевищує підтримуваний розмір; звузьте конфігурацію обладнання.")
    result = []
    names = {}
    for node, device_unit, model, device_name, designation, equipment_name in device_names:
        normalized = model.casefold().replace("-", "").replace(" ", "")
        prefix = "SDM120M" if "sdm120" in normalized else "LE01MP" if "le01mp" in normalized else None
        if prefix is not None:
            names.setdefault((node, f"{prefix}-{device_unit}"), []).append((equipment_name, designation or device_name))
    for row, node_name in rows:
        match = re.fullmatch(r"(LE01MP|SDM120M)-(\d{1,3})", row.equipment_id)
        if not match or not 1 <= int(match[2]) <= 247:
            continue
        if match[1] == "SDM120M" and row.metric == "temperature.internal":
            continue
        unit_id = int(match[2])
        label = f"W{unit_id - 199}" if match[1] == "LE01MP" and 200 <= unit_id <= 203 else row.equipment_id
        if row.equipment_id == "SDM120M-1":
            label = "SDM120M"
        recorded_names = names.get((row.node_id, row.equipment_id), [])
        equipment_name, meter_label = recorded_names[0] if len(recorded_names) == 1 else (f"{node_name} · {label}", label)
        result.append(CatalogSeries(
            node_id=row.node_id, equipment_id=row.equipment_id, channel_id=row.channel_id,
            metric=row.metric, unit=METRICS[row.metric][1], equipment_name=equipment_name,
            meter_label=meter_label, parameter_name=METRICS[row.metric][2], name_source="catalog" if len(recorded_names) == 1 else "telemetry_identity",
        ))
    return result


def validate_catalog_selection(database: Database, organization_id: str, options: ExportOptions) -> list[CatalogSeries]:
    allowed = {item.key: item for item in catalog(database, organization_id)}
    if any(item.key not in allowed for item in options.series):
        raise ExportError("series_unavailable", "Вибраний показник недоступний у цій організації або не підтримується лічильником.")
    return [allowed[item.key] for item in options.series]


def _scope(series: SeriesSelection, snapshot_at: datetime, source_id_watermark: int | None = None):
    # Keep incorrect historical units as flagged original records; do not silently
    # lose them by filtering to the currently expected unit.
    return and_(
        TelemetrySample.node_id == series.node_id,
        TelemetrySample.equipment_id == series.equipment_id,
        TelemetrySample.channel_id == series.channel_id,
        TelemetrySample.metric == series.metric,
        TelemetrySample.received_at <= snapshot_at,
        TelemetrySample.id <= source_id_watermark if source_id_watermark is not None else True,
    )


def _configure(session: Session) -> None:
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SET LOCAL statement_timeout = '15s'"))
        session.execute(text("SET LOCAL lock_timeout = '1s'"))


def _sample_rows():
    # Delivery JSON can be large and is not part of scalar measurement exports.
    # Keep each page bounded by only the actual values/provenance we serialize.
    return select(TelemetrySample).options(load_only(
        TelemetrySample.captured_at, TelemetrySample.event_id, TelemetrySample.value,
        TelemetrySample.unit, TelemetrySample.quality, TelemetrySample.source,
        raiseload=True,
    ))


def establish_snapshot(database: Database) -> tuple[datetime, int | None]:
    with Session(database.engine) as session, session.begin():
        _configure(session)
        if database.engine.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": TELEMETRY_HISTORY_ADVISORY_LOCK_ID})
            snapshot = utc(session.scalar(select(func.clock_timestamp())))
            boundary = int(session.scalar(select(func.max(TelemetrySample.id))) or 0)
            return snapshot, boundary
        # Development SQLite's CURRENT_TIMESTAMP has only second precision. Bind
        # additionally to the committed ID boundary so late same-second inserts
        # cannot drift into the frozen set. Production uses PostgreSQL above.
        boundary = int(session.scalar(select(func.max(TelemetrySample.id))) or 0)
        return datetime.now(UTC), boundary


def _count(database: Database, series: SeriesSelection, options: ExportOptions, snapshot: datetime, source_id_watermark: int | None = None) -> int:
    with Session(database.engine) as session:
        _configure(session)
        return int(session.scalar(select(func.count()).select_from(TelemetrySample).where(
            _scope(series, snapshot, source_id_watermark), TelemetrySample.captured_at >= options.from_at, TelemetrySample.captured_at < options.to_at,
        )) or 0)


def open_staging(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA temp_store = FILE")
    connection.execute("PRAGMA cache_size = -4096")
    connection.execute("PRAGMA journal_mode = DELETE")
    return connection


def freeze_source(
    database: Database,
    path: Path,
    options: ExportOptions,
    *,
    guard: Callable[[], None],
    progress: Callable[[int], None],
) -> dict:
    snapshot, source_id_watermark = establish_snapshot(database)
    counts = [_count(database, item, options, snapshot, source_id_watermark) for item in options.series]
    connection = open_staging(path)
    connection.execute("CREATE TABLE samples (series INTEGER NOT NULL, captured_us INTEGER NOT NULL, event_id TEXT NOT NULL, value REAL, observed_unit TEXT NOT NULL, quality TEXT NOT NULL, source TEXT NOT NULL, anchor INTEGER NOT NULL, PRIMARY KEY(series,event_id))")
    connection.execute("CREATE INDEX samples_order ON samples(series,captured_us,event_id)")
    resolutions = []
    source_events = 0
    first_all = None
    last_all = None
    try:
        for index, series in enumerate(options.series):
            previous_us = None
            minimum = None
            maximum = None
            actual_count = 0
            cursor = None
            # An original previous counter reading is an explicitly labeled anchor.
            if series.metric == COUNTER:
                with Session(database.engine) as session:
                    _configure(session)
                    anchors = list(session.scalars(_sample_rows().where(
                        _scope(series, snapshot, source_id_watermark), TelemetrySample.captured_at < options.from_at,
                    ).order_by(TelemetrySample.captured_at.desc(), TelemetrySample.event_id.desc()).limit(2)))
                # Preserve ties so ambiguous counter anchors cannot become valid deltas.
                if anchors:
                    latest_at = utc(anchors[0].captured_at)
                    for row in reversed(anchors):
                        if utc(row.captured_at) == latest_at:
                            _insert(connection, index, row, True)
            while True:
                guard()
                statement = _sample_rows().where(
                    _scope(series, snapshot, source_id_watermark), TelemetrySample.captured_at >= options.from_at,
                    TelemetrySample.captured_at <= options.to_at if series.metric == COUNTER else TelemetrySample.captured_at < options.to_at,
                )
                if cursor is not None:
                    at, event_id = cursor
                    statement = statement.where(or_(TelemetrySample.captured_at > at, and_(TelemetrySample.captured_at == at, TelemetrySample.event_id > event_id)))
                statement = statement.order_by(TelemetrySample.captured_at, TelemetrySample.event_id).limit(PAGE_SIZE)
                with Session(database.engine) as session:
                    _configure(session)
                    page = list(session.scalars(statement))
                if not page:
                    break
                for row in page:
                    captured = utc(row.captured_at)
                    captured_us = micros(captured)
                    anchor = captured >= options.to_at
                    _insert(connection, index, row, anchor)
                    if not anchor:
                        actual_count += 1
                        source_events += 1
                        first_all = captured_us if first_all is None else min(first_all, captured_us)
                        last_all = captured_us if last_all is None else max(last_all, captured_us)
                        if previous_us is not None and captured_us > previous_us:
                            difference = captured_us - previous_us
                            minimum = difference if minimum is None else min(minimum, difference)
                            maximum = difference if maximum is None else max(maximum, difference)
                        previous_us = captured_us
                connection.commit()
                progress(source_events)
                cursor = utc(page[-1].captured_at), page[-1].event_id
            if actual_count != counts[index] or _count(database, series, options, snapshot, source_id_watermark) != counts[index]:
                raise ExportError("history_changed", "Історію змінено під час підготовки. Повторіть попередній перегляд.")
            resolutions.append({"minimum_us": minimum, "maximum_us": maximum, "source_events": actual_count})
        guard()
        if any(_count(database, series, options, snapshot, source_id_watermark) != counts[index] for index, series in enumerate(options.series)):
            raise ExportError("history_changed", "Історію змінено під час підготовки. Повторіть попередній перегляд.")
        return {"snapshot_at": iso(snapshot), "source_id_watermark": source_id_watermark, "source_events": source_events, "resolutions": resolutions, "first_us": first_all, "last_us": last_all}
    finally:
        connection.close()


def _insert(connection: sqlite3.Connection, index: int, row: TelemetrySample, anchor: bool) -> None:
    value = row.value if row.value is not None and math.isfinite(row.value) else None
    quality = row.quality if value is not None or row.value is None else "invalid_nonfinite"
    connection.execute("INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)", (
        index, micros(row.captured_at), row.event_id, value, row.unit, quality, row.source, int(anchor),
    ))
