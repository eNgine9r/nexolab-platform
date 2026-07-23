from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.mqtt")


class MqttConsumer:
    def __init__(
        self,
        settings: Settings,
        ingestor: TelemetryIngestor,
        state: RuntimeState,
    ) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("paho-mqtt is required when MQTT is enabled") from exc

        self._mqtt = mqtt
        self._settings = settings
        self._ingestor = ingestor
        self._state = state
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message

    def start(self) -> None:
        self._state.set_mqtt_connected(False)
        self._client.connect_async(
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            self._settings.mqtt_keepalive_seconds,
        )
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._state.set_mqtt_connected(False)
            self._state.set_mqtt_error(None)

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del userdata, flags, properties
        if reason_code == 0:
            self._state.set_mqtt_connected(False)
            result, _ = client.subscribe(
                self._settings.mqtt_topic,
                qos=self._settings.mqtt_qos,
            )
            if result != self._mqtt.MQTT_ERR_SUCCESS:
                self._state.set_mqtt_error(f"MQTT subscribe failed: {result}")
        else:
            self._state.set_mqtt_connected(False)
            self._state.set_mqtt_error(
                f"MQTT connection rejected: {reason_code}"
            )

    def _on_subscribe(
        self,
        client: Any,
        userdata: Any,
        mid: int,
        reason_code_list: Any,
        properties: Any,
    ) -> None:
        del client, userdata, mid, properties
        failed = any(getattr(code, "is_failure", False) for code in reason_code_list)
        if failed:
            self._state.set_mqtt_connected(False)
            self._state.set_mqtt_error("MQTT subscription was rejected")
            return
        self._state.set_mqtt_connected(True)
        self._state.set_mqtt_error(None)
        LOGGER.info("Subscribed to MQTT topic %s", self._settings.mqtt_topic)

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del client, userdata, disconnect_flags, properties
        self._state.set_mqtt_connected(False)
        if reason_code != 0:
            message = f"unexpected MQTT disconnect: {reason_code}"
            self._state.set_mqtt_error(message)
            LOGGER.warning(message)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        del client, userdata
        self._ingestor.submit_payload(message.payload, topic=message.topic)
