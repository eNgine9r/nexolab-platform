from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app.contracts import TelemetryEvent
from app.db import Database


def event(event_id: str, captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent.model_validate(
        {
            "event_id": event_id,
            "node_id": "edge-01",
            "captured_at": captured_at.isoformat(),
            "metric": "temperature.probe",
            "value": 26.0,
            "unit": "degC",
            "quality": "valid",
            "source": "dixell-xjp60d",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "alarm": "high",
            "raw_value": 260,
            "raw_status": 4354,
        }
    )


def test_retention_deletes_and_redacts_in_bounded_batches(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()

    old = event(
        "11111111-1111-4111-8111-111111111111",
        now - timedelta(days=400),
    )
    recent = event(
        "22222222-2222-4222-8222-222222222222",
        now - timedelta(minutes=1),
    )
    assert database.persist(old, old.normalized_payload())
    assert database.persist(recent, recent.normalized_payload())
    database.persist_dead_letter(
        payload=b"not-json",
        payload_size=8,
        payload_truncated=False,
        reason_code="invalid_json",
        reason_detail="test fixture",
        topic="nexolab/telemetry",
    )

    old_received_at = now - timedelta(days=40)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE telemetry_samples SET received_at = :received_at "
                "WHERE event_id = :event_id"
            ),
            {
                "received_at": old_received_at,
                "event_id": str(recent.event_id),
            },
        )
        connection.execute(
            text(
                "UPDATE telemetry_dead_letters SET received_at = :received_at"
            ),
            {"received_at": old_received_at},
        )

    result = database.cleanup_retention(
        now=now,
        telemetry_retention_days=365,
        raw_payload_retention_days=30,
        dead_letter_retention_days=30,
        batch_size=1,
    )

    assert result.telemetry_deleted == 1
    assert result.raw_payloads_redacted == 1
    assert result.dead_letters_deleted == 1
    assert database.count_samples() == 1
    assert database.count_retained_raw_payloads() == 0
    assert database.count_dead_letters() == 0
    database.dispose()
