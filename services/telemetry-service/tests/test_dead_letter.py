from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from app.db import Database
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def test_invalid_json_is_persisted_as_dead_letter(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=10)
    ingestor.start()

    assert not ingestor.submit_payload(b"not-json", topic="nexolab/telemetry")
    wait_for(lambda: database.count_dead_letters() == 1)

    ingestor.stop()
    records = database.list_dead_letters()
    assert database.count_samples() == 0
    assert len(records) == 1
    assert records[0].topic == "nexolab/telemetry"
    assert records[0].reason_code == "invalid_json"
    assert records[0].payload == b"not-json"
    assert records[0].payload_size == len(b"not-json")
    assert records[0].payload_truncated is False

    snapshot = state.snapshot()
    assert snapshot["rejected_total"] == 1
    assert snapshot["dead_letter_queued_total"] == 1
    assert snapshot["dead_letter_persisted_total"] == 1
    assert snapshot["dead_letter_by_reason"] == {"invalid_json": 1}
    database.dispose()


def test_schema_failure_does_not_enter_telemetry_table(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=10)
    ingestor.start()

    assert not ingestor.submit_payload(b'{"event_id":"not-a-uuid"}')
    wait_for(lambda: database.count_dead_letters() == 1)

    ingestor.stop()
    assert database.count_samples() == 0
    assert database.list_dead_letters()[0].reason_code == "schema_validation"
    database.dispose()


def test_oversized_dead_letter_payload_is_bounded(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        payload_max_bytes=5,
        dead_letter_payload_max_bytes=4,
    )
    ingestor.start()

    assert not ingestor.submit_payload(b"123456")
    wait_for(lambda: database.count_dead_letters() == 1)

    ingestor.stop()
    record = database.list_dead_letters()[0]
    assert record.reason_code == "payload_too_large"
    assert record.payload == b"1234"
    assert record.payload_size == 6
    assert record.payload_truncated is True
    database.dispose()
