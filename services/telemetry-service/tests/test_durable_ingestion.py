from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from app.db import Database
from app.durable_spool import DurableIngestionSpool
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def payload(event_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or str(uuid4()),
            "node_id": "edge-01",
            "captured_at": datetime.now(UTC).isoformat(),
            "metric": "temperature",
            "value": 4.2,
            "unit": "degC",
            "quality": "valid",
            "source": "dixell-xjp60d",
            "equipment_id": "XJP60D-106",
            "channel_id": "106-03",
            "alarm": None,
            "raw_value": 42,
            "raw_status": None,
        }
    ).encode()


def test_staged_event_replays_after_process_restart(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    spool_path = tmp_path / "spool.db"
    event_id = str(uuid4())

    first_spool = DurableIngestionSpool(
        spool_path,
        max_records=100,
        max_bytes=1024 * 1024,
    )
    first_state = RuntimeState()
    first_ingestor = TelemetryIngestor(
        database,
        first_state,
        queue_maxsize=10,
        durable_spool=first_spool,
    )
    result = first_ingestor.stage_mqtt_payload(
        payload(event_id),
        topic="nexolab/telemetry",
        delivery_key="delivery-1",
    )
    assert result.staged is True
    assert first_spool.stats().pending_records == 1

    # Simulate a process termination after local durable commit and before
    # PostgreSQL persistence. The MQTT message is safe to acknowledge here.
    first_spool.close()

    second_spool = DurableIngestionSpool(
        spool_path,
        max_records=100,
        max_bytes=1024 * 1024,
    )
    second_state = RuntimeState()
    second_ingestor = TelemetryIngestor(
        database,
        second_state,
        queue_maxsize=10,
        durable_spool=second_spool,
    )
    second_ingestor.start()

    wait_for(lambda: database.count_samples() == 1)
    wait_for(lambda: second_spool.stats().pending_records == 0)

    snapshot = second_state.snapshot()
    assert snapshot["spool_recovered_total"] == 1
    assert snapshot["spool_replayed_total"] == 1

    second_ingestor.stop()
    second_spool.close()
    database.dispose()


def test_invalid_payload_is_durably_staged_before_ack(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    spool = DurableIngestionSpool(
        tmp_path / "spool.db",
        max_records=100,
        max_bytes=1024 * 1024,
    )
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        durable_spool=spool,
    )

    result = ingestor.stage_mqtt_payload(
        b"not-json",
        topic="nexolab/telemetry",
        delivery_key="delivery-invalid",
    )

    assert result.staged is True
    assert result.accepted is False
    assert spool.stats().pending_records == 1

    ingestor.start()
    wait_for(lambda: database.count_dead_letters() == 1)
    wait_for(lambda: spool.stats().pending_records == 0)

    ingestor.stop()
    spool.close()
    database.dispose()


def test_event_id_remains_idempotent_after_spool_replay(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    spool = DurableIngestionSpool(
        tmp_path / "spool.db",
        max_records=100,
        max_bytes=1024 * 1024,
    )
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        durable_spool=spool,
    )
    event_id = str(uuid4())
    encoded = payload(event_id)

    assert ingestor.stage_mqtt_payload(
        encoded,
        topic="nexolab/telemetry",
        delivery_key="delivery-1",
    ).staged
    assert ingestor.stage_mqtt_payload(
        encoded,
        topic="nexolab/telemetry",
        delivery_key="delivery-1",
    ).duplicate

    ingestor.start()
    wait_for(lambda: database.count_samples() == 1)
    wait_for(lambda: spool.stats().pending_records == 0)

    assert ingestor.stage_mqtt_payload(
        encoded,
        topic="nexolab/telemetry",
        delivery_key="delivery-2",
    ).staged
    wait_for(lambda: state.snapshot()["duplicate_total"] == 1)
    wait_for(lambda: spool.stats().pending_records == 0)
    assert database.count_samples() == 1

    ingestor.stop()
    spool.close()
    database.dispose()
