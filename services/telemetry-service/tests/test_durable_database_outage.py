from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest

from app.db import Database
from app.durable_spool import DurableIngestionSpool
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState


def wait_for(predicate: Callable[[], bool], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition was not met before timeout")


def run_docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=True,
        text=True,
        capture_output=True,
    )


def wait_for_postgres(container_id: str) -> None:
    def ready() -> bool:
        result = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "pg_isready",
                "-U",
                "nexolab",
                "-d",
                "nexolab_test",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        return result.returncode == 0

    wait_for(ready, timeout=30.0)


def payload(event_id: str) -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "node_id": "edge-01",
            "captured_at": datetime.now(UTC).isoformat(),
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


@pytest.mark.database_outage
def test_durable_spool_survives_service_restart_during_postgres_outage(
    tmp_path: Path,
) -> None:
    container_id = os.getenv("POSTGRES_CONTAINER_ID")
    database_url = os.getenv("DATABASE_URL")
    if not container_id or not database_url:
        pytest.skip("requires the CI PostgreSQL service container")

    database = Database(database_url, connect_timeout_seconds=1)
    baseline_samples = database.count_samples()
    event_id = str(uuid4())
    spool_path = tmp_path / "ingestion-spool.db"
    postgres_started = True
    first_ingestor: TelemetryIngestor | None = None
    second_ingestor: TelemetryIngestor | None = None
    first_spool: DurableIngestionSpool | None = None
    second_spool: DurableIngestionSpool | None = None

    try:
        run_docker("stop", "--time", "1", container_id)
        postgres_started = False

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
            database_retry_initial_seconds=0.1,
            database_retry_max_seconds=0.5,
        )
        staged = first_ingestor.stage_mqtt_payload(
            payload(event_id),
            topic="nexolab/telemetry",
            delivery_key="mqtt-delivery-1",
        )
        assert staged.staged is True
        first_ingestor.start()
        wait_for(
            lambda: first_state.snapshot()["database_retry_total"] > 0,
            timeout=10.0,
        )
        assert first_spool.stats().pending_records == 1

        first_ingestor.stop(timeout=2.0)
        first_ingestor = None
        first_spool.close()
        first_spool = None

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
            database_retry_initial_seconds=0.1,
            database_retry_max_seconds=0.5,
        )
        second_ingestor.start()
        wait_for(
            lambda: second_state.snapshot()["database_retry_total"] > 0,
            timeout=10.0,
        )
        assert second_state.snapshot()["spool_recovered_total"] == 1
        assert second_spool.stats().pending_records == 1

        run_docker("start", container_id)
        postgres_started = True
        wait_for_postgres(container_id)

        wait_for(
            lambda: database.count_samples() == baseline_samples + 1,
            timeout=30.0,
        )
        wait_for(
            lambda: second_spool.stats().pending_records == 0,
            timeout=10.0,
        )
        snapshot = second_state.snapshot()
        assert snapshot["spool_replayed_total"] == 1
        assert snapshot["spool_terminal_records"] == 0
    finally:
        if not postgres_started:
            run_docker("start", container_id)
            wait_for_postgres(container_id)
        if first_ingestor is not None:
            first_ingestor.stop(timeout=2.0)
        if second_ingestor is not None:
            second_ingestor.stop(timeout=2.0)
        if first_spool is not None:
            first_spool.close()
        if second_spool is not None:
            second_spool.close()
        database.dispose()
