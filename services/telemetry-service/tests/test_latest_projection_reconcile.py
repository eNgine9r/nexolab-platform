from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from app.application import create_app as create_application
from app.config import Settings
from app.contracts import TelemetryEvent
from app.db import Database, TelemetryQuery, TelemetrySample
from app.latest_projection_reconcile import reconcile_latest_projection


def telemetry_event(
    *,
    event_id: str,
    captured_at: datetime,
    value: float,
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=UUID(event_id),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=value,
        unit="degC",
        quality="valid",
        source="reconcile-test",
        equipment_id="K106",
        channel_id="106-03",
        alarm=None,
        raw_value=int(value * 10),
        raw_status=None,
    )


def database_for(tmp_path: Path, name: str) -> Database:
    database = Database(f"sqlite:///{tmp_path / name}")
    database.create_schema()
    return database


def insert_history_only(database: Database, event: TelemetryEvent) -> None:
    raw_payload = event.normalized_payload()
    raw_payload["stale_after_seconds"] = 15.0
    with database.engine.begin() as connection:
        connection.execute(
            insert(TelemetrySample).values(
                event_id=str(event.event_id),
                node_id=event.node_id,
                captured_at=event.captured_at,
                metric=event.metric,
                value=event.value,
                unit=event.unit,
                quality=event.quality,
                source=event.source,
                equipment_id=event.equipment_id,
                channel_id=event.channel_id,
                alarm=event.alarm,
                raw_value=event.raw_value,
                raw_status=event.raw_status,
                raw_payload=raw_payload,
                raw_payload_retained=True,
                received_at=event.captured_at + timedelta(seconds=1),
            )
        )


def test_reconcile_catches_only_post_migration_gap_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path, "reconcile.db")
    captured_at = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    baseline = telemetry_event(
        event_id="11111111-1111-4111-8111-111111111111",
        captured_at=captured_at,
        value=3.0,
    )
    newer = telemetry_event(
        event_id="22222222-2222-4222-8222-222222222222",
        captured_at=captured_at + timedelta(seconds=10),
        value=3.2,
    )
    delayed_older = telemetry_event(
        event_id="33333333-3333-4333-8333-333333333333",
        captured_at=captured_at - timedelta(minutes=5),
        value=2.8,
    )

    assert database.persist(baseline, baseline.normalized_payload())
    insert_history_only(database, newer)
    insert_history_only(database, delayed_older)

    assert reconcile_latest_projection(database) == 1
    assert reconcile_latest_projection(database) == 0

    latest = database.latest_samples(query=TelemetryQuery(), limit=10, offset=0)
    assert len(latest) == 1
    assert latest[0].event_id == str(newer.event_id)
    assert latest[0].value == 3.2
    assert latest[0].stale_after_seconds == 15.0
    assert database.count_samples() == 3
    database.dispose()


def test_reconcile_fails_closed_when_history_exists_without_projection(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path, "missing-projection.db")
    event = telemetry_event(
        event_id="44444444-4444-4444-8444-444444444444",
        captured_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        value=4.4,
    )
    insert_history_only(database, event)

    with pytest.raises(RuntimeError, match="telemetry_latest is empty"):
        reconcile_latest_projection(database)

    assert database.count_samples() == 1
    assert database.count_latest_samples() == 0
    database.dispose()


def test_reconcile_rejects_unbounded_deployment_gap_without_partial_update(
    tmp_path: Path,
) -> None:
    database = database_for(tmp_path, "bounded-gap.db")
    captured_at = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    baseline = telemetry_event(
        event_id="55555555-5555-4555-8555-555555555555",
        captured_at=captured_at,
        value=5.0,
    )
    first_gap = telemetry_event(
        event_id="66666666-6666-4666-8666-666666666666",
        captured_at=captured_at + timedelta(seconds=10),
        value=5.1,
    )
    second_gap = telemetry_event(
        event_id="77777777-7777-4777-8777-777777777777",
        captured_at=captured_at + timedelta(seconds=20),
        value=5.2,
    )

    assert database.persist(baseline, baseline.normalized_payload())
    insert_history_only(database, first_gap)
    insert_history_only(database, second_gap)

    with pytest.raises(RuntimeError, match="exceeds bounded deployment gap"):
        reconcile_latest_projection(database, max_rows=1)

    latest = database.latest_samples(query=TelemetryQuery(), limit=10, offset=0)
    assert len(latest) == 1
    assert latest[0].event_id == str(baseline.event_id)
    database.dispose()


def test_production_application_reconciles_before_ingestor_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'application-order.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
    )
    order: list[str] = []

    def fake_reconcile(_database: Database) -> int:
        order.append("reconcile")
        return 0

    monkeypatch.setattr(
        "app.application.reconcile_latest_projection",
        fake_reconcile,
    )
    app = create_application(settings)
    monkeypatch.setattr(app.state.ingestor, "start", lambda: order.append("ingestor"))
    monkeypatch.setattr(app.state.ingestor, "stop", lambda: None)

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200

    assert order[:2] == ["reconcile", "ingestor"]
