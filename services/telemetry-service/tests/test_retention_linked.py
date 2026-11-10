"""Regression: 30-day monitoring retention must not erase test-session evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app.config import Settings
from app.db import Database
from app.model_registry import register_models
from tests.test_retention import event


def test_default_ordinary_telemetry_retention_is_30_days() -> None:
    assert Settings.model_fields["telemetry_retention_days"].default == 30


def test_expired_linked_sample_and_raw_payload_survive_retention(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    database = Database(f"sqlite:///{tmp_path / 'linked-retention.db'}")
    register_models()
    database.create_schema()

    linked = event("11111111-1111-4111-8111-111111111111", now - timedelta(days=70))
    unlinked = event("22222222-2222-4222-8222-222222222222", now - timedelta(days=40))
    current = event("33333333-3333-4333-8333-333333333333", now - timedelta(days=1))
    for sample in (linked, unlinked, current):
        assert database.persist(sample, sample.normalized_payload())

    with database.engine.begin() as connection:
        # Only the reference to the real, registered context table matters here.
        # Session-domain FK construction is covered by the session schema tests.
        connection.execute(
            text(
                "INSERT INTO telemetry_session_contexts "
                "(telemetry_event_id, session_id, binding_id, "
                "config_snapshot_id, captured_at, resolver_version) "
                "VALUES (:event_id, :session_id, :binding_id, "
                ":snapshot_id, :captured_at, :resolver_version)"
            ),
            {
                "event_id": str(linked.event_id),
                "session_id": "44444444-4444-4444-8444-444444444444",
                "binding_id": "55555555-5555-4555-8555-555555555555",
                "snapshot_id": "66666666-6666-4666-8666-666666666666",
                "captured_at": linked.captured_at,
                "resolver_version": "test",
            },
        )
        connection.execute(
            text(
                "UPDATE telemetry_samples SET received_at = :received_at "
                "WHERE event_id IN (:linked, :unlinked)"
            ),
            {
                "received_at": now - timedelta(days=35),
                "linked": str(linked.event_id),
                "unlinked": str(unlinked.event_id),
            },
        )

    result = database.cleanup_retention(
        now=now,
        telemetry_retention_days=30,
        raw_payload_retention_days=30,
        dead_letter_retention_days=30,
        batch_size=1,
    )
    assert result.telemetry_deleted == 1
    assert result.raw_payloads_redacted == 0

    with database.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT event_id, raw_payload_retained FROM telemetry_samples")
        ).all()
        contexts = connection.execute(
            text("SELECT telemetry_event_id FROM telemetry_session_contexts")
        ).all()
    assert {row[0] for row in rows} == {str(linked.event_id), str(current.event_id)}
    assert {row[0] for row in contexts} == {str(linked.event_id)}
    assert next(row[1] for row in rows if row[0] == str(linked.event_id)) == 1

    repeated = database.cleanup_retention(
        now=now,
        telemetry_retention_days=30,
        raw_payload_retention_days=30,
        dead_letter_retention_days=30,
        batch_size=1,
    )
    assert repeated.telemetry_deleted == 0
    assert repeated.raw_payloads_redacted == 0
    database.dispose()
