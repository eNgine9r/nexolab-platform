from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.ingestion import TelemetryIngestor
from app.main import create_app
from app.mqtt_consumer import MqttConsumer
from app.state import RuntimeState


def test_dashboard_cors_is_explicit_and_origin_scoped() -> None:
    app = create_app(
        Settings(
            database_url="sqlite://",
            auto_create_schema=True,
            mqtt_enabled=False,
            retention_enabled=False,
            cors_allowed_origins=(
                "https://dashboard.nexolab.example, http://127.0.0.1:3000/"
            ),
        )
    )

    with TestClient(app) as client:
        allowed = client.options(
            "/api/v1/telemetry/latest",
            headers={
                "Origin": "https://dashboard.nexolab.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/api/v1/telemetry/latest",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://dashboard.nexolab.example"
    )
    assert "access-control-allow-origin" not in denied.headers


def test_mqtt_credentials_are_applied_when_configured() -> None:
    database = Database("sqlite://")
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=4)
    settings = Settings(
        database_url="sqlite://",
        mqtt_username="telemetry-ingestion",
        mqtt_password="secret-value",
    )

    with patch(
        "paho.mqtt.client.Client.username_pw_set",
        autospec=True,
    ) as username_pw_set:
        MqttConsumer(settings, ingestor, state)

    username_pw_set.assert_called_once()
    _, username, password = username_pw_set.call_args.args
    assert username == "telemetry-ingestion"
    assert password == "secret-value"
    database.dispose()


def test_cors_origin_parser_trims_and_removes_trailing_slashes() -> None:
    settings = Settings(
        cors_allowed_origins=(
            " https://one.example/,https://two.example , ,http://localhost:3000/"
        )
    )

    assert settings.parsed_cors_allowed_origins == [
        "https://one.example",
        "https://two.example",
        "http://localhost:3000",
    ]
