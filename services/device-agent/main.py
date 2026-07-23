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

from le01mp import LE01MPReader, REGISTERS as LE01MP_REGISTERS
from modbus_rtu import ModbusError, ModbusRTUClient
from xjp60d import XJP60DReader

LOG = logging.getLogger("nexolab.device_agent")


def parse_xjp60d_points(value: str) -> tuple[tuple[int, int], ...]:
    points: list[tuple[int, int]] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            unit_text, channel_text = token.split(":", maxsplit=1)
            unit_id = int(unit_text)
            channel = int(channel_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid XJP60D point {token!r}; expected UNIT_ID:CHANNEL"
            ) from exc
        if not 1 <= unit_id <= 247:
            raise ValueError(f"XJP60D unit ID must be 1..247, got {unit_id}")
        if not 1 <= channel <= 6:
            raise ValueError(f"XJP60D channel must be 1..6, got {channel}")
        point = (unit_id, channel)
        if point not in points:
            points.append(point)
    return tuple(points)


def parse_unit_ids(value: str, *, label: str) -> tuple[int, ...]:
    unit_ids: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            unit_id = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid {label} unit ID: {token!r}") from exc
        if not 1 <= unit_id <= 247:
            raise ValueError(f"{label} unit ID must be 1..247, got {unit_id}")
        if unit_id not in unit_ids:
            unit_ids.append(unit_id)
    return tuple(unit_ids)


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
    serial_device: str
    serial_baudrate: int
    serial_parity: str
    serial_stopbits: int
    serial_timeout_seconds: float
    serial_retries: int
    xjp60d_points: tuple[tuple[int, int], ...]
    xjp60d_scale: float
    le01mp_unit_ids: tuple[int, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            node_id=os.getenv("NEXOLAB_NODE_ID", "edge-01"),
            mqtt_host=os.getenv("MQTT_HOST", "mqtt"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_topic=os.getenv("MQTT_TOPIC", "nexolab/telemetry"),
            sample_interval_seconds=float(os.getenv("SAMPLE_INTERVAL_SECONDS", "5")),
            database_path=Path(os.getenv("DATABASE_PATH", "/var/lib/nexolab/edge.db")),
            health_host=os.getenv("HEALTH_HOST", "0.0.0.0"),
            health_port=int(os.getenv("HEALTH_PORT", "8081")),
            device_mode=os.getenv("DEVICE_MODE", "simulator").strip().casefold(),
            serial_device=os.getenv("SERIAL_DEVICE", "/dev/rs485"),
            serial_baudrate=int(os.getenv("SERIAL_BAUDRATE", "9600")),
            serial_parity=os.getenv("SERIAL_PARITY", "N").strip().upper(),
            serial_stopbits=int(os.getenv("SERIAL_STOPBITS", "1")),
            serial_timeout_seconds=float(os.getenv("SERIAL_TIMEOUT_SECONDS", "0.30")),
            serial_retries=int(os.getenv("SERIAL_RETRIES", "1")),
            xjp60d_points=parse_xjp60d_points(os.getenv("XJP60D_POINTS", "")),
            xjp60d_scale=float(os.getenv("XJP60D_SCALE", "0.1")),
            le01mp_unit_ids=parse_unit_ids(
                os.getenv("LE01MP_UNIT_IDS", ""),
                label="LE-01MP",
            ),
        )
        allowed_modes = {"simulator", "xjp60d", "le01mp", "modbus"}
        if settings.device_mode not in allowed_modes:
            raise ValueError(
                "DEVICE_MODE must be simulator, xjp60d, le01mp, or modbus"
            )
        if settings.device_mode == "xjp60d" and not settings.xjp60d_points:
            raise ValueError("XJP60D_POINTS is required when DEVICE_MODE=xjp60d")
        if settings.device_mode == "le01mp" and not settings.le01mp_unit_ids:
            raise ValueError("LE01MP_UNIT_IDS is required when DEVICE_MODE=le01mp")
        if (
            settings.device_mode == "modbus"
            and not settings.xjp60d_points
            and not settings.le01mp_unit_ids
        ):
            raise ValueError(
                "At least one XJP60D point or LE-01MP unit is required "
                "when DEVICE_MODE=modbus"
            )
        return settings


@dataclass(frozen=True)
class TelemetryRecord:
    event_id: str
    node_id: str
    captured_at: str
    metric: str
    value: float | None
    unit: str
    quality: str
    source: str
    equipment_id: str | None = None
    channel_id: str | None = None
    alarm: str | None = None
    raw_value: int | None = None
    raw_status: int | None = None


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
                "configured_points": [
                    f"{unit_id}-{channel:02d}"
                    for unit_id, channel in settings.xjp60d_points
                ],
                "configured_devices": [
                    f"LE01MP-{unit_id}" for unit_id in settings.le01mp_unit_ids
                ],
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
        self.modbus_client: ModbusRTUClient | None = None
        self.xjp60d_reader: XJP60DReader | None = None
        self.le01mp_reader: LE01MPReader | None = None

        if settings.device_mode != "simulator":
            self.modbus_client = ModbusRTUClient(
                settings.serial_device,
                baudrate=settings.serial_baudrate,
                parity=settings.serial_parity,
                stopbits=settings.serial_stopbits,
                timeout=settings.serial_timeout_seconds,
                retries=settings.serial_retries,
            )

        if settings.device_mode in {"xjp60d", "modbus"} and settings.xjp60d_points:
            if self.modbus_client is None:
                raise RuntimeError("Modbus client was not initialized")
            self.xjp60d_reader = XJP60DReader(
                self.modbus_client,
                scale=settings.xjp60d_scale,
                unit="degC",
            )

        if settings.device_mode in {"le01mp", "modbus"} and settings.le01mp_unit_ids:
            if self.modbus_client is None:
                raise RuntimeError("Modbus client was not initialized")
            self.le01mp_reader = LE01MPReader(self.modbus_client)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        connected = reason_code == 0
        self.state.update(mqtt_connected=connected)
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

    def _sample_xjp60d(
        self,
        captured_at: str,
        records: list[TelemetryRecord],
        errors: list[str],
    ) -> None:
        if not self.settings.xjp60d_points:
            return
        if self.xjp60d_reader is None:
            raise RuntimeError("XJP60D reader was not initialized")

        for unit_id, channel in self.settings.xjp60d_points:
            equipment_id = f"K{unit_id}"
            channel_id = f"{unit_id}-{channel:02d}"
            try:
                reading = self.xjp60d_reader.read_channel(unit_id, channel)
            except (ModbusError, OSError, RuntimeError) as exc:
                LOG.warning("XJP60D read failed for %s: %s", channel_id, exc)
                errors.append(f"{channel_id}: {exc}")
                records.append(
                    TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric="temperature.probe",
                        value=None,
                        unit="degC",
                        quality="communication_error",
                        source="dixell-xjp60d",
                        equipment_id=equipment_id,
                        channel_id=channel_id,
                    )
                )
                continue

            records.append(
                TelemetryRecord(
                    event_id=str(uuid.uuid4()),
                    node_id=self.settings.node_id,
                    captured_at=captured_at,
                    metric="temperature.probe",
                    value=reading.value,
                    unit=reading.unit,
                    quality=reading.quality,
                    source="dixell-xjp60d",
                    equipment_id=equipment_id,
                    channel_id=channel_id,
                    alarm=reading.alarm,
                    raw_value=reading.raw_value,
                    raw_status=reading.raw_status,
                )
            )

    def _sample_le01mp(
        self,
        captured_at: str,
        records: list[TelemetryRecord],
        errors: list[str],
    ) -> None:
        if not self.settings.le01mp_unit_ids:
            return
        if self.le01mp_reader is None:
            raise RuntimeError("LE-01MP reader was not initialized")

        for unit_id in self.settings.le01mp_unit_ids:
            equipment_id = f"LE01MP-{unit_id}"
            for register in LE01MP_REGISTERS:
                channel_id = f"{unit_id}-{register.key.replace('_', '-')}"
                try:
                    reading = self.le01mp_reader.read_metric(unit_id, register.key)
                except (ModbusError, OSError, RuntimeError) as exc:
                    LOG.warning("LE-01MP read failed for %s: %s", channel_id, exc)
                    errors.append(f"{channel_id}: {exc}")
                    records.append(
                        TelemetryRecord(
                            event_id=str(uuid.uuid4()),
                            node_id=self.settings.node_id,
                            captured_at=captured_at,
                            metric=register.metric,
                            value=None,
                            unit=register.unit,
                            quality="communication_error",
                            source="f-and-f-le-01mp",
                            equipment_id=equipment_id,
                            channel_id=channel_id,
                        )
                    )
                    continue

                records.append(
                    TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric=reading.metric,
                        value=reading.value,
                        unit=reading.unit,
                        quality=reading.quality,
                        source="f-and-f-le-01mp",
                        equipment_id=equipment_id,
                        channel_id=channel_id,
                        raw_value=reading.raw_value,
                    )
                )

    def sample_batch(self) -> tuple[list[TelemetryRecord], str | None]:
        if self.settings.device_mode == "simulator":
            now = datetime.now(timezone.utc).isoformat()
            return (
                [
                    TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=now,
                        metric="temperature.air",
                        value=round(random.uniform(2.0, 8.0), 2),
                        unit="degC",
                        quality="valid",
                        source="simulator",
                    )
                ],
                None,
            )

        captured_at = datetime.now(timezone.utc).isoformat()
        records: list[TelemetryRecord] = []
        errors: list[str] = []
        self._sample_xjp60d(captured_at, records, errors)
        self._sample_le01mp(captured_at, records, errors)

        if not records:
            raise RuntimeError("No Modbus telemetry sources are configured")

        error = "; ".join(errors) if errors else None
        return records, error

    def publish_or_queue(self, record: TelemetryRecord) -> bool:
        payload = json.dumps(asdict(record), separators=(",", ":"), ensure_ascii=False)
        if self.state.mqtt_connected:
            try:
                result = self.client.publish(self.settings.mqtt_topic, payload, qos=1)
                result.wait_for_publish(timeout=5)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.state.update(
                        last_publish_at=datetime.now(timezone.utc).isoformat(),
                    )
                    return True
            except (RuntimeError, ValueError, OSError) as exc:
                LOG.warning("MQTT publish failed; queueing event: %s", exc)

        self.queue.enqueue(self.settings.mqtt_topic, payload, record.event_id)
        return False

    def flush_queue(self) -> bool:
        if not self.state.mqtt_connected:
            return False

        for record_id, topic, payload in self.queue.oldest():
            result = self.client.publish(topic, payload, qos=1)
            result.wait_for_publish(timeout=5)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                return False
            self.queue.delete(record_id)
            self.state.update(last_publish_at=datetime.now(timezone.utc).isoformat())
        return True

    def run(self) -> None:
        self.connect()
        LOG.info("Starting device agent for %s", self.settings.node_id)

        try:
            while not self.stop_event.is_set():
                try:
                    records, sample_error = self.sample_batch()
                    publish_results = [
                        self.publish_or_queue(record) for record in records
                    ]
                    publish_ok = all(publish_results)
                    flush_ok = self.flush_queue()
                    last_error = sample_error
                    if last_error is None and (not publish_ok or not flush_ok):
                        last_error = "MQTT unavailable; telemetry queued locally"
                    self.state.update(
                        last_sample_at=records[-1].captured_at if records else None,
                        samples_total=self.state.samples_total + len(records),
                        last_error=last_error,
                    )
                except Exception as exc:  # noqa: BLE001
                    LOG.exception("Device-agent cycle failed")
                    self.state.update(last_error=str(exc))
                self.stop_event.wait(self.settings.sample_interval_seconds)
        finally:
            if self.modbus_client is not None:
                self.modbus_client.close()
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
