from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.mqtt_consumer import MqttConsumer, load_mqtt_password


def test_settings_reject_partial_mqtt_credentials() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(mqtt_username="nexolab-central-ingestion")


def test_settings_requires_credentials_in_secure_mode() -> None:
    with pytest.raises(ValidationError, match="credentials are required"):
        Settings(mqtt_auth_required=True)


def test_load_mqtt_password_accepts_one_trailing_newline(tmp_path: Path) -> None:
    password_file = tmp_path / "mqtt-password"
    password_file.write_text("secret-value\n", encoding="utf-8")

    assert load_mqtt_password(str(password_file)) == "secret-value"


def test_load_mqtt_password_rejects_multiple_lines(tmp_path: Path) -> None:
    password_file = tmp_path / "mqtt-password"
    password_file.write_text("first\nsecond\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exactly one secret"):
        load_mqtt_password(str(password_file))


def test_consumer_configures_username_and_password(tmp_path: Path) -> None:
    password_file = tmp_path / "mqtt-password"
    password_file.write_text("secret-value", encoding="utf-8")
    settings = Settings(
        mqtt_auth_required=True,
        mqtt_username="nexolab-central-ingestion",
        mqtt_password_file=str(password_file),
        mqtt_client_id="nexolab-central-ingestion",
    )
    ingestor = Mock()
    state = Mock()

    with patch("paho.mqtt.client.Client") as client_factory:
        MqttConsumer(settings, ingestor, state)

    client_factory.return_value.username_pw_set.assert_called_once_with(
        "nexolab-central-ingestion",
        "secret-value",
    )
