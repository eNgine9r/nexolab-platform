"""Source-only central MQTT QoS1 receipt transport (#1445).

A broker PUBACK proves broker acceptance, NOT Edge reception and NOT a
verified publisher ACL. Do not connect this class to the installed runtime
until dedicated MQTT identity/ACL review and isolated acceptance are complete.
"""
from __future__ import annotations

import json
from threading import Event
from typing import Any
from uuid import UUID

from app.committed_receipt_publisher import MAX_RECEIPT_BYTES
from app.mqtt_consumer import load_mqtt_password
from app.mqtt_tls import MQTTTLSConfig


class CommittedReceiptMqttSender:
    """Dedicated, non-retained MQTT 3.1.1 QoS1 transport for DB-backed replies.

    Do NOT reuse the ingestion subscriber's username/client-id. Separate
    broker authorization must allow central publish and disallow node publish
    on exactly the receipts topics. Connection success is NOT ACL proof.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: str,
        username: str,
        password_file: str,
        tls_config: MQTTTLSConfig,
        connect_timeout_seconds: float = 3.0,
        puback_timeout_seconds: float = 5.0,
        mqtt_module: Any | None = None,
    ) -> None:
        if not host.strip() or not client_id.strip() or not username.strip():
            raise ValueError("dedicated_receipt_broker_identity_required")
        if not password_file.strip():
            raise ValueError("dedicated_receipt_password_file_required")
        if not 1 <= port <= 65535 or connect_timeout_seconds <= 0 or puback_timeout_seconds <= 0:
            raise ValueError("invalid_receipt_broker_policy")
        if mqtt_module is None:
            try:
                import paho.mqtt.client as mqtt_module
            except ImportError as exc:
                raise RuntimeError("paho_mqtt_required_for_receipt_transport") from exc
        self._mqtt = mqtt_module
        self._host = host
        self._port = port
        self._connect_timeout_seconds = connect_timeout_seconds
        self._puback_timeout_seconds = puback_timeout_seconds
        self._connected = Event()
        self._started = False
        client = mqtt_module.Client(
            callback_api_version=mqtt_module.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
            protocol=mqtt_module.MQTTv311,
        )
        client.username_pw_set(username, load_mqtt_password(password_file))
        tls_config.apply(client)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        self._client = client

    def start(self) -> None:
        if self._started:
            raise RuntimeError("receipt_transport_already_started")
        self._connected.clear()
        self._client.connect_async(self._host, self._port, 60)
        self._client.loop_start()
        self._started = True

    def stop(self) -> None:
        self._connected.clear()
        if self._started:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()
                self._started = False

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del client, userdata, flags, properties
        if reason_code == 0:
            self._connected.set()
        else:
            self._connected.clear()

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        del client, userdata, flags, reason_code, properties
        self._connected.clear()

    @staticmethod
    def _identity_matches(topic: str, body: bytes) -> bool:
        if not isinstance(topic, str) or not isinstance(body, bytes):
            return False
        if not 0 < len(body) <= MAX_RECEIPT_BYTES:
            return False
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return False
            expected = {
                "contract_version", "receipt_id", "event_id",
                "organization_id", "node_id", "stream",
                "node_sequence", "receipt_level", "accepted_at",
            }
            if set(payload) != expected:
                return False
            if payload["contract_version"] != 1 or type(payload["contract_version"]) is not int:
                return False
            if payload["receipt_level"] != "postgres_committed" or payload["stream"] != "telemetry":
                return False
            if type(payload["node_sequence"]) is not int or payload["node_sequence"] < 1:
                return False
            for value in (payload["receipt_id"], payload["event_id"], payload["organization_id"]):
                if not isinstance(value, str) or str(UUID(value)) != value:
                    return False
            node = payload["node_id"]
            if not isinstance(node, str) or not node or "/" in node or "+" in node or "#" in node:
                return False
            if not isinstance(payload["accepted_at"], str):
                return False
            return topic == f'nexolab/v1/{payload["organization_id"]}/{node}/receipts'
        except (UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def __call__(self, topic: str, payload: bytes) -> bool:
        """Report success only when paho confirms the broker's QoS1 PUBACK.

        The callback does not attest origin ACL configuration or Edge delivery.
        The caller's durable DB outbox owns replay after failures.
        """
        if not self._identity_matches(topic, payload) or not self._started:
            return False
        if not self._connected.wait(self._connect_timeout_seconds):
            return False
        try:
            published = self._client.publish(topic, payload, qos=1, retain=False)
            if published.rc != self._mqtt.MQTT_ERR_SUCCESS:
                return False
            published.wait_for_publish(timeout=self._puback_timeout_seconds)
            return published.is_published() is True
        except Exception:
            # Transport remains retryable; do not leak credentials or payload.
            self._connected.clear()
            return False
