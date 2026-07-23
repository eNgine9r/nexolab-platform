from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.contracts import TelemetryEvent
from app.db import TelemetrySample
from app.main import create_app


@pytest.mark.integration
def test_postgres_migration_idempotency_and_rest_queries() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database is not configured")

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

    app = create_app(
        Settings(
            database_url=database_url,
            auto_create_schema=False,
            mqtt_enabled=False,
        )
    )

    with TestClient(app) as client:
        database = app.state.database

        def cleanup() -> None:
            with database.engine.begin() as connection:
                connection.execute(
                    delete(TelemetrySample).where(
                        TelemetrySample.event_id.in_(
                            [str(value) for value in event_ids]
                        )
                    )
                )

        assert database.ping()
        cleanup()
        try:
            assert database.persist(events[0], events[0].normalized_payload())
            assert not database.persist(events[0], events[0].normalized_payload())
            assert database.persist(events[1], events[1].normalized_payload())

            latest = client.get(
                "/api/v1/telemetry/latest",
                params={
                    "node_id": "integration-edge",
                    "equipment_id": "K106",
                    "channel_id": "106-04",
                },
            )
            assert latest.status_code == 200
            latest_payload = latest.json()
            assert latest_payload["count"] == 1
            assert latest_payload["items"][0]["event_id"] == str(event_ids[1])
            assert latest_payload["items"][0]["value"] == 26.0

            history = client.get(
                "/api/v1/telemetry/history",
                params={
                    "node_id": "integration-edge",
                    "channel_id": "106-04",
                    "from": (captured_at - timedelta(seconds=1)).isoformat(),
                    "to": (captured_at + timedelta(seconds=10)).isoformat(),
                },
            )
            assert history.status_code == 200
            history_payload = history.json()
            assert [item["event_id"] for item in history_payload["items"]] == [
                str(event_ids[1]),
                str(event_ids[0]),
            ]
        finally:
            cleanup()
