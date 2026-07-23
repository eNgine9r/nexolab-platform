from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.contracts import TelemetryEvent
from app.db import TelemetrySample
from app.main import create_app


def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not met before timeout")


def publish_fixture(topic: str, payload: dict[str, object]) -> None:
    publisher = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"nexolab-e2e-publisher-{uuid4()}",
        protocol=mqtt.MQTTv311,
    )
    publisher.connect("127.0.0.1", 1883, 30)
    publisher.loop_start()
    try:
        result = publisher.publish(topic, json.dumps(payload), qos=1)
        result.wait_for_publish(timeout=5)
        assert result.rc == mqtt.MQTT_ERR_SUCCESS
    finally:
        publisher.disconnect()
        publisher.loop_stop()


@pytest.mark.e2e
def test_mqtt_fixture_persists_once_and_reaches_rest_and_websocket() -> None:
    if os.environ.get("MQTT_E2E") != "true":
        pytest.skip("MQTT end-to-end broker is not configured")

    database_url = os.environ["DATABASE_URL"]
    topic = f"nexolab/telemetry/e2e/{uuid4()}"
    event = TelemetryEvent(
        event_id=uuid4(),
        node_id=f"e2e-edge-{uuid4()}",
        captured_at=datetime.now(UTC),
        metric="electrical.voltage",
        value=228.4,
        unit="V",
        quality="valid",
        source="f-and-f-le-01mp",
        equipment_id="LE01MP-201",
        channel_id="201-voltage",
        alarm=None,
        raw_value=2284,
        raw_status=None,
    )
    settings = Settings(
        database_url=database_url,
        auto_create_schema=False,
        mqtt_enabled=True,
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        mqtt_topic=topic,
        mqtt_client_id=f"nexolab-e2e-consumer-{uuid4()}",
        websocket_heartbeat_seconds=30,
        websocket_send_timeout_seconds=5,
    )
    app = create_app(settings)

    def cleanup() -> None:
        with app.state.database.engine.begin() as connection:
            connection.execute(
                delete(TelemetrySample).where(
                    TelemetrySample.event_id == str(event.event_id)
                )
            )

    try:
        cleanup()
        with TestClient(app) as client:
            wait_for(lambda: client.get("/health/ready").status_code == 200)

            with client.websocket_connect(
                "/api/v1/telemetry/live?channel_id=201-voltage"
            ) as websocket:
                publish_fixture(topic, event.normalized_payload())
                live_message = websocket.receive_json()

            assert live_message["event_id"] == str(event.event_id)
            assert live_message["value"] == 228.4

            wait_for(
                lambda: client.get(
                    "/api/v1/telemetry/latest",
                    params={"node_id": event.node_id},
                ).json()["count"]
                == 1
            )
            latest = client.get(
                "/api/v1/telemetry/latest",
                params={"node_id": event.node_id},
            ).json()
            assert latest["items"][0]["event_id"] == str(event.event_id)

            publish_fixture(topic, event.normalized_payload())
            wait_for(
                lambda: app.state.runtime.snapshot()["duplicate_total"] >= 1
            )

            history = client.get(
                "/api/v1/telemetry/history",
                params={
                    "from": (event.captured_at - timedelta(seconds=1)).isoformat(),
                    "to": (event.captured_at + timedelta(seconds=1)).isoformat(),
                    "node_id": event.node_id,
                    "channel_id": event.channel_id,
                },
            )
            assert history.status_code == 200
            history_payload = history.json()
            assert history_payload["count"] == 1
            assert history_payload["items"][0]["event_id"] == str(event.event_id)
    finally:
        cleanup()
        app.state.database.dispose()
