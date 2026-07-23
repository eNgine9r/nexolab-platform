from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryQuery, TelemetrySample


@pytest.mark.integration
def test_postgres_migration_idempotency_and_queries() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database is not configured")

    database = Database(database_url)
    event_ids = [uuid4(), uuid4()]
    captured_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    events = [
        TelemetryEvent(
            event_id=event_ids[0],
            node_id="integration-edge",
            captured_at=captured_at,
            metric="temperature.probe",
            value=25.6,
            unit="degC",
            quality="valid",
            source="dixell-xjp60d",
            equipment_id="K106",
            channel_id="106-04",
            alarm="high",
            raw_value=256,
            raw_status=4354,
        ),
        TelemetryEvent(
            event_id=event_ids[1],
            node_id="integration-edge",
            captured_at=captured_at + timedelta(seconds=5),
            metric="temperature.probe",
            value=26.0,
            unit="degC",
            quality="valid",
            source="dixell-xjp60d",
            equipment_id="K106",
            channel_id="106-04",
            alarm="high",
            raw_value=260,
            raw_status=4354,
        ),
    ]

    def cleanup() -> None:
        with database.engine.begin() as connection:
            connection.execute(
                delete(TelemetrySample).where(
                    TelemetrySample.event_id.in_([str(value) for value in event_ids])
                )
            )

    try:
        assert database.ping()
        cleanup()

        assert database.persist(events[0], events[0].normalized_payload())
        assert not database.persist(events[0], events[0].normalized_payload())
        assert database.persist(events[1], events[1].normalized_payload())

        query = TelemetryQuery(
            node_id="integration-edge",
            equipment_id="K106",
            channel_id="106-04",
        )
        latest = database.latest_samples(query=query, limit=10, offset=0)
        assert len(latest) == 1
        assert latest[0].event_id == str(event_ids[1])
        assert latest[0].value == 26.0

        history = database.history_samples(
            query=TelemetryQuery(
                node_id="integration-edge",
                channel_id="106-04",
                from_at=captured_at - timedelta(seconds=1),
                to_at=captured_at + timedelta(seconds=10),
            ),
            limit=10,
            offset=0,
        )
        assert [sample.event_id for sample in history] == [
            str(event_ids[1]),
            str(event_ids[0]),
        ]
    finally:
        cleanup()
        database.dispose()
