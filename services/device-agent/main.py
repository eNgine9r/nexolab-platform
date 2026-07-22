from __future__ import annotations

import json
import logging
import os
import random
import signal
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

LOG = logging.getLogger("nexolab.device_agent")


@dataclass(frozen=True)
class Settings:
    node_id: str
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    sample_interval_seconds: float
    database_path: Path
    health_host: str
    health_port: int
    device_mode: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            node_id=os.getenv("NEXOLAB_NODE_ID", "edge-01"),
            mqtt_host=os.getenv("MQTT_HOST", "mqtt"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_topic=os.getenv("MQTT_TOPIC", "nexolab/telemetry"),
            sample_interval_seconds=float(os.getenv("SAMPLE_INTERVAL_SECONDS", "5")),
            database_path=Path(os.getenv("DATABASE_PATH", "/var/lib/nexolab/edge.db")),
            health_host=os.getenv("HEALTH_HOST", "0.0.0.0"),
            health_port=int(os.getenv("HEALTH_PORT", "8081")),
            device_mode=os.getenv("DEVICE_MODE", "simulator"),
        )


@dataclass(frozen=True)
class TelemetryRecord:
    event_id: str
    node_id: str
    captured_at: str
    metric: str
    value: float
    unit: str
    quality: str
    source: str


class OfflineQueue:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def enqueue(self, topic: str, payload: str, event_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO outbound_queue(event_id, topic, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, topic, payload, datetime.now(timezone.utc).isoformat()),
            )

    def oldest(self, limit: int = 100) -> list[tuple[int, str, str]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, topic, payload FROM outbound_queue ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

    def delete(self, record_id: int) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM outbound_queue WHERE id = ?", (record_id,))

    def size(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) FROM outbound_queue").fetchone()
        return int(row[0] if row else 0)


class AgentState:
    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.mqtt_connected = False
        self.last_sample_at: str | None = None
        self.last_publish_at: str | None = None
        self.last_error: str | None = None
        self.samples_total = 0
        self._lock = threading.Lock()

    def update(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self, queue_size: int, settings: Settings) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok" if self.last_error is None else "degraded",
                "node_id": settings.node_id,
                "device_mode": settings.device_mode,
                "mqtt_connected": self.mqtt_connected,
                "queue_size": queue_size,
                "samples_total": self.samples_total,
                "last_sample_at": self.last_sample_at,
                "last_publish_at": self.last_publish_at,
                "last_error": self.last_error,
                "started_at": self.started_at.isoformat(),
            }


class DeviceAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queue = OfflineQueue(settings.database_path)
        self.state = AgentState()
        self.stop_event = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.node_id)
        self.client.enable_logger(LOG)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        connected = reason_code == 0
        self.state.update(mqtt_connected=connected, last_error=None if connected else str(reason_code))
        LOG.info("MQTT connection result: %s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self.state.update(mqtt_connected=False)
        LOG.warning("MQTT disconnected: %s", reason_code)

    def connect(self) -> None:
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        self.client.loop_start()

    def sample(self) -> TelemetryRecord:
        if self.settings.device_mode != "simulator":
            raise RuntimeError(
                "Hardware mode is reserved for the first Modbus adapter. "
                "Set DEVICE_MODE=simulator until a driver is configured."
            )

        now = datetime.now(timezone.utc).isoformat()
        return TelemetryRecord(
            event_id=str(uuid.uuid4()),
            node_id=self.settings.node_id,
            captured_at=now,
            metric="temperature.air",
            value=round(random.uniform(2.0, 8.0), 2),
            unit="degC",
            quality="good",
            source="simulator",
        )

    def publish_or_queue(self, record: TelemetryRecord) -> None:
        payload = json.dumps(asdict(record), separators=(",", ":"), ensure_ascii=False)
        if self.state.mqtt_connected:
            try:
                result = self.client.publish(self.settings.mqtt_topic, payload, qos=1)
                result.wait_for_publish(timeout=5)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.state.update(
                        last_publish_at=datetime.now(timezone.utc).isoformat(),
                        last_error=None,
                    )
                    return
            except (RuntimeError, ValueError, OSError) as exc:
                LOG.warning("MQTT publish failed; queueing event: %s", exc)

        self.queue.enqueue(self.settings.mqtt_topic, payload, record.event_id)
        self.state.update(last_error="MQTT unavailable; telemetry queued locally")

    def flush_queue(self) -> None:
        if not self.state.mqtt_connected:
            return

        for record_id, topic, payload in self.queue.oldest():
            result = self.client.publish(topic, payload, qos=1)
            result.wait_for_publish(timeout=5)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                break
            self.queue.delete(record_id)
            self.state.update(last_publish_at=datetime.now(timezone.utc).isoformat(), last_error=None)

    def run(self) -> None:
        self.connect()
        LOG.info("Starting device agent for %s", self.settings.node_id)

        while not self.stop_event.is_set():
            try:
                record = self.sample()
                self.publish_or_queue(record)
                self.flush_queue()
                self.state.update(
                    last_sample_at=record.captured_at,
                    samples_total=self.state.samples_total + 1,
                )
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Device-agent cycle failed")
                self.state.update(last_error=str(exc))
            self.stop_event.wait(self.settings.sample_interval_seconds)

        self.client.loop_stop()
        self.client.disconnect()


class HealthHandler(BaseHTTPRequestHandler):
    agent: DeviceAgent

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/ready"}:
            self.send_response(404)
            self.end_headers()
            return

        payload = self.agent.state.snapshot(self.agent.queue.size(), self.agent.settings)
        status = 200 if payload["status"] in {"ok", "degraded"} else 503
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.debug("health: " + format, *args)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = DeviceAgent(settings)
    HealthHandler.agent = agent
    server = ThreadingHTTPServer((settings.health_host, settings.health_port), HealthHandler)

    def stop(signum: int, frame: Any) -> None:
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker = threading.Thread(target=agent.run, name="device-agent", daemon=True)
    worker.start()
    LOG.info("Health endpoint listening on %s:%s", settings.health_host, settings.health_port)
    server.serve_forever(poll_interval=0.5)
    worker.join(timeout=10)


if __name__ == "__main__":
    main()
