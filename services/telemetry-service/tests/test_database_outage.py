from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

import pytest

from app.db import Database
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


def payload() -> bytes:
    return json.dumps(
        {
            "event_id": str(uuid4()),
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
def test_accepted_work_survives_postgres_restart() -> None:
    container_id = os.getenv("POSTGRES_CONTAINER_ID")
    database_url = os.getenv("DATABASE_URL")
    if not container_id or not database_url:
        pytest.skip("requires the CI PostgreSQL service container")

    database = Database(database_url, connect_timeout_seconds=1)
    baseline_samples = database.count_samples()
    baseline_dead_letters = database.count_dead_letters()
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        database_retry_initial_seconds=0.1,
        database_retry_max_seconds=0.5,
    )
    ingestor.start()
    postgres_started = True

    try:
        run_docker("stop", "--time", "1", container_id)
        postgres_started = False

        assert ingestor.submit_payload(payload())
        assert not ingestor.submit_payload(
            b"not-json",
            topic="nexolab/telemetry",
        )
        wait_for(
            lambda: state.snapshot()["database_retry_total"] > 0,
            timeout=10.0,
        )
        assert state.snapshot()["database_ready"] is False
        assert state.snapshot()["database_outage_since"] is not None
        assert state.snapshot()["queue_size"] >= 1

        run_docker("start", container_id)
        postgres_started = True
        wait_for_postgres(container_id)

        wait_for(
            lambda: state.snapshot()["persisted_total"] == 1
            and state.snapshot()["dead_letter_persisted_total"] == 1,
            timeout=30.0,
        )
        wait_for(
            lambda: database.count_samples() == baseline_samples + 1
            and database.count_dead_letters() == baseline_dead_letters + 1,
            timeout=10.0,
        )

        snapshot = state.snapshot()
        assert snapshot["queue_size"] == 0
        assert snapshot["database_ready"] is True
        assert snapshot["database_error"] is None
        assert snapshot["database_recovery_total"] >= 1
    finally:
        if not postgres_started:
            run_docker("start", container_id)
            wait_for_postgres(container_id)
        ingestor.stop(timeout=10.0)
        database.dispose()
