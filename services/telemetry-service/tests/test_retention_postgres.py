"""Evidence-aware retention SQL on real PostgreSQL (#1551).

Runs only when CI provides a migrated PostgreSQL DATABASE_URL. Retention deletes
every eligible row in the database, so this test uses a synthetic clock in the
year 2000: only its own 1999 rows are older than the cutoff, and rows written by
other tests (2026 timestamps) can never become eligible.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.contracts import TelemetryEvent
from app.db import Database
from app.model_registry import register_models

register_models()

NOW = datetime(2000, 1, 31, tzinfo=UTC)


def _event(captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="retention-integration",
        captured_at=captured_at,
        metric="temperature.probe",
        value=21.0,
        unit="degC",
        quality="valid",
        source="dixell-xjp60d",
        equipment_id="K999",
        channel_id="999-01",
        alarm="high",
        raw_value=210,
        raw_status=4354,
    )


@pytest.fixture()
def database() -> Database:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database is not configured")
    database = Database(url)
    with database.engine.connect() as connection:
        if connection.execute(text("SELECT to_regclass('telemetry_session_contexts')")).scalar() is None:
            database.dispose()
            pytest.skip("PostgreSQL schema is not migrated")
    yield database
    with database.engine.begin() as connection:
        connection.execute(text("DELETE FROM telemetry_samples WHERE node_id = 'retention-integration'"))
        connection.execute(text("DELETE FROM telemetry_latest WHERE node_id = 'retention-integration'"))
    database.dispose()


def test_postgres_retention_deletes_only_old_ordinary_samples_in_bounded_batches(database: Database) -> None:
    old = [_event(NOW - timedelta(days=40, minutes=index)) for index in range(5)]
    recent = _event(NOW - timedelta(days=1))
    for sample in (*old, recent):
        assert database.persist(sample, sample.normalized_payload())

    inventory = database.retention_inventory(now=NOW, telemetry_retention_days=30)
    assert inventory.eligible >= 5
    assert inventory.older_than_cutoff == inventory.eligible + inventory.preserved_session_evidence

    disabled = database.cleanup_retention(
        now=NOW,
        telemetry_retention_days=30,
        raw_payload_retention_days=36500,
        dead_letter_retention_days=36500,
        batch_size=2,
        delete_telemetry=False,
    )
    assert disabled.telemetry_deleted == 0

    deleted = 0
    for _ in range(10):
        result = database.cleanup_retention(
            now=NOW,
            telemetry_retention_days=30,
            raw_payload_retention_days=36500,
            dead_letter_retention_days=36500,
            batch_size=2,
        )
        assert result.telemetry_deleted <= 2
        deleted += result.telemetry_deleted
        if result.telemetry_deleted == 0:
            break

    with database.engine.connect() as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                text("SELECT event_id FROM telemetry_samples WHERE node_id = 'retention-integration'")
            )
        }
    assert remaining == {str(recent.event_id)}
    assert deleted >= 5
