from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import DeliveryState, RenderedMessage
from app.outbox import DeliveryOutbox, DeliveryOutboxError
from tests.support import sample_snapshot


NOW = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)
DESTINATION = "-1001234567890"


def message() -> RenderedMessage:
    return RenderedMessage(
        text="report",
        button_url="https://t.me/nexolab_bot/nexolab?startapp=report_snapshot-1",
    )


def test_successful_delivery_is_not_reenqueued_after_restart(tmp_path) -> None:
    path = tmp_path / "outbox.db"
    first = DeliveryOutbox(str(path))
    created, replayed = first.enqueue(sample_snapshot(), DESTINATION, message(), now=NOW)
    assert replayed is False
    claimed = first.claim_next(now=NOW)
    assert claimed is not None and claimed.id == created.id and claimed.attempts == 1
    sent = first.mark_sent(claimed.id, telegram_message_id=77, now=NOW)
    assert sent.state is DeliveryState.SENT

    second = DeliveryOutbox(str(path))
    existing, replayed = second.enqueue(sample_snapshot(), DESTINATION, message(), now=NOW)
    assert replayed is True
    assert existing.state is DeliveryState.SENT
    assert existing.telegram_message_id == 77
    assert second.claim_next(now=NOW + timedelta(days=1)) is None


def test_snapshot_identity_cannot_be_reused_for_different_content(tmp_path) -> None:
    outbox = DeliveryOutbox(str(tmp_path / "outbox.db"))
    snapshot = sample_snapshot()
    outbox.enqueue(snapshot, DESTINATION, message(), now=NOW)
    changed = replace(sample_snapshot(), payload_sha256="f" * 64)
    with pytest.raises(DeliveryOutboxError):
        outbox.enqueue(changed, DESTINATION, message(), now=NOW)


def test_retry_and_stale_sending_recovery_are_explicit(tmp_path) -> None:
    outbox = DeliveryOutbox(str(tmp_path / "outbox.db"))
    outbox.enqueue(sample_snapshot(), DESTINATION, message(), now=NOW)
    claimed = outbox.claim_next(now=NOW)
    assert claimed is not None
    retried = outbox.mark_retry(
        claimed.id,
        delay=timedelta(seconds=10),
        error_code="telegram_server_error",
        now=NOW,
    )
    assert retried.state is DeliveryState.RETRY_WAIT
    assert retried.available_at == NOW + timedelta(seconds=10)
    assert outbox.claim_next(now=NOW + timedelta(seconds=9)) is None

    second_claim = outbox.claim_next(now=NOW + timedelta(seconds=10))
    assert second_claim is not None and second_claim.attempts == 2
    recovered = outbox.recover_stale_sending(
        stale_after=timedelta(seconds=30),
        now=NOW + timedelta(seconds=50),
    )
    assert recovered == 1
    record = outbox.get_by_snapshot("snapshot-1", DESTINATION)
    assert record is not None
    assert record.state is DeliveryState.RETRY_WAIT
    assert record.duplicate_risk is True
    assert record.last_error_code == "delivery_outcome_unknown_after_restart"
    assert outbox.counts()["duplicate_risk"] == 1


def test_outbox_uses_private_filesystem_permissions(tmp_path) -> None:
    path = tmp_path / "private" / "outbox.db"
    DeliveryOutbox(str(path))
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600


def test_read_only_inspection_does_not_create_missing_outbox(tmp_path) -> None:
    path = tmp_path / "missing" / "outbox.db"
    assert DeliveryOutbox.inspect_existing(
        str(path),
        "snapshot-1",
        DESTINATION,
    ) is None
    assert path.exists() is False
    assert path.parent.exists() is False


def test_exact_claim_cannot_consume_unrelated_pending_delivery(tmp_path) -> None:
    outbox = DeliveryOutbox(str(tmp_path / "outbox.db"))
    unrelated = sample_snapshot(snapshot_id="snapshot-unrelated")
    target = sample_snapshot(snapshot_id="snapshot-target")
    outbox.enqueue(unrelated, DESTINATION, message(), now=NOW)
    target_record, _ = outbox.enqueue(target, DESTINATION, message(), now=NOW)

    claimed = outbox.claim_exact(target.id, DESTINATION, now=NOW)

    assert claimed.id == target_record.id
    assert claimed.snapshot_id == target.id
    assert claimed.state is DeliveryState.SENDING
    untouched = outbox.get_by_snapshot(unrelated.id, DESTINATION)
    assert untouched is not None
    assert untouched.state is DeliveryState.PENDING
    assert untouched.attempts == 0


def test_general_and_forum_topic_destinations_do_not_alias(tmp_path) -> None:
    outbox = DeliveryOutbox(str(tmp_path / "outbox.db"))
    snapshot = sample_snapshot()
    general, general_replayed = outbox.enqueue(snapshot, DESTINATION, message(), now=NOW)
    topic, topic_replayed = outbox.enqueue(
        snapshot,
        DESTINATION,
        message(),
        destination_message_thread_id=73,
        now=NOW,
    )

    assert general_replayed is False
    assert topic_replayed is False
    assert general.id != topic.id
    assert general.destination_message_thread_id is None
    assert topic.destination_message_thread_id == 73
    assert outbox.get_by_snapshot(snapshot.id, DESTINATION) == general
    assert outbox.get_by_snapshot(snapshot.id, DESTINATION, 73) == topic


def test_legacy_general_delivery_migrates_without_becoming_topic_delivery(tmp_path) -> None:
    import sqlite3

    path = tmp_path / "outbox.db"
    stamp = NOW.isoformat(timespec="microseconds")
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE telegram_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                destination_chat_id TEXT NOT NULL,
                rendered_text TEXT NOT NULL,
                button_url TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TEXT NOT NULL,
                locked_at TEXT,
                last_attempt_at TEXT,
                last_error_code TEXT,
                telegram_message_id INTEGER,
                sent_at TEXT,
                duplicate_risk INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(snapshot_id, destination_chat_id)
            )
            """
        )
        snapshot = sample_snapshot()
        connection.execute(
            """
            INSERT INTO telegram_deliveries (
                snapshot_id, snapshot_sha256, destination_chat_id, rendered_text, button_url,
                state, attempts, available_at, telegram_message_id, sent_at, duplicate_risk,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'sent', 1, ?, 77, ?, 0, ?, ?)
            """,
            (
                snapshot.id,
                snapshot.payload_sha256,
                DESTINATION,
                message().text,
                message().button_url,
                stamp,
                stamp,
                stamp,
                stamp,
            ),
        )

    assert DeliveryOutbox.inspect_existing(str(path), "snapshot-1", DESTINATION, 73) is None
    legacy_general = DeliveryOutbox.inspect_existing(str(path), "snapshot-1", DESTINATION)
    assert legacy_general is not None and legacy_general.state is DeliveryState.SENT

    migrated = DeliveryOutbox(str(path))
    general = migrated.get_by_snapshot("snapshot-1", DESTINATION)
    assert general is not None
    assert general.state is DeliveryState.SENT
    assert general.telegram_message_id == 77
    assert general.destination_message_thread_id is None
    assert migrated.get_by_snapshot("snapshot-1", DESTINATION, 73) is None

    topic, replayed = migrated.enqueue(
        sample_snapshot(),
        DESTINATION,
        message(),
        destination_message_thread_id=73,
        now=NOW,
    )
    assert replayed is False
    assert topic.destination_message_thread_id == 73
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(telegram_deliveries)")}
        assert "destination_message_thread_id" in columns
        assert connection.execute("SELECT COUNT(*) FROM telegram_deliveries").fetchone()[0] == 2
