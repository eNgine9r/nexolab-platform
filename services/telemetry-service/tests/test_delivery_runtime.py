from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app


def event(*, captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=26.0,
        unit="degC",
        quality="valid",
        source="dixell-xjp60d",
        equipment_id="K106",
        channel_id="106-03",
        alarm=None,
        raw_value=260,
        raw_status=None,
    )


def app_for(tmp_path: Path, *, database_name: str = "delivery-runtime.db"):
    return create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / database_name}",
            auto_create_schema=True,
            mqtt_enabled=False,
            websocket_client_queue_maxsize=8,
            websocket_heartbeat_seconds=30,
            websocket_send_timeout_seconds=2,
            websocket_resume_limit=20,
        )
    )


def wait_for(predicate: object, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def test_refresh_reads_persisted_latest_without_ingestion(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    sample = event(captured_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC))

    with TestClient(app) as client:
        assert app.state.database.persist(sample, sample.normalized_payload())
        count_before = app.state.database.count_samples()

        for _ in range(20):
            response = client.get(
                "/api/v1/telemetry/latest",
                params={"channel_id": "106-03"},
            )
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert item["event_id"] == str(sample.event_id)
            assert item["quality"] == "valid"
            assert item["age_seconds"] >= 0
            assert item["staleness"] == "unknown"
            assert item["state_source"] == "persisted"

        runtime = app.state.runtime.snapshot()
        assert app.state.database.count_samples() == count_before == 1
        assert runtime["received_total"] == 0
        assert runtime["accepted_total"] == 0
        assert runtime["persisted_total"] == 0


def test_websocket_reconnect_churn_does_not_persist_telemetry(tmp_path: Path) -> None:
    app = app_for(tmp_path)
    payload = event(
        captured_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    ).normalized_payload()

    with TestClient(app) as client:
        before = app.state.runtime.snapshot()
        for _ in range(10):
            with client.websocket_connect("/api/v1/telemetry/live") as websocket:
                app.state.live_hub.publish_committed(payload)
                assert websocket.receive_json()["state_source"] == "persisted"
            app.state.live_hub.publish_committed(payload)
            wait_for(
                lambda: app.state.runtime.snapshot()["websocket_clients"] == 0
            )

        after = app.state.runtime.snapshot()
        assert after["websocket_clients"] == 0
        assert (
            after["websocket_connect_total"]
            - before["websocket_connect_total"]
            == 10
        )
        assert after["received_total"] == before["received_total"] == 0
        assert after["accepted_total"] == before["accepted_total"] == 0
        assert after["persisted_total"] == before["persisted_total"] == 0
        assert app.state.database.count_samples() == 0


def test_restart_latest_and_resume_use_the_existing_database(tmp_path: Path) -> None:
    database_name = "delivery-restart.db"
    base = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    sample = event(captured_at=base)

    first_app = app_for(tmp_path, database_name=database_name)
    with TestClient(first_app):
        assert first_app.state.database.persist(
            sample,
            sample.normalized_payload(),
        )

    second_app = app_for(tmp_path, database_name=database_name)
    with TestClient(second_app) as client:
        latest = client.get(
            "/api/v1/telemetry/latest",
            params={"channel_id": "106-03"},
        )
        assert latest.status_code == 200
        assert latest.json()["items"][0]["event_id"] == str(sample.event_id)

        query = urlencode(
            {
                "channel_id": "106-03",
                "after": (base - timedelta(seconds=1)).isoformat(),
            }
        )
        with client.websocket_connect(
            f"/api/v1/telemetry/live?{query}"
        ) as websocket:
            replay = websocket.receive_json()

        assert replay["event_id"] == str(sample.event_id)
        assert replay["state_source"] == "persisted"
        runtime = second_app.state.runtime.snapshot()
        assert runtime["received_total"] == 0
        assert runtime["accepted_total"] == 0
        assert runtime["persisted_total"] == 0
        assert second_app.state.database.count_samples() == 1
