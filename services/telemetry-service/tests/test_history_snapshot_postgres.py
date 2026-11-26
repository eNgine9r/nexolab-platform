"""#1807: history reads must not hold the snapshot lock or starve the shared connection pool.

Production evidence (2026-11-26): `QueuePool limit of size 5 overflow 10 reached` in
`history_snapshot_samples` while operators loaded charts; the browser aborted at 8 s.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

import app.db as db_module
from app.api import create_api_router
from app.contracts import TelemetryEvent
from app.db import (
    HISTORY_READ_POOL_SIZE,
    TELEMETRY_HISTORY_ADVISORY_LOCK_ID,
    Database,
    HistoryCapacityError,
    TelemetryQuery,
    TelemetrySample,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for advisory-lock and connection-pool evidence",
)

BASE = datetime(2026, 11, 25, 12, tzinfo=UTC)


@pytest.fixture
def database():
    instance = Database(os.environ["DATABASE_URL"])
    instance.create_schema()
    node_id = f"history-1807-{uuid4().hex[:12]}"
    try:
        yield instance, node_id
    finally:
        with instance.engine.begin() as connection:
            connection.execute(delete(TelemetrySample).where(TelemetrySample.node_id == node_id))
        instance.dispose()


def _event(node_id: str, index: int, channel_id: str = "temperature-1") -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id=node_id,
        captured_at=BASE + timedelta(seconds=10 * index),
        metric="temperature",
        value=4.0 + index / 100,
        unit="degC",
        quality="valid",
        source="history-1807-test",
        equipment_id="XJP60D-1807",
        channel_id=channel_id,
        alarm=None,
        raw_value=400 + index,
        raw_status=0,
    )


def _query(node_id: str, channel_id: str = "temperature-1") -> TelemetryQuery:
    return TelemetryQuery(
        node_id=node_id,
        equipment_id="XJP60D-1807",
        channel_id=channel_id,
        metric="temperature",
        from_at=BASE - timedelta(hours=1),
        to_at=BASE + timedelta(days=2),
    )


def _slow_statement(seconds: float):
    def statement(*, query, limit, offset):  # noqa: ARG001 - same signature as _history_statement
        return select(TelemetrySample).where(text(f"(SELECT 1 FROM pg_sleep({seconds})) = 1")).limit(1)

    return statement


def test_history_select_runs_without_holding_the_snapshot_lock(database) -> None:
    instance, node_id = database
    for index in range(3):
        event = _event(node_id, index)
        assert instance.persist(event, event.normalized_payload())
    instance._history_statement = _slow_statement(1.5)  # type: ignore[method-assign]
    outcome: dict[str, object] = {}

    def load() -> None:
        try:
            outcome["result"] = instance.history_snapshot_samples(query=_query(node_id), limit=10, offset=0)
        except Exception as error:  # pragma: no cover - surfaced by the assertion below
            outcome["error"] = error

    worker = threading.Thread(target=load)
    worker.start()
    time.sleep(0.6)
    # Ingestion takes this lock shared for every insert. Before #1807 the history SELECT held it
    # exclusively for its whole duration, so this probe (and every insert) was blocked.
    with instance.engine.begin() as connection:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_xact_lock_shared(:lock_id)"),
            {"lock_id": TELEMETRY_HISTORY_ADVISORY_LOCK_ID},
        )
    worker.join(timeout=10)
    assert "error" not in outcome, outcome.get("error")
    assert acquired is True


def test_ingestion_persists_while_history_capacity_is_exhausted(database) -> None:
    instance, node_id = database
    held = [instance.history_engine.connect() for _ in range(HISTORY_READ_POOL_SIZE)]
    try:
        started = time.perf_counter()
        event = _event(node_id, 1)
        assert instance.persist(event, event.normalized_payload())
        assert time.perf_counter() - started < 2.0

        started = time.perf_counter()
        with pytest.raises(HistoryCapacityError):
            instance.history_snapshot_samples(query=_query(node_id), limit=10, offset=0)
        # Fails inside the browser's 8 s request budget instead of the 30 s default checkout.
        assert time.perf_counter() - started < 5.0
    finally:
        for connection in held:
            connection.close()


def test_history_statement_timeout_is_reported_as_capacity(database, monkeypatch) -> None:
    instance, node_id = database
    monkeypatch.setattr(db_module, "HISTORY_READ_STATEMENT_TIMEOUT_MS", 200)
    instance._history_statement = _slow_statement(2.0)  # type: ignore[method-assign]
    started = time.perf_counter()
    with pytest.raises(HistoryCapacityError):
        instance.history_snapshot_samples(
            query=_query(node_id),
            limit=10,
            offset=0,
            snapshot_at=BASE + timedelta(days=3),
        )
    assert time.perf_counter() - started < 1.5


def test_history_endpoint_answers_503_with_retry_after_when_capacity_is_exhausted(database) -> None:
    instance, node_id = database
    application = FastAPI()
    application.include_router(create_api_router(instance, max_history_days=31, max_page_size=1000))
    client = TestClient(application)
    held = [instance.history_engine.connect() for _ in range(HISTORY_READ_POOL_SIZE)]
    try:
        response = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": (BASE - timedelta(hours=1)).isoformat(),
                "to": (BASE + timedelta(hours=1)).isoformat(),
                "node_id": node_id,
            },
        )
    finally:
        for connection in held:
            connection.close()
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "1"


def _plan_index_names(value: object) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        index_name = value.get("Index Name")
        if isinstance(index_name, str):
            names.add(index_name)
        for child in value.values():
            names.update(_plan_index_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_plan_index_names(child))
    return names


def test_sparse_channel_history_page_uses_a_channel_index(database) -> None:
    """A sparse channel among dense channels must not walk the metric index of every channel."""
    instance, node_id = database
    with instance.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO telemetry_samples (
                    event_id, node_id, captured_at, metric, value, unit, quality, source,
                    equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload, received_at
                )
                SELECT gen_random_uuid()::text, :node_id,
                       :base + make_interval(secs => step * 10), 'temperature', 4 + (step % 50) / 10.0,
                       'degC', 'valid', 'history-1807-test', 'XJP60D-1807', 'dense-' || channel,
                       NULL, 400, 0, '{}'::json, :base + make_interval(secs => step * 10)
                FROM generate_series(1, 16) AS channel, generate_series(0, 8639) AS step
                """
            ),
            {"node_id": node_id, "base": BASE},
        )
        connection.execute(
            text(
                """
                INSERT INTO telemetry_samples (
                    event_id, node_id, captured_at, metric, value, unit, quality, source,
                    equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload, received_at
                )
                SELECT gen_random_uuid()::text, :node_id,
                       :base + make_interval(secs => step * 3600), 'temperature', 5,
                       'degC', 'valid', 'history-1807-test', 'XJP60D-1807', 'sparse-1',
                       NULL, 500, 0, '{}'::json, :base + make_interval(secs => step * 3600)
                FROM generate_series(0, 23) AS step
                """
            ),
            {"node_id": node_id, "base": BASE},
        )
        connection.execute(text("ANALYZE telemetry_samples"))

    query = TelemetryQuery(
        node_id=node_id,
        equipment_id="XJP60D-1807",
        channel_id="sparse-1",
        metric="temperature",
        from_at=BASE,
        to_at=BASE + timedelta(days=1),
        received_before=BASE + timedelta(days=2),
    )
    statement = instance._history_statement(query=query, limit=1001, offset=0)
    compiled = statement.compile(dialect=instance.engine.dialect, compile_kwargs={"literal_binds": True})
    with instance.engine.begin() as connection:
        plan = connection.scalar(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {compiled}"))
    document = plan if isinstance(plan, list) else json.loads(plan)
    names = _plan_index_names(document)
    execution_ms = float(document[0]["Execution Time"])
    print(f"sparse-channel history plan indexes={sorted(names)} execution_ms={execution_ms:.2f}")
    assert names & {"ix_telemetry_history_lookup", "ix_telemetry_channel_captured", "ix_telemetry_latest_lookup"}
    assert "ix_telemetry_metric_captured" not in names

    started = time.perf_counter()
    rows, _ = instance.history_snapshot_samples(
        query=TelemetryQuery(
            node_id=node_id,
            equipment_id="XJP60D-1807",
            channel_id="dense-1",
            metric="temperature",
            from_at=BASE,
            to_at=BASE + timedelta(days=1),
        ),
        limit=1001,
        offset=0,
    )
    page_ms = (time.perf_counter() - started) * 1000
    print(f"dense-channel 1001-row page ms={page_ms:.1f}")
    assert len(rows) == 1001
