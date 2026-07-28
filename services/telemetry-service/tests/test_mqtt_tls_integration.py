from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.mqtt_consumer import MqttConsumer


@patch("app.mqtt_consumer.MQTTTLSConfig.from_settings")
@patch("paho.mqtt.client.Client")
def test_consumer_applies_tls_before_reconnect_setup(
    client_factory: Mock,
    tls_from_settings: Mock,
) -> None:
    settings = Settings(mqtt_enabled=False)
    client = client_factory.return_value
    tls_config = tls_from_settings.return_value

    def assert_before_reconnect(_client: Mock) -> None:
        assert _client is client
        client.reconnect_delay_set.assert_not_called()

    tls_config.apply.side_effect = assert_before_reconnect

    consumer = MqttConsumer(settings, Mock(), Mock())

    assert consumer._mqtt_tls is tls_config
    tls_from_settings.assert_called_once_with(settings)
    tls_config.apply.assert_called_once_with(client)
    client.reconnect_delay_set.assert_called_once_with(
        min_delay=1,
        max_delay=30,
    )


def test_settings_reject_tls_material_without_tls_mode() -> None:
    with pytest.raises(ValidationError, match="MQTT_TLS_REQUIRED"):
        Settings(
            mqtt_enabled=False,
            mqtt_tls_ca_file="/run/secrets/ca.pem",
        )


def test_settings_require_ca_and_atomic_client_identity() -> None:
    with pytest.raises(ValidationError, match="MQTT_TLS_CA_FILE"):
        Settings(mqtt_enabled=False, mqtt_tls_required=True)

    with pytest.raises(ValidationError, match="configured together"):
        Settings(
            mqtt_enabled=False,
            mqtt_tls_required=True,
            mqtt_tls_ca_file="/run/secrets/ca.pem",
            mqtt_tls_cert_file="/run/secrets/client.pem",
        )
