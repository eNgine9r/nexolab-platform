from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


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


def test_prometheus_metrics_and_json_snapshot(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'telemetry.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert app.state.ingestor.submit_payload(payload())
        assert not app.state.ingestor.submit_payload(b"not-json")
        wait_for(
            lambda: app.state.runtime.snapshot()["persisted_total"] == 1
            and app.state.runtime.snapshot()["dead_letter_persisted_total"] == 1
        )

        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "nexolab_telemetry_persisted_total 1" in response.text
        assert "nexolab_telemetry_rejected_total 1" in response.text
        assert (
            'nexolab_telemetry_dead_letter_reason_total{reason_code="invalid_json"} 1'
            in response.text
        )
        assert "nexolab_telemetry_ingestion_lag_seconds" in response.text
        assert "nexolab_telemetry_last_persisted_timestamp_seconds" in response.text

        snapshot = client.get("/metrics/json").json()
        assert snapshot["persisted_total"] == 1
        assert snapshot["dead_letter_persisted_total"] == 1
        assert snapshot["ingestion_lag_seconds"] is not None
        assert snapshot["last_persisted_at"] is not None
