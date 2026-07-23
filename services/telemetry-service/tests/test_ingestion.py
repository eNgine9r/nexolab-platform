from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from app.db import Database
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState


def payload() -> bytes:
    return json.dumps(
        {
            "event_id": "56bb5d38-1c20-48c7-bfaf-8d3101da9e21",
            "node_id": "edge-01",
            "captured_at": "2026-07-23T09:27:52.785640+00:00",
            "metric": "electrical.voltage",
            "value": 227.3,
            "unit": "V",
            "quality": "valid",
            "source": "f-and-f-le-01mp",
            "equipment_id": "LE01MP-201",
            "channel_id": "201-voltage",
            "alarm": None,
            "raw_value": 2273,
            "raw_status": None,
        }
    ).encode()


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def test_ingestion_is_idempotent(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=10)
    ingestor.start()

    assert ingestor.submit_payload(payload())
    assert ingestor.submit_payload(payload())

    wait_for(
        lambda: (
            state.snapshot()["persisted_total"]
            + state.snapshot()["duplicate_total"]
        )
        == 2
    )

    ingestor.stop()
    assert database.count_samples() == 1
    snapshot = state.snapshot()
    assert snapshot["persisted_total"] == 1
    assert snapshot["duplicate_total"] == 1
    database.dispose()


def test_invalid_payload_is_rejected(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=10)
    ingestor.start()

    assert not ingestor.submit_payload(b"not-json")
    assert state.snapshot()["rejected_total"] == 1

    ingestor.stop()
    database.dispose()
