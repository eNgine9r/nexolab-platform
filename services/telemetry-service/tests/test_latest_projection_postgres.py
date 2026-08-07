from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, text

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryLatest, TelemetryQuery, TelemetrySample


@pytest.mark.integration
def test_postgres_latest_projection_query_is_history_volume_independent() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database is not configured")

    database = Database(database_url)
    node_id = f"latest-perf-{uuid4()}"
    base = datetime(2026, 8, 7, 7, 0, tzinfo=UTC)
    series_count = 200
    history_per_series = 40

    def cleanup() -> None:
        with database.engine.begin() as connection:
            connection.execute(
                delete(TelemetryLatest).where(TelemetryLatest.node_id == node_id)
            )
            connection.execute(
                delete(TelemetrySample).where(TelemetrySample.node_id == node_id)
            )

    cleanup()
    try:
        for series_index in range(series_count):
            latest = TelemetryEvent(
                event_id=uuid4(),
                node_id=node_id,
                captured_at=base,
                metric="temperature.probe",
                value=float(series_index),
                unit="degC",
                quality="valid",
                source="performance-fixture",
                equipment_id=f"equipment-{series_index // 20:03d}",
                channel_id=f"channel-{series_index:04d}",
                alarm=None,
                raw_value=series_index,
                raw_status=None,
            )
            assert database.persist(latest, latest.normalized_payload())

        history_rows = []
        for series_index in range(series_count):
            equipment_id = f"equipment-{series_index // 20:03d}"
            channel_id = f"channel-{series_index:04d}"
            for history_index in range(1, history_per_series + 1):
                history_rows.append(
                    {
                        "event_id": str(uuid4()),
                        "node_id": node_id,
                        "captured_at": base - timedelta(seconds=history_index),
                        "metric": "temperature.probe",
                        "value": float(series_index) - history_index / 100.0,
                        "unit": "degC",
                        "quality": "valid",
                        "source": "performance-fixture",
                        "equipment_id": equipment_id,
                        "channel_id": channel_id,
                        "alarm": None,
                        "raw_value": series_index,
                        "raw_status": None,
                        "raw_payload": {},
                        "raw_payload_retained": True,
                    }
                )

        with database.engine.begin() as connection:
            connection.execute(insert(TelemetrySample), history_rows)

        started = perf_counter()
        rows = database.latest_samples(
            query=TelemetryQuery(node_id=node_id),
            limit=series_count,
            offset=0,
        )
        elapsed_ms = (perf_counter() - started) * 1000.0

        assert len(rows) == series_count
        assert elapsed_ms < 500.0

        statement = (
            select(TelemetryLatest)
            .where(TelemetryLatest.node_id == node_id)
            .order_by(
                TelemetryLatest.captured_at.desc(),
                TelemetryLatest.event_id.desc(),
            )
            .limit(series_count)
        )
        compiled = statement.compile(
            database.engine,
            compile_kwargs={"literal_binds": True},
        )
        with database.engine.connect() as connection:
            plan = connection.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")
            ).scalar_one()

        plan_text = json.dumps(plan)
        assert "telemetry_latest" in plan_text
        assert "telemetry_samples" not in plan_text
        assert float(plan[0]["Execution Time"]) < 500.0
    finally:
        cleanup()
        database.dispose()
