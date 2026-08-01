from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from threading import Event
from typing import Any

from app.config import Settings
from app.ingestion import TelemetryIngestor
from app.mqtt_tls import MQTTTLSConfig
from app.nodes.domain import NodeTopicStream, parse_node_topic
from app.nodes.stream_ingestion import NodeStreamIngestor
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.mqtt")


def load_mqtt_password(password_file: str) -> str:
    path = Path(password_file)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"MQTT password file is not readable: {path}") from exc
    password = content.rstrip("\r\n")
    if not password:
        raise RuntimeError("MQTT password file must not be empty")
    if "\r" in password or "\n" in password:
        raise RuntimeError("MQTT password file must contain exactly one secret")
    return password


class MqttConsumer:
    def __init__(
        self,
        settings: Settings,
        ingestor: TelemetryIngestor,
        state: RuntimeState,
        node_stream_ingestor: NodeStreamIngestor | None = None,
    ) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("paho-mqtt is required when MQTT is enabled") from exc

        self._mqtt = mqtt
        self._settings = settings
        self._ingestor = ingestor
        self._state = state
        self._stop = Event()
        self._manual_ack = ingestor.durable_enabled
        self._node_stream_ingestor = node_stream_ingestor
        if self._node_stream_ingestor is None and settings.mqtt_node_registry_enforced:
            self._node_stream_ingestor = NodeStreamIngestor(
                ingestor._database,  # noqa: SLF001 - shared service persistence boundary
                state,
                queue_maxsize=settings.ingestion_queue_maxsize,
                payload_max_bytes=settings.ingestion_payload_max_bytes,
                dead_letter_payload_max_bytes=settings.dead_letter_payload_max_bytes,
                database_retry_initial_seconds=settings.database_retry_initial_seconds,
                database_retry_max_seconds=settings.database_retry_max_seconds,
            )
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            clean_session=not self._manual_ack,
            protocol=mqtt.MQTTv311,
            manual_ack=self._manual_ack,
        )
        if settings.mqtt_username is not None:
            if settings.mqtt_password_file is None:  # validated by Settings
                raise RuntimeError("MQTT password file is required")
            self._client.username_pw_set(
                settings.mqtt_username,
                load_mqtt_password(settings.mqtt_password_file),
            )
        self._mqtt_tls = MQTTTLSConfig.from_settings(settings)
        self._mqtt_tls.apply(self._client)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message

    def start(self) -> None:
        self._stop.clear()
        self._state.set_mqtt_connected(False)
        if self._node_stream_ingestor is not None:
            self._node_stream_ingestor.start()
        self._client.connect_async(
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            self._settings.mqtt_keepalive_seconds,
        )
        self._client.loop_start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            if self._node_stream_ingestor is not None:
                self._node_stream_ingestor.stop()
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
            subscriptions = [
                (topic, self._settings.mqtt_qos)
                for topic in self._settings.resolved_mqtt_topics
            ]
            result, _ = client.subscribe(subscriptions)
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
        LOGGER.info(
            "Subscribed to MQTT topics %s",
            ", ".join(self._settings.resolved_mqtt_topics),
        )

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
        del userdata
        if not self._settings.mqtt_node_registry_enforced:
            self._ingest_telemetry_message(client, message)
            return

        try:
            parsed = parse_node_topic(message.topic)
        except ValueError:
            self._ingest_telemetry_message(client, message)
            return

        if parsed.stream is NodeTopicStream.TELEMETRY:
            self._ingest_telemetry_message(client, message)
            return

        if (
            parsed.stream in {NodeTopicStream.HEALTH, NodeTopicStream.STATUS}
            and self._node_stream_ingestor is not None
        ):
            submitted = self._node_stream_ingestor.submit_payload(
                message.payload,
                topic=message.topic,
            )
            if submitted:
                self._ack_message(client, message)
            else:
                self._state.set_mqtt_error(
                    f"node stream message {message.mid} was not accepted"
                )
            return

        LOGGER.warning("No dispatcher configured for MQTT topic %s", message.topic)

    def _ingest_telemetry_message(self, client: Any, message: Any) -> None:
        if not self._manual_ack:
            self._ingestor.submit_payload(
                message.payload,
                topic=message.topic,
            )
            return

        delivery_key = self._delivery_key(message)
        retry_delay = self._settings.database_retry_initial_seconds
        is_retry = False
        while not self._stop.is_set():
            result = self._ingestor.stage_mqtt_payload(
                message.payload,
                topic=message.topic,
                delivery_key=delivery_key,
                is_retry=is_retry,
            )
            if result.staged:
                self._ack_message(client, message)
                return

            self._state.increment("mqtt_stage_retry_total")
            self._state.set_mqtt_error(
                result.error or "MQTT payload was not durably staged"
            )
            LOGGER.error(
                "MQTT message %s remains unacknowledged; retrying durable "
                "staging in %.2fs",
                message.mid,
                retry_delay,
            )
            if self._stop.wait(retry_delay):
                return
            retry_delay = min(
                retry_delay * 2,
                self._settings.database_retry_max_seconds,
            )
            is_retry = True

    def _ack_message(self, client: Any, message: Any) -> None:
        if not self._manual_ack or int(message.qos) == 0:
            return
        result = client.ack(message.mid, message.qos)
        if result == self._mqtt.MQTT_ERR_SUCCESS:
            self._state.increment("mqtt_manual_ack_total")
            self._state.set_mqtt_error(None)
            return
        self._state.increment("mqtt_ack_failure_total")
        self._state.set_mqtt_error(
            f"manual MQTT acknowledgement failed for {message.mid}: {result}"
        )
        LOGGER.error(
            "Manual MQTT acknowledgement failed for mid=%s qos=%s result=%s",
            message.mid,
            message.qos,
            result,
        )

    def _delivery_key(self, message: Any) -> str:
        digest = hashlib.sha256(message.payload).hexdigest()
        return (
            f"{self._settings.mqtt_client_id}:"
            f"{message.topic}:{message.mid}:{message.qos}:{digest}"
        )
