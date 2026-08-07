from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import event as sqlalchemy_event

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryQuery


def telemetry_event(
    *,
    event_id: str,
    captured_at: datetime,
    value: float,
    alarm: str | None = None,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=UUID(event_id),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=value,
        unit="degC",
        quality="valid",
        source="dixell-xjp60d",
        equipment_id="K106",
        channel_id="106-03",
        alarm=alarm,
        raw_value=int(value * 10),
        raw_status=None,
    )


def database_for(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'latest-projection.db'}")
    database.create_schema()
    return database


def test_latest_projection_is_duplicate_out_of_order_and_tie_break_safe(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path)
    captured_at = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    first = telemetry_event(
        event_id="11111111-1111-4111-8111-111111111111",
        captured_at=captured_at,
        value=3.1,
    )
    same_timestamp_newer_insert = telemetry_event(
        event_id="22222222-2222-4222-8222-222222222222",
        captured_at=captured_at,
        value=3.2,
    )
    delayed_older = telemetry_event(
        event_id="33333333-3333-4333-8333-333333333333",
        captured_at=captured_at - timedelta(minutes=5),
        value=2.9,
    )

    raw = first.normalized_payload()
    raw["stale_after_seconds"] = 10.0
    assert database.persist(first, raw)
    assert not database.persist(first, raw)
    assert database.count_samples() == 1
    assert database.count_latest_samples() == 1

    raw = same_timestamp_newer_insert.normalized_payload()
    raw["stale_after_seconds"] = 20.0
    assert database.persist(same_timestamp_newer_insert, raw)
    assert database.persist(delayed_older, delayed_older.normalized_payload())

    latest = database.latest_samples(
        query=TelemetryQuery(),
        limit=10,
        offset=0,
    )
    assert len(latest) == 1
    assert latest[0].event_id == str(same_timestamp_newer_insert.event_id)
    assert latest[0].value == 3.2
    assert latest[0].stale_after_seconds == 20.0
    assert database.count_samples() == 3
    assert database.count_latest_samples() == 1
    database.dispose()


def test_latest_projection_preserves_last_value_after_history_retention(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path)
    now = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    old = telemetry_event(
        event_id="44444444-4444-4444-8444-444444444444",
        captured_at=now - timedelta(days=400),
        value=4.4,
        alarm="high",
    )
    raw = old.normalized_payload()
    raw["stale_after_seconds"] = 30.0
    assert database.persist(old, raw)

    result = database.cleanup_retention(
        now=now,
        telemetry_retention_days=365,
        raw_payload_retention_days=30,
        dead_letter_retention_days=30,
        batch_size=100,
    )

    assert result.telemetry_deleted == 1
    assert database.count_samples() == 0
    assert database.count_latest_samples() == 1
    latest = database.latest_samples(
        query=TelemetryQuery(channel_id="106-03", alarm="high"),
        limit=10,
        offset=0,
    )
    assert len(latest) == 1
    assert latest[0].event_id == str(old.event_id)
    assert latest[0].value == 4.4
    assert latest[0].stale_after_seconds == 30.0
    database.dispose()


def test_latest_hot_path_reads_projection_without_history_window_scan(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path)
    sample = telemetry_event(
        event_id="55555555-5555-4555-8555-555555555555",
        captured_at=datetime(2026, 8, 7, 7, 0, tzinfo=UTC),
        value=5.5,
    )
    assert database.persist(sample, sample.normalized_payload())

    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lower())

    sqlalchemy_event.listen(
        database.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        rows = database.latest_samples(
            query=TelemetryQuery(channel_id="106-03"),
            limit=1,
            offset=0,
        )
    finally:
        sqlalchemy_event.remove(
            database.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert len(rows) == 1
    latest_selects = [
        statement for statement in statements if statement.lstrip().startswith("select")
    ]
    assert latest_selects
    assert any("from telemetry_latest" in statement for statement in latest_selects)
    assert all("row_number" not in statement for statement in latest_selects)
    assert all("telemetry_samples" not in statement for statement in latest_selects)
    database.dispose()


def test_postgres_backfill_defers_exclusive_lock_until_bounded_catchup() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260807_0023_add_telemetry_latest_projection.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    postgres_start = source.index("def _upgrade_postgresql()")
    sqlite_start = source.index("def _upgrade_sqlite()")
    postgres_source = source[postgres_start:sqlite_start]

    assert "row_number() OVER" not in postgres_source
    assert "CREATE TEMPORARY TABLE telemetry_latest_backfill_watermark" in postgres_source
    assert "CROSS JOIN LATERAL" in postgres_source
    assert "ON CONFLICT (node_id, equipment_id, channel_id, metric)" in source

    bulk_backfill = postgres_source.index("CROSS JOIN LATERAL")
    exclusive_lock = postgres_source.index("SELECT pg_advisory_xact_lock")
    bounded_catchup = postgres_source.index("candidate.id >")

    assert bulk_backfill < exclusive_lock < bounded_catchup
