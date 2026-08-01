from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.durable_spool import (
    DurableIngestionSpool,
    DurableSpoolCapacityError,
    DurableSpoolConflictError,
)


def test_spool_survives_reopen_and_preserves_fifo(tmp_path: Path) -> None:
    path = tmp_path / "ingestion.db"
    first = DurableIngestionSpool(path, max_records=10, max_bytes=1024)
    one = first.append_telemetry(
        event_id="event-1",
        payload=b'{"event_id":"event-1"}',
        topic="nexolab/telemetry",
        received_at=datetime.now(UTC),
        delivery_key="delivery-1",
    )
    two = first.append_dead_letter(
        payload=b"not-json",
        payload_size=8,
        payload_truncated=False,
        reason_code="invalid_json",
        reason_detail="invalid",
        topic="nexolab/telemetry",
        received_at=datetime.now(UTC),
        delivery_key="delivery-2",
    )
    first.close()

    reopened = DurableIngestionSpool(path, max_records=10, max_bytes=1024)
    assert reopened.stats().pending_records == 2
    oldest = reopened.oldest_pending()
    assert oldest is not None
    assert oldest.record_id == one.record_id

    reopened.delete(one.record_id)
    oldest = reopened.oldest_pending()
    assert oldest is not None
    assert oldest.record_id == two.record_id
    reopened.close()


def test_spool_deduplicates_only_identical_payloads(tmp_path: Path) -> None:
    spool = DurableIngestionSpool(
        tmp_path / "ingestion.db",
        max_records=10,
        max_bytes=1024,
    )
    first = spool.append_telemetry(
        event_id="event-1",
        payload=b"payload",
        topic="nexolab/telemetry",
        received_at=datetime.now(UTC),
        delivery_key="delivery-1",
    )
    duplicate = spool.append_telemetry(
        event_id="event-1",
        payload=b"payload",
        topic="nexolab/telemetry",
        received_at=datetime.now(UTC),
        delivery_key="delivery-1",
    )

    assert duplicate.record_id == first.record_id
    assert duplicate.duplicate is True

    with pytest.raises(DurableSpoolConflictError):
        spool.append_telemetry(
            event_id="event-1",
            payload=b"different",
            topic="nexolab/telemetry",
            received_at=datetime.now(UTC),
            delivery_key="delivery-1",
        )
    spool.close()


def test_spool_capacity_and_terminal_records_are_visible(tmp_path: Path) -> None:
    spool = DurableIngestionSpool(
        tmp_path / "ingestion.db",
        max_records=1,
        max_bytes=8,
    )
    appended = spool.append_dead_letter(
        payload=b"bad",
        payload_size=3,
        payload_truncated=False,
        reason_code="invalid_json",
        reason_detail="invalid",
        topic="nexolab/telemetry",
        received_at=datetime.now(UTC),
    )

    with pytest.raises(DurableSpoolCapacityError):
        spool.append_dead_letter(
            payload=b"next",
            payload_size=4,
            payload_truncated=False,
            reason_code="invalid_json",
            reason_detail="invalid",
            topic="nexolab/telemetry",
            received_at=datetime.now(UTC),
        )

    spool.mark_terminal(appended.record_id, "operator review required")
    stats = spool.stats()
    assert stats.pending_records == 0
    assert stats.terminal_records == 1
    assert stats.payload_bytes == 3
    spool.close()
