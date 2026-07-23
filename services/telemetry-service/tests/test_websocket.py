from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app


def event(
    *,
    captured_at: datetime,
    channel_id: str,
    metric: str,
    value: float,
) -> TelemetryEvent:
    temperature = metric.startswith("temperature")
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit="degC" if temperature else "V",
        quality="valid",
        source="dixell-xjp60d" if temperature else "f-and-f-le-01mp",
        equipment_id="K106" if temperature else "LE01MP-201",
        channel_id=channel_id,
        alarm="high" if temperature else None,
        raw_value=int(value * 10),
        raw_status=4354 if temperature else None,
    )


def wait_for(predicate: object, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def app_for(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'live.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        websocket_client_queue_maxsize=8,
        websocket_heartbeat_seconds=30,
        websocket_send_timeout_seconds=2,
        websocket_resume_limit=20,
    )
    return create_app(settings)


def test_only_successfully_persisted_events_reach_filtered_clients(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    captured_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    voltage = event(
        captured_at=captured_at,
        channel_id="201-voltage",
        metric="electrical.voltage",
        value=227.3,
    )
    temperature = event(
        captured_at=captured_at,
        channel_id="106-03",
        metric="temperature.probe",
        value=26.0,
    )

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/telemetry/live?metric=electrical.voltage"
        ) as voltage_socket:
            with client.websocket_connect(
                "/api/v1/telemetry/live?channel_id=106-03"
            ) as temperature_socket:
                assert app.state.ingestor.submit_payload(
                    json.dumps(voltage.normalized_payload()).encode()
                )
                assert app.state.ingestor.submit_payload(
                    json.dumps(temperature.normalized_payload()).encode()
                )

                voltage_message = voltage_socket.receive_json()
                temperature_message = temperature_socket.receive_json()

                assert voltage_message["event_id"] == str(voltage.event_id)
                assert voltage_message["channel_id"] == "201-voltage"
                assert temperature_message["event_id"] == str(temperature.event_id)
                assert temperature_message["raw_status"] == 4354

                wait_for(
                    lambda: app.state.runtime.snapshot()["persisted_total"] == 2
                )
                snapshot = app.state.runtime.snapshot()
                assert snapshot["websocket_broadcast_total"] == 2
                assert snapshot["websocket_filtered_total"] == 2

                assert app.state.ingestor.submit_payload(
                    json.dumps(voltage.normalized_payload()).encode()
                )
                wait_for(
                    lambda: app.state.runtime.snapshot()["duplicate_total"] == 1
                )
                assert app.state.runtime.snapshot()["websocket_broadcast_total"] == 2


def test_resume_replays_committed_events_oldest_first(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    base = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    first = event(
        captured_at=base,
        channel_id="106-03",
        metric="temperature.probe",
        value=25.5,
    )
    second = event(
        captured_at=base + timedelta(seconds=5),
        channel_id="106-03",
        metric="temperature.probe",
        value=26.0,
    )

    with TestClient(app) as client:
        database = app.state.database
        assert database.persist(first, first.normalized_payload())
        assert database.persist(second, second.normalized_payload())

        query = urlencode(
            {
                "channel_id": "106-03",
                "after": (base - timedelta(seconds=1)).isoformat(),
            }
        )
        with client.websocket_connect(
            f"/api/v1/telemetry/live?{query}"
        ) as websocket:
            first_message = websocket.receive_json()
            second_message = websocket.receive_json()

        assert [first_message["event_id"], second_message["event_id"]] == [
            str(first.event_id),
            str(second.event_id),
        ]
        assert app.state.runtime.snapshot()["websocket_resume_total"] == 2
