"""#1811: PostgreSQL SQL aggregation equals the reference implementation, with measured timings.

Timings are reported as warnings so they appear in the CI summary (pytest -q). They come from the
GitHub runner, not the Raspberry Pi; Pi timings need a deployed measurement.
"""

from __future__ import annotations

import os
import time
import warnings
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, text

from app.db import Database, TelemetrySample
from app.history_aggregate import SeriesKey, aggregate_history

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for SQL aggregation evidence",
)

BASE = datetime(2026, 10, 27, 0, tzinfo=UTC)


@pytest.fixture
def database():
    instance = Database(os.environ["DATABASE_URL"])
    instance.create_schema()
    node_id = f"aggregate-1811-{uuid4().hex[:12]}"
    try:
        yield instance, node_id
    finally:
        with instance.engine.begin() as connection:
            connection.execute(delete(TelemetrySample).where(TelemetrySample.node_id == node_id))
        instance.dispose()


def _seed(instance: Database, node_id: str, *, channels: int, seconds: int, cadence: int) -> None:
    """Deterministic noisy series with excursions, invalid samples, NaN, ties and a gap."""
    with instance.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO telemetry_samples (
                    event_id, node_id, captured_at, metric, value, unit, quality, source,
                    equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload, received_at
                )
                SELECT gen_random_uuid()::text, :node_id,
                       :base + make_interval(secs => step * :cadence + (channel % 3) * 0.0015),
                       'temperature',
                       CASE
                           WHEN step % 997 = 13 THEN NULL
                           WHEN step % 1499 = 7 THEN 'NaN'::float8
                           WHEN step % 1201 = 600 THEN 30 + channel
                           ELSE round((4 + sin(step / 360.0) + ((step * 7919) % 10) / 20.0)::numeric, 2)::float8
                       END,
                       'degC',
                       CASE WHEN step % 997 = 13 THEN 'communication_error' ELSE 'valid' END,
                       'aggregate-1811-test', 'XJP60D-1811', 'ch-' || channel, NULL, 0, 0, '{}'::json,
                       :base
                FROM generate_series(1, :channels) AS channel,
                     generate_series(0, :steps) AS step
                WHERE NOT (step BETWEEN 2000 AND 2100)
                """
            ),
            {"node_id": node_id, "base": BASE, "channels": channels, "steps": seconds // cadence, "cadence": cadence},
        )
        connection.execute(text("ANALYZE telemetry_samples"))


def _keys(node_id: str, channels: int) -> list[SeriesKey]:
    return [SeriesKey(node_id, "XJP60D-1811", f"ch-{index}", "temperature") for index in range(1, channels + 1)]


def _comparable(result):
    return [
        (
            item.mode,
            item.count,
            item.valid_count,
            item.minimum,
            item.maximum,
            item.first_ms,
            item.last_ms,
            [
                (
                    bucket.index,
                    bucket.count,
                    bucket.valid_count,
                    bucket.invalid_count,
                    bucket.first_invalid_ms,
                    bucket.last_invalid_ms,
                    bucket.first,
                    bucket.last,
                    bucket.minimum,
                    bucket.maximum,
                )
                for bucket in item.buckets
            ],
            len(item.raw),
        )
        for item in result
    ]


def test_sql_aggregation_equals_reference_and_reports_timings(database) -> None:
    instance, node_id = database
    _seed(instance, node_id, channels=24, seconds=86_400, cadence=10)
    keys = _keys(node_id, 24)
    window = {"from_at": BASE, "to_at": BASE + timedelta(days=1), "snapshot_at": BASE + timedelta(days=2)}

    started = time.perf_counter()
    sql, _ = aggregate_history(instance, keys, buckets=60, **window)
    sql_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    reference, _ = aggregate_history(instance, keys, buckets=60, reference=True, **window)
    reference_ms = (time.perf_counter() - started) * 1000

    assert _comparable(sql) == _comparable(reference)
    for left, right in zip(sql, reference, strict=True):
        assert left.average == pytest.approx(right.average, rel=1e-9)
        for left_bucket, right_bucket in zip(left.buckets, right.buckets, strict=True):
            assert left_bucket.total == pytest.approx(right_bucket.total, rel=1e-9)
    assert all(item.mode == "aggregate" for item in sql)
    # Excursions survive: every channel's spike (30 + channel) is a bucket maximum.
    for index, item in enumerate(sql, start=1):
        assert item.maximum == 30 + index
        assert max(bucket.maximum[1] for bucket in item.buckets if bucket.maximum) == 30 + index
    warnings.warn(
        f"#1811 timing 24 ch x 24 h @10 s ({sum(item.count for item in sql)} rows, 60 buckets): "
        f"SQL {sql_ms:.0f} ms, reference {reference_ms:.0f} ms",
        UserWarning,
        stacklevel=1,
    )


def test_thirty_day_single_channel_timing(database) -> None:
    instance, node_id = database
    _seed(instance, node_id, channels=1, seconds=30 * 86_400, cadence=10)
    keys = _keys(node_id, 1)
    started = time.perf_counter()
    result, _ = aggregate_history(
        instance,
        keys,
        from_at=BASE,
        to_at=BASE + timedelta(days=30),
        snapshot_at=BASE + timedelta(days=31),
        buckets=240,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert result[0].mode == "aggregate"
    assert result[0].count > 250_000
    assert result[0].maximum == 31
    warnings.warn(
        f"#1811 timing 1 ch x 30 d @10 s ({result[0].count} rows, 240 buckets): SQL {elapsed_ms:.0f} ms",
        UserWarning,
        stacklevel=1,
    )


def test_sql_interval_statistics_equal_reference(database) -> None:
    instance, node_id = database
    _seed(instance, node_id, channels=4, seconds=86_400, cadence=10)
    keys = _keys(node_id, 4)
    window = {"from_at": BASE, "to_at": BASE + timedelta(days=1), "snapshot_at": BASE + timedelta(days=2)}
    started = time.perf_counter()
    sql, _ = aggregate_history(instance, keys, buckets=1, statistics=True, **window)
    sql_ms = (time.perf_counter() - started) * 1000
    reference, _ = aggregate_history(instance, keys, buckets=1, statistics=True, reference=True, **window)
    for left, right in zip(sql, reference, strict=True):
        a, b = left.statistics, right.statistics
        assert a is not None and b is not None
        assert (a.valid_count, a.invalid_count, a.minimum, a.maximum) == (b.valid_count, b.invalid_count, b.minimum, b.maximum)
        assert (a.first_valid_ms, a.last_valid_ms, a.median_spacing_ms) == (b.first_valid_ms, b.last_valid_ms, b.median_spacing_ms)
        assert (a.gap_count, a.gap_total_ms, a.gap_longest_ms) == (b.gap_count, b.gap_total_ms, b.gap_longest_ms)
        assert a.valid_sum == pytest.approx(b.valid_sum, rel=1e-9)
        assert a.gap_count >= 1  # the seeded 1 000 s gap
    warnings.warn(f"#1813 timing statistics 4 ch x 24 h @10 s: SQL {sql_ms:.0f} ms", UserWarning, stacklevel=1)
