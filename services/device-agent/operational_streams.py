from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Protocol


class PublishResult(Protocol):
    rc: int

    def wait_for_publish(self, timeout: float | None = None) -> None: ...


class MqttPublisher(Protocol):
    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> PublishResult: ...

    def will_set(
        self,
        topic: str,
        payload: str | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None: ...


class NodeOperationalPublisher:
    """Publish versioned health and retained availability streams."""

    def __init__(
        self,
        client: MqttPublisher,
        *,
        organization_id: str,
        node_id: str,
        software_version: str,
        device_mode: str,
        health_interval_seconds: float,
        next_sequence: Callable[[str], int],
        state_snapshot: Callable[[], dict[str, Any]],
    ) -> None:
        self._client = client
        self._organization_id = organization_id.strip()
        self._node_id = node_id.strip().lower()
        self._software_version = software_version.strip()
        self._device_mode = device_mode.strip()
        self._health_interval_seconds = health_interval_seconds
        self._next_sequence = next_sequence
        self._state_snapshot = state_snapshot
        self._lock = threading.Lock()
        self._prepared_online: dict[str, Any] | None = None
        self._prepared_will: dict[str, Any] | None = None
        self._last_health_monotonic: float | None = None

        if not self._organization_id:
            raise ValueError("organization_id is required for node operational streams")
        if not self._node_id:
            raise ValueError("node_id is required for node operational streams")
        if not self._software_version:
            raise ValueError("software_version is required for node operational streams")
        if health_interval_seconds <= 0:
            raise ValueError("health_interval_seconds must be positive")

    @property
    def health_topic(self) -> str:
        return self._topic("health")

    @property
    def status_topic(self) -> str:
        return self._topic("status")

    def prepare_connection(self) -> None:
        """Prepare online and LWT events before the MQTT CONNECT packet."""
        with self._lock:
            self._prepare_connection_locked()

    def on_connected(self) -> bool:
        """Publish retained online status and prepare the next reconnect pair."""
        with self._lock:
            if self._prepared_online is None or self._prepared_will is None:
                self._prepare_connection_locked()
            assert self._prepared_online is not None
            published = self._publish(
                self.status_topic,
                self._prepared_online,
                retain=True,
            )
            self._prepare_connection_locked()
            return published

    def publish_health_if_due(self, *, force: bool = False) -> bool | None:
        now_monotonic = time.monotonic()
        with self._lock:
            if (
                not force
                and self._last_health_monotonic is not None
                and now_monotonic - self._last_health_monotonic
                < self._health_interval_seconds
            ):
                return None
            snapshot = self._state_snapshot()
            last_error = snapshot.get("last_error")
            payload = {
                "schema_version": 1,
                "event_id": str(uuid.uuid4()),
                "node_id": self._node_id,
                "captured_at": _now(),
                "node_sequence": self._next_sequence("health"),
                "health": "degraded" if last_error else "healthy",
                "uptime_seconds": max(0, int(snapshot.get("uptime_seconds", 0))),
                "queue_depth": max(0, int(snapshot.get("queue_depth", 0))),
                "samples_total": max(0, int(snapshot.get("samples_total", 0))),
                "software_version": self._software_version,
                "device_mode": self._device_mode,
                "last_sample_at": snapshot.get("last_sample_at"),
                "last_publish_at": snapshot.get("last_publish_at"),
                "last_error": str(last_error) if last_error else None,
            }
            published = self._publish(self.health_topic, payload, retain=False)
            if published:
                self._last_health_monotonic = now_monotonic
            return published

    def publish_graceful_offline(self) -> bool:
        with self._lock:
            payload = self._status_payload(
                sequence=self._next_sequence("status"),
                status="offline",
                reason="device agent stopped",
                graceful=True,
            )
            return self._publish(self.status_topic, payload, retain=True)

    def _prepare_connection_locked(self) -> None:
        online_sequence = self._next_sequence("status")
        will_sequence = self._next_sequence("status")
        self._prepared_online = self._status_payload(
            sequence=online_sequence,
            status="online",
            reason="device agent connected",
            graceful=True,
        )
        self._prepared_will = self._status_payload(
            sequence=will_sequence,
            status="offline",
            reason="mqtt last will",
            graceful=False,
        )
        self._client.will_set(
            self.status_topic,
            json.dumps(
                self._prepared_will,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            qos=1,
            retain=True,
        )

    def _status_payload(
        self,
        *,
        sequence: int,
        status: str,
        reason: str,
        graceful: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "node_id": self._node_id,
            "captured_at": _now(),
            "node_sequence": sequence,
            "status": status,
            "reason": reason,
            "software_version": self._software_version,
            "graceful": graceful,
        }

    def _publish(self, topic: str, payload: dict[str, Any], *, retain: bool) -> bool:
        result = self._client.publish(
            topic,
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            qos=1,
            retain=retain,
        )
        result.wait_for_publish(timeout=5)
        return result.rc == 0

    def _topic(self, stream: str) -> str:
        return (
            f"nexolab/v1/{self._organization_id}/{self._node_id}/{stream}"
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
