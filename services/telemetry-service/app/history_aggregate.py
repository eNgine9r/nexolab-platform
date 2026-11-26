"""Extremum-preserving aggregated telemetry history (#1811).

Charts need a few hundred points per channel, not every raw sample. Shipping raw pages made a
7-day, 8-channel chart transfer ~130 MB of JSON in ~488 requests (#1804 baseline). This module
answers one request for up to 24 series:

* ``raw`` mode when the window holds at most ``RAW_POINTS_PER_BUCKET`` samples per bucket, so the
  chart loses nothing at that density;
* otherwise ``aggregate`` mode: per time bucket the first, last, minimum and maximum valid sample
  (M4, with their own timestamps), counts, the first/last invalid sample time (so communication
  errors still break the line) and the sum of valid values.

Whole-window statistics are computed from the original rows, never from display points. Nothing is
interpolated: an empty bucket is missing data. PostgreSQL aggregates in SQL; other dialects
(development SQLite) use the reference implementation below, which CI proves equivalent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import and_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.db import Database, HistoryCapacityError, TelemetrySample, _is_statement_timeout

MAX_AGGREGATE_SERIES = 24
MAX_AGGREGATE_BUCKETS = 2_000
RAW_POINTS_PER_BUCKET = 4


@dataclass(frozen=True)
class SeriesKey:
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str

    @classmethod
    def parse(cls, value: str) -> "SeriesKey":
        parts = value.split("|")
        if len(parts) != 4 or any(not part.strip() for part in parts):
            raise ValueError("series must be node|equipment|channel|metric")
        return cls(*(part.strip() for part in parts))


@dataclass
class Bucket:
    index: int
    count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    first_invalid_ms: int | None = None
    last_invalid_ms: int | None = None
    first: tuple[int, float] | None = None
    last: tuple[int, float] | None = None
    minimum: tuple[int, float] | None = None
    maximum: tuple[int, float] | None = None
    total: float = 0.0


@dataclass
class SeriesAggregate:
    key: SeriesKey
    unit: str | None
    mode: str
    count: int
    valid_count: int
    minimum: float | None
    maximum: float | None
    average: float | None
    first_ms: int | None
    last_ms: int | None
    raw: list[tuple[int, float | None, str, str | None, str]] = field(default_factory=list)
    buckets: list[Bucket] = field(default_factory=list)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def epoch_ms(value: datetime) -> int:
    """Milliseconds since the epoch, rounded half up from exact microseconds (as PostgreSQL)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    delta = value - _EPOCH
    microseconds = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return (microseconds + 500) // 1_000


def bucket_width_ms(from_ms: int, to_ms: int, buckets: int) -> int:
    return max(1, math.ceil((to_ms - from_ms) / buckets))


def _is_valid(quality: str, value: float | None) -> bool:
    return quality == "valid" and value is not None and math.isfinite(value)


def epoch_us(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    delta = value - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def us_to_ms(microseconds: int) -> int:
    return (microseconds + 500) // 1_000


def aggregate_rows(
    rows: Iterable[tuple[int, float | None, str]],
    *,
    from_ms: int,
    bucket_ms: int,
    buckets: int,
) -> list[Bucket]:
    """Reference M4 aggregation over (captured_us, value, quality) rows.

    Deterministic tie rules shared with the PostgreSQL query (no ordering of input required):
    first = smallest (time, value); last = largest (time, value); minimum = smallest
    (value, time); maximum = largest value, earliest time. Times are microseconds; the response
    carries milliseconds rounded half up.
    """
    state: dict[int, dict[str, Any]] = {}
    for captured_us, value, quality in rows:
        captured_ms = us_to_ms(captured_us)
        index = min(buckets - 1, max(0, (captured_ms - from_ms) // bucket_ms))
        entry = state.setdefault(index, {"bucket": Bucket(index=index)})
        bucket: Bucket = entry["bucket"]
        bucket.count += 1
        if not _is_valid(quality, value):
            bucket.invalid_count += 1
            bucket.first_invalid_ms = captured_ms if bucket.first_invalid_ms is None else min(bucket.first_invalid_ms, captured_ms)
            bucket.last_invalid_ms = captured_ms if bucket.last_invalid_ms is None else max(bucket.last_invalid_ms, captured_ms)
            continue
        assert value is not None
        numeric = float(value)
        bucket.valid_count += 1
        bucket.total += numeric
        candidate = (captured_us, numeric)
        if entry.get("first") is None or candidate < entry["first"]:
            entry["first"] = candidate
        if entry.get("last") is None or candidate > entry["last"]:
            entry["last"] = candidate
        if entry.get("min") is None or (numeric, captured_us) < entry["min"]:
            entry["min"] = (numeric, captured_us)
        if entry.get("max") is None or (numeric, -captured_us) > entry["max"]:
            entry["max"] = (numeric, -captured_us)
    result: list[Bucket] = []
    for index in sorted(state):
        entry = state[index]
        bucket = entry["bucket"]
        if bucket.valid_count:
            bucket.first = (us_to_ms(entry["first"][0]), entry["first"][1])
            bucket.last = (us_to_ms(entry["last"][0]), entry["last"][1])
            bucket.minimum = (us_to_ms(entry["min"][1]), entry["min"][0])
            bucket.maximum = (us_to_ms(-entry["max"][1]), entry["max"][0])
        result.append(bucket)
    return result


def _series_filter(key: SeriesKey, from_at: datetime, to_at: datetime, snapshot_at: datetime) -> Any:
    return and_(
        TelemetrySample.node_id == key.node_id,
        TelemetrySample.equipment_id == key.equipment_id,
        TelemetrySample.channel_id == key.channel_id,
        TelemetrySample.metric == key.metric,
        TelemetrySample.captured_at >= from_at,
        TelemetrySample.captured_at <= to_at,
        TelemetrySample.received_at <= snapshot_at,
    )


_POSTGRES_UNIT = text(
    """
    SELECT unit FROM telemetry_samples
    WHERE node_id = :node_id AND equipment_id = :equipment_id AND channel_id = :channel_id
      AND metric = :metric AND captured_at >= :from_at AND captured_at <= :to_at
      AND received_at <= :snapshot_at
    ORDER BY captured_at DESC
    LIMIT 1
    """
)

# One pass, no per-bucket sorting: min/max over [value, time] arrays give the extremum and its
# time with deterministic ties (same rules as aggregate_rows). Times are exact microseconds in
# float8 (exact below 2^53 us, i.e. until year 2255).
_POSTGRES_BUCKETS = text(
    """
    SELECT bucket,
           count(*) AS total,
           count(*) FILTER (WHERE ok) AS valid,
           count(*) FILTER (WHERE NOT ok) AS invalid,
           min(ms) FILTER (WHERE NOT ok) AS first_invalid_ms,
           max(ms) FILTER (WHERE NOT ok) AS last_invalid_ms,
           min(ARRAY[us, value]) FILTER (WHERE ok) AS first_pair,
           max(ARRAY[us, value]) FILTER (WHERE ok) AS last_pair,
           min(ARRAY[value, us]) FILTER (WHERE ok) AS min_pair,
           max(ARRAY[value, -us]) FILTER (WHERE ok) AS max_pair,
           sum(value) FILTER (WHERE ok) AS total_value
    FROM (
        SELECT us, value, ok, (floor((us + 500) / 1000))::bigint AS ms,
               LEAST(:last_bucket, GREATEST(0, floor((floor((us + 500) / 1000) - :from_ms) / :bucket_ms)))::bigint
                   AS bucket
        FROM (
            SELECT value,
                   (extract(epoch FROM captured_at) * 1000000)::float8 AS us,
                   (quality = 'valid' AND value IS NOT NULL AND value <> 'NaN'::float8
                    AND value <> 'Infinity'::float8 AND value <> '-Infinity'::float8) AS ok
            FROM telemetry_samples
            WHERE node_id = :node_id AND equipment_id = :equipment_id AND channel_id = :channel_id
              AND metric = :metric AND captured_at >= :from_at AND captured_at <= :to_at
              AND received_at <= :snapshot_at
        ) AS rows
    ) AS source
    GROUP BY bucket
    ORDER BY bucket
    """
)


def _us_pair_ms(pair: Any, *, value_first: bool = False, negated_time: bool = False) -> tuple[int, float] | None:
    if pair is None:
        return None
    if value_first:
        value, us = float(pair[0]), float(pair[1])
    else:
        us, value = float(pair[0]), float(pair[1])
    microseconds = int(-us if negated_time else us)
    return us_to_ms(microseconds), value


def _parameters(key: SeriesKey, from_at: datetime, to_at: datetime, snapshot_at: datetime) -> dict[str, Any]:
    return {
        "node_id": key.node_id,
        "equipment_id": key.equipment_id,
        "channel_id": key.channel_id,
        "metric": key.metric,
        "from_at": from_at,
        "to_at": to_at,
        "snapshot_at": snapshot_at,
    }


def _raw_rows(session: Any, key: SeriesKey, from_at: datetime, to_at: datetime, snapshot_at: datetime) -> list[Any]:
    statement = (
        select(
            TelemetrySample.captured_at,
            TelemetrySample.value,
            TelemetrySample.quality,
            TelemetrySample.alarm,
            TelemetrySample.event_id,
            TelemetrySample.unit,
        )
        .where(_series_filter(key, from_at, to_at, snapshot_at))
        .order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
    )
    return list(session.execute(statement))


def _summary_from_rows(key: SeriesKey, rows: list[Any]) -> SeriesAggregate:
    valid = [float(row.value) for row in rows if _is_valid(row.quality, row.value)]
    return SeriesAggregate(
        key=key,
        unit=rows[-1].unit if rows else None,
        mode="raw",
        count=len(rows),
        valid_count=len(valid),
        minimum=min(valid) if valid else None,
        maximum=max(valid) if valid else None,
        average=(sum(valid) / len(valid)) if valid else None,
        first_ms=epoch_ms(rows[0].captured_at) if rows else None,
        last_ms=epoch_ms(rows[-1].captured_at) if rows else None,
    )


def _aggregate_series_reference(
    session: Any,
    key: SeriesKey,
    *,
    from_at: datetime,
    to_at: datetime,
    snapshot_at: datetime,
    buckets: int,
) -> SeriesAggregate:
    rows = _raw_rows(session, key, from_at, to_at, snapshot_at)
    summary = _summary_from_rows(key, rows)
    if len(rows) <= buckets * RAW_POINTS_PER_BUCKET:
        summary.raw = [
            (epoch_ms(row.captured_at), row.value, row.quality, row.alarm, row.event_id) for row in rows
        ]
        return summary
    from_ms = epoch_ms(from_at)
    result = aggregate_rows(
        ((epoch_us(row.captured_at), row.value, row.quality) for row in rows),
        from_ms=from_ms,
        bucket_ms=bucket_width_ms(from_ms, epoch_ms(to_at), buckets),
        buckets=buckets,
    )
    return _summary_from_buckets(key, summary.unit, result)


def _summary_from_buckets(key: SeriesKey, unit: str | None, buckets: list[Bucket]) -> SeriesAggregate:
    valid = sum(bucket.valid_count for bucket in buckets)
    total = sum(bucket.total for bucket in buckets if bucket.valid_count)
    times = [
        moment
        for bucket in buckets
        for moment in (
            bucket.first[0] if bucket.first else None,
            bucket.last[0] if bucket.last else None,
            bucket.first_invalid_ms,
            bucket.last_invalid_ms,
        )
        if moment is not None
    ]
    minima = [bucket.minimum[1] for bucket in buckets if bucket.minimum]
    maxima = [bucket.maximum[1] for bucket in buckets if bucket.maximum]
    return SeriesAggregate(
        key=key,
        unit=unit,
        mode="aggregate",
        count=sum(bucket.count for bucket in buckets),
        valid_count=valid,
        minimum=min(minima) if minima else None,
        maximum=max(maxima) if maxima else None,
        average=(total / valid) if valid else None,
        first_ms=min(times) if times else None,
        last_ms=max(times) if times else None,
        buckets=buckets,
    )


def _aggregate_series_postgres(
    session: Any,
    key: SeriesKey,
    *,
    from_at: datetime,
    to_at: datetime,
    snapshot_at: datetime,
    buckets: int,
) -> SeriesAggregate:
    parameters = _parameters(key, from_at, to_at, snapshot_at)
    from_ms = epoch_ms(from_at)
    bucket_ms = bucket_width_ms(from_ms, epoch_ms(to_at), buckets)
    rows = session.execute(
        _POSTGRES_BUCKETS,
        {**parameters, "from_ms": from_ms, "bucket_ms": bucket_ms, "last_bucket": buckets - 1},
    )
    result: list[Bucket] = [
        Bucket(
            index=int(row.bucket),
            count=int(row.total),
            valid_count=int(row.valid),
            invalid_count=int(row.invalid),
            first_invalid_ms=None if row.first_invalid_ms is None else int(row.first_invalid_ms),
            last_invalid_ms=None if row.last_invalid_ms is None else int(row.last_invalid_ms),
            first=_us_pair_ms(row.first_pair),
            last=_us_pair_ms(row.last_pair),
            minimum=_us_pair_ms(row.min_pair, value_first=True),
            maximum=_us_pair_ms(row.max_pair, value_first=True, negated_time=True),
            total=0.0 if row.total_value is None else float(row.total_value),
        )
        for row in rows
    ]
    count = sum(bucket.count for bucket in result)
    if count <= buckets * RAW_POINTS_PER_BUCKET:
        raw_rows = _raw_rows(session, key, from_at, to_at, snapshot_at)
        summary = _summary_from_rows(key, raw_rows)
        summary.raw = [
            (epoch_ms(row.captured_at), row.value, row.quality, row.alarm, row.event_id) for row in raw_rows
        ]
        return summary
    unit = session.execute(_POSTGRES_UNIT, parameters).scalar()
    return _summary_from_buckets(key, unit, result)


def aggregate_history(
    database: Database,
    series: list[SeriesKey],
    *,
    from_at: datetime,
    to_at: datetime,
    buckets: int,
    snapshot_at: datetime | None = None,
    reference: bool = False,
) -> tuple[list[SeriesAggregate], datetime]:
    """Aggregated history for each series under one ingestion snapshot watermark."""
    if not 1 <= buckets <= MAX_AGGREGATE_BUCKETS:
        raise ValueError(f"buckets must be between 1 and {MAX_AGGREGATE_BUCKETS}")
    if not 1 <= len(series) <= MAX_AGGREGATE_SERIES:
        raise ValueError(f"between 1 and {MAX_AGGREGATE_SERIES} series are required")
    if from_at >= to_at:
        raise ValueError("from must be earlier than to")
    postgres = database.history_engine.dialect.name == "postgresql" and not reference
    try:
        resolved_snapshot_at = snapshot_at if snapshot_at is not None else database._establish_history_snapshot()
        results: list[SeriesAggregate] = []
        with database._history_sessions() as session:
            with session.begin():
                database._limit_history_statement(session)
                for key in series:
                    compute = _aggregate_series_postgres if postgres else _aggregate_series_reference
                    results.append(
                        compute(
                            session,
                            key,
                            from_at=from_at,
                            to_at=to_at,
                            snapshot_at=resolved_snapshot_at,
                            buckets=buckets,
                        )
                    )
    except SQLAlchemyTimeoutError as error:
        raise HistoryCapacityError("History read capacity is exhausted") from error
    except OperationalError as error:
        if _is_statement_timeout(error):
            raise HistoryCapacityError("History query exceeded its time budget") from error
        raise
    return results, resolved_snapshot_at
