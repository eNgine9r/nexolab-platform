from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryQuery
from app.delivery import PersistedTelemetryReadModel


def event(*, captured_at: datetime, quality: str = "valid") -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=26.0 if quality == "valid" else None,
        unit="degC",
        quality=quality,
        source="dixell-xjp60d",
        equipment_id="K106",
        channel_id="106-03",
        alarm=None,
        raw_value=260 if quality == "valid" else None,
        raw_status=None,
    )


def database_for(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'delivery.db'}")
    database.create_schema()
    return database


def test_read_model_projects_age_quality_and_source_owned_staleness(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    database = database_for(tmp_path)
    sample = event(captured_at=now - timedelta(seconds=20))
    raw = sample.normalized_payload()
    raw["stale_after_seconds"] = 10.0
    assert database.persist(sample, raw)

    read_model = PersistedTelemetryReadModel(database, clock=lambda: now)
    rows = read_model.latest_samples(
        query=TelemetryQuery(),
        limit=10,
        offset=0,
    )

    assert len(rows) == 1
    payload = rows[0]
    assert payload["quality"] == "valid"
    assert payload["age_seconds"] == 20.0
    assert payload["stale_after_seconds"] == 10.0
    assert payload["is_stale"] is True
    assert payload["staleness"] == "stale"
    assert payload["state_source"] == "persisted"
    assert payload["received_at"]


def test_missing_source_threshold_is_explicitly_unknown(tmp_path: Path) -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    database = database_for(tmp_path)
    sample = event(
        captured_at=now - timedelta(minutes=5),
        quality="communication_error",
    )
    assert database.persist(sample, sample.normalized_payload())

    read_model = PersistedTelemetryReadModel(database, clock=lambda: now)
    payload = read_model.latest_samples(
        query=TelemetryQuery(),
        limit=10,
        offset=0,
    )[0]

    assert payload["quality"] == "communication_error"
    assert payload["age_seconds"] == 300.0
    assert payload["stale_after_seconds"] is None
    assert payload["is_stale"] is None
    assert payload["staleness"] == "unknown"
    assert payload["state_source"] == "persisted"


def test_repeated_latest_reads_never_mutate_persisted_state(tmp_path: Path) -> None:
    now = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    database = database_for(tmp_path)
    sample = event(captured_at=now)
    assert database.persist(sample, sample.normalized_payload())
    read_model = PersistedTelemetryReadModel(database, clock=lambda: now)

    before = database.count_samples()
    for _ in range(50):
        rows = read_model.latest_samples(
            query=TelemetryQuery(channel_id="106-03"),
            limit=10,
            offset=0,
        )
        assert rows[0]["event_id"] == str(sample.event_id)
    assert database.count_samples() == before == 1
