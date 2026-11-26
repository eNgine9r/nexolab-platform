"""#1811: extremum-preserving aggregated history API (reference path; PostgreSQL in a sibling test)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import create_api_router
from app.contracts import TelemetryEvent
from app.db import Database
from app.history_aggregate import aggregate_rows, bucket_width_ms, epoch_ms

BASE = datetime(2026, 11, 25, 12, tzinfo=UTC)
SERIES = "edge-01|XJP60D-1|temperature-1|temperature"


def _event(index: int, *, value: float | None, quality: str = "valid", seconds: int | None = None) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=BASE + timedelta(seconds=10 * index if seconds is None else seconds),
        metric="temperature",
        value=value,
        unit="degC",
        quality=quality,
        source="aggregate-test",
        equipment_id="XJP60D-1",
        channel_id="temperature-1",
        alarm=None,
        raw_value=None if value is None or not math.isfinite(value) else int(value * 10),
        raw_status=0,
    )


def _client(tmp_path: Path) -> tuple[TestClient, Database]:
    database = Database(f"sqlite:///{tmp_path / 'aggregate.db'}")
    database.create_schema()
    application = FastAPI()
    application.include_router(create_api_router(database, max_history_days=31, max_page_size=1000))
    return TestClient(application), database


def _seed(database: Database) -> list[TelemetryEvent]:
    events: list[TelemetryEvent] = []
    for index in range(600):
        if 300 <= index < 330:  # five minutes without any sample: a real gap
            continue
        value = 4.0 + (index % 7) / 10
        if index == 123:
            value = 19.5  # short excursion that must survive aggregation
        if index == 456:
            value = -3.25  # short dip
        quality = "communication_error" if index == 200 else "valid"
        events.append(_event(index, value=None if quality != "valid" else value, quality=quality))
    for event in events:
        assert database.persist(event, event.normalized_payload())
    return events


def _params(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "from": BASE.isoformat(),
        "to": (BASE + timedelta(seconds=6_000)).isoformat(),
        "series": [SERIES],
        "buckets": 20,
    }
    params.update(overrides)
    return params


def test_aggregate_preserves_extremes_invalid_samples_gaps_and_exact_statistics(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    events = _seed(database)
    response = client.get("/api/v1/telemetry/history/aggregate", params=_params())
    assert response.status_code == 200, response.text
    body = response.json()
    series = body["series"][0]
    assert series["mode"] == "aggregate"
    assert series["raw"] is None
    valid = [event.value for event in events if event.quality == "valid"]
    assert series["count"] == len(events)
    assert series["valid_count"] == len(valid)
    assert series["maximum"] == 19.5
    assert series["minimum"] == -3.25
    assert abs(series["average"] - sum(valid) / len(valid)) < 1e-9

    buckets = series["buckets"]
    assert max(row[13] for row in buckets) == 19.5  # bucket maximum value
    assert min(row[11] for row in buckets) == -3.25  # bucket minimum value
    spike_ms = epoch_ms(BASE + timedelta(seconds=1_230))
    assert any(row[12] == spike_ms for row in buckets)  # the excursion keeps its own timestamp
    invalid_ms = epoch_ms(BASE + timedelta(seconds=2_000))
    invalid_rows = [row for row in buckets if row[3] > 0]
    assert len(invalid_rows) == 1 and invalid_rows[0][4] == invalid_ms == invalid_rows[0][5]
    assert body["bucket_ms"] == 300_000
    # The silent 300 s (index 300..329) is one whole bucket: it is absent, not zero-filled.
    assert 10 not in {row[0] for row in buckets}
    assert sum(row[1] for row in buckets) == len(events)


def test_small_windows_return_original_samples(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    events = _seed(database)
    response = client.get("/api/v1/telemetry/history/aggregate", params=_params(buckets=200))
    series = response.json()["series"][0]
    assert series["mode"] == "raw"
    assert series["buckets"] is None
    assert len(series["raw"]) == len(events)
    assert [row[4] for row in series["raw"]] == [str(event.event_id) for event in events]
    invalid = [row for row in series["raw"] if row[2] != "valid"]
    assert len(invalid) == 1 and invalid[0][1] is None


def test_viewport_statistics_with_one_bucket_are_exact(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    events = _seed(database)
    window_from = BASE + timedelta(seconds=1_000)
    window_to = BASE + timedelta(seconds=2_500)
    response = client.get(
        "/api/v1/telemetry/history/aggregate",
        params=_params(**{"from": window_from.isoformat(), "to": window_to.isoformat(), "buckets": 1}),
    )
    series = response.json()["series"][0]
    inside = [event for event in events if window_from <= event.captured_at <= window_to]
    valid = [event.value for event in inside if event.quality == "valid"]
    assert series["count"] == len(inside)
    assert series["valid_count"] == len(valid)
    assert series["maximum"] == max(valid) == 19.5
    assert abs(series["average"] - sum(valid) / len(valid)) < 1e-9


def test_rejects_malformed_or_too_many_series(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/v1/telemetry/history/aggregate", params=_params(series=["broken"])).status_code == 422
    too_many = [f"edge-01|eq|channel-{index}|temperature" for index in range(25)]
    assert client.get("/api/v1/telemetry/history/aggregate", params=_params(series=too_many)).status_code == 422
    assert (
        client.get(
            "/api/v1/telemetry/history/aggregate",
            params=_params(**{"to": (BASE + timedelta(days=40)).isoformat()}),
        ).status_code
        == 422
    )


def test_reference_aggregation_ties_and_bucket_edges() -> None:
    rows = [  # (captured microseconds, value, quality), deliberately out of order
        (99_000, 7.0, "valid"),  # last sample of bucket 0
        (0, 5.0, "valid"),
        (20_000, 1.0, "valid"),
        (10_000, 1.0, "valid"),  # tie: the earliest minimum wins
        (40_000, 9.0, "valid"),
        (30_000, 9.0, "valid"),  # tie: the earliest maximum wins
        (50_000, None, "sensor_error"),
        (100_000, 2.0, "valid"),  # first sample of bucket 1
    ]
    buckets = aggregate_rows(rows, from_ms=0, bucket_ms=bucket_width_ms(0, 200, 2), buckets=2)
    first, second = buckets
    assert (first.count, first.valid_count, first.invalid_count) == (7, 6, 1)
    assert first.first == (0, 5.0) and first.last == (99, 7.0)
    assert first.minimum == (10, 1.0) and first.maximum == (30, 9.0)
    assert first.first_invalid_ms == first.last_invalid_ms == 50
    assert second.first == second.last == second.minimum == second.maximum == (100, 2.0)


def test_epoch_ms_rounds_half_up_like_postgresql() -> None:
    assert epoch_ms(datetime(1970, 1, 1, 0, 0, 0, 2_500, tzinfo=UTC)) == 3
    assert epoch_ms(datetime(1970, 1, 1, 0, 0, 0, 1_499, tzinfo=UTC)) == 1


def test_non_finite_raw_values_are_returned_as_null(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    for index, value in enumerate([4.0, float("nan"), 5.0, float("inf")]):
        event = _event(index, value=value)
        assert database.persist(event, event.normalized_payload())
    response = client.get("/api/v1/telemetry/history/aggregate", params=_params(buckets=50))
    assert response.status_code == 200, response.text
    series = response.json()["series"][0]
    assert series["mode"] == "raw"
    assert [row[1] for row in series["raw"]] == [4.0, None, 5.0, None]
    assert series["valid_count"] == 2
    assert series["maximum"] == 5.0


def test_interval_statistics_match_browser_semantics(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    events = _seed(database)
    response = client.get(
        "/api/v1/telemetry/history/aggregate", params=_params(buckets=1, statistics="true")
    )
    assert response.status_code == 200, response.text
    stats = response.json()["series"][0]["statistics"]
    valid = [event for event in events if event.quality == "valid"]
    assert stats["valid_count"] == len(valid)
    assert stats["invalid_count"] == 1
    assert stats["maximum"] == 19.5 and stats["minimum"] == -3.25
    assert abs(stats["valid_sum"] - sum(event.value for event in valid)) < 1e-9
    assert stats["median_spacing_ms"] == 10_000
    # Only the silent 300 s gap (index 299 -> 330) exceeds max(30 s, 3 x 10 s); the invalid sample
    # at index 200 leaves a 20 s spacing between valid samples, which is not a silent gap.
    assert stats["gap_count"] == 1
    assert stats["gap_longest_ms"] == stats["gap_total_ms"] == 310_000
    assert stats["first_valid_ms"] == epoch_ms(BASE)
    assert stats["recent_valid_ms"] == [epoch_ms(BASE + timedelta(seconds=10 * index)) for index in range(594, 600)]
    plain = client.get("/api/v1/telemetry/history/aggregate", params=_params()).json()["series"][0]
    assert plain["statistics"] is None
