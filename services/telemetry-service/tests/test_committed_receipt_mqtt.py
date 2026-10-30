"""Hermetic unit checks; fake MQTT callbacks do NOT prove broker ACL."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.committed_receipt_mqtt import CommittedReceiptMqttSender
from app.mqtt_tls import MQTTTLSConfig


ORG = str(uuid4())
NODE = "receipt-edge-01"


class FakeMessageInfo:
    def __init__(self, ack: bool) -> None:
        self.rc = 0
        self.ack = ack
        self.waited = False

    def wait_for_publish(self, timeout: float) -> None:
        assert timeout > 0
        self.waited = True

    def is_published(self) -> bool:
        return self.ack and self.waited


class FakeClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_disconnect = None
        self.sent: list[tuple[str, bytes, int, bool]] = []
        self.ack = True
        self.start_connect = True
        self.username = ""
        self.password = ""
        self.client_id = ""

    def username_pw_set(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        assert host == "isolated-mqtt"
        assert port == 1883
        assert keepalive == 60

    def loop_start(self) -> None:
        if self.start_connect:
            assert self.on_connect is not None
            self.on_connect(self, None, None, 0, None)

    def loop_stop(self) -> None:
        return

    def disconnect(self) -> None:
        if self.on_disconnect is not None:
            self.on_disconnect(self, None, None, 0, None)

    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> FakeMessageInfo:
        self.sent.append((topic, payload, qos, retain))
        return FakeMessageInfo(self.ack)


def make_sender(tmp_path):
    password = tmp_path / "dedicated-receipt-password"
    password.write_text("synthetic-test-only\n", encoding="utf-8")
    password.chmod(0o600)
    client = FakeClient()
    module = SimpleNamespace(
        CallbackAPIVersion=SimpleNamespace(VERSION2=2),
        MQTTv311=4,
        MQTT_ERR_SUCCESS=0,
        Client=lambda **kwargs: client,
    )
    sender = CommittedReceiptMqttSender(
        host="isolated-mqtt",
        port=1883,
        client_id="nexolab-central-receipts-only",
        username="central-receipts-only",
        password_file=str(password),
        tls_config=MQTTTLSConfig(enabled=False),
        connect_timeout_seconds=0.01,
        mqtt_module=module,
    )
    return sender, client


def receipt(sequence: int = 1) -> tuple[str, bytes]:
    topic = f"nexolab/v1/{ORG}/{NODE}/receipts"
    obj = {
        "contract_version": 1,
        "receipt_id": str(uuid4()),
        "event_id": str(uuid4()),
        "organization_id": ORG,
        "node_id": NODE,
        "stream": "telemetry",
        "node_sequence": sequence,
        "receipt_level": "postgres_committed",
        "accepted_at": "2026-10-30T14:00:00Z",
    }
    return topic, json.dumps(obj).encode("utf-8")


def test_dedicated_identity_and_explicit_qos1_puback(tmp_path):
    sender, client = make_sender(tmp_path)
    assert client.username == "central-receipts-only"
    assert client.password == "synthetic-test-only"
    sender.start()
    topic, payload = receipt()
    assert sender(topic, payload) is True
    assert client.sent == [(topic, payload, 1, False)]
    sender.stop()
    assert sender(topic, payload) is False


def test_no_puback_is_retryable(tmp_path):
    sender, client = make_sender(tmp_path)
    sender.start()
    client.ack = False
    topic, payload = receipt()
    assert sender(topic, payload) is False
    assert len(client.sent) == 1
    sender.stop()


def test_unconnected_broker_never_claims_ack(tmp_path):
    sender, client = make_sender(tmp_path)
    client.start_connect = False
    sender.start()
    topic, payload = receipt()
    assert sender(topic, payload) is False
    assert client.sent == []
    sender.stop()


@pytest.mark.parametrize("change", ["topic", "stream", "node", "receipt_level", "sequence"])
def test_untrusted_topic_payload_is_rejected_before_publish(tmp_path, change):
    sender, client = make_sender(tmp_path)
    sender.start()
    topic, raw = receipt()
    obj = json.loads(raw)
    if change == "topic":
        topic = "nexolab/v1/other/other/receipts"
    elif change == "stream":
        obj["stream"] = "health"
    elif change == "node":
        obj["node_id"] = "different"
    elif change == "receipt_level":
        obj["receipt_level"] = "durably_spooled"
    else:
        obj["node_sequence"] = True
    assert sender(topic, json.dumps(obj).encode("utf-8")) is False
    assert client.sent == []
    sender.stop()


def test_transport_requires_separate_nonempty_credentials(tmp_path):
    with pytest.raises(ValueError, match="dedicated_receipt_broker_identity_required"):
        CommittedReceiptMqttSender(
            host="isolated-mqtt",
            port=1883,
            client_id="",
            username="",
            password_file="missing",
            tls_config=MQTTTLSConfig(enabled=False),
        )
