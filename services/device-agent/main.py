from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
import random
import signal
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from le01mp import LE01MPReader, REGISTERS as LE01MP_REGISTERS
from modbus_rtu import ModbusError, ModbusRTUClient
from mqtt_tls import MQTTTLSConfig
from operational_streams import NodeOperationalPublisher
from xjp60d import XJP60DReader

LOG = logging.getLogger("nexolab.device_agent")


def mode_uses_xjp60d(device_mode: str) -> bool:
    return device_mode in {"xjp60d", "modbus"}


def mode_uses_le01mp(device_mode: str) -> bool:
    return device_mode in {"le01mp", "modbus"}


def parse_bool(value: str, *, label: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{label} must be true or false")


def read_mounted_secret(path: Path, *, label: str) -> str:
    if not path.is_file() or not os.access(path, os.R_OK):
        raise ValueError(f"{label} file is not readable")
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{label} file could not be read") from exc
    if not value:
        raise ValueError(f"{label} must not be empty")
    if any(
        character.isspace()
        or ord(character) < 33
        or ord(character) == 127
        for character in value
    ):
        raise ValueError(
            f"{label} must not contain whitespace or control characters"
        )
    return value


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
    organization_id: str | None
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    health_interval_seconds: float
    software_version: str
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
    mqtt_auth_required: bool = False
    mqtt_username: str | None = None
    mqtt_client_id: str = ""
    mqtt_password_file: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        node_id = os.getenv("NEXOLAB_NODE_ID", "edge-01").strip()
        organization_id = (
            os.getenv("NEXOLAB_ORGANIZATION_ID", "").strip() or None
        )
        mqtt_auth_required = parse_bool(
            os.getenv("MQTT_AUTH_REQUIRED", "false"),
            label="MQTT_AUTH_REQUIRED",
        )
        expected_username = (
            f"node:{organization_id}:{node_id}"
            if organization_id is not None
            else None
        )
        expected_client_id = (
            f"nexolab-{organization_id}-{node_id}"
            if organization_id is not None
            else node_id
        )
        mqtt_username = os.getenv("MQTT_USERNAME", "").strip() or (
            expected_username if mqtt_auth_required else None
        )
        mqtt_client_id = os.getenv("MQTT_CLIENT_ID", "").strip() or (
            expected_client_id if mqtt_auth_required else node_id
        )
        password_file_value = os.getenv("MQTT_PASSWORD_FILE", "").strip()
        mqtt_password_file = (
            Path(password_file_value) if password_file_value else None
        )

        settings = cls(
            node_id=node_id,
            organization_id=organization_id,
            mqtt_host=os.getenv("MQTT_HOST", "mqtt"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_topic=os.getenv("MQTT_TOPIC", "nexolab/telemetry"),
            health_interval_seconds=float(
                os.getenv("NODE_HEALTH_INTERVAL_SECONDS", "30")
            ),
            software_version=os.getenv(
                "NEXOLAB_DEVICE_AGENT_VERSION", "0.15.0"
            ),
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
            mqtt_auth_required=mqtt_auth_required,
            mqtt_username=mqtt_username,
            mqtt_client_id=mqtt_client_id,
            mqtt_password_file=mqtt_password_file,
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
        if settings.health_interval_seconds <= 0:
            raise ValueError("NODE_HEALTH_INTERVAL_SECONDS must be positive")
        if not settings.node_id or any(
            character.isspace() for character in settings.node_id
        ):
            raise ValueError(
                "NEXOLAB_NODE_ID must not be empty or contain whitespace"
            )
        if settings.mqtt_auth_required:
            if settings.organization_id is None:
                raise ValueError(
                    "NEXOLAB_ORGANIZATION_ID is required when "
                    "MQTT_AUTH_REQUIRED=true"
                )
            if settings.mqtt_username != settings.expected_mqtt_username:
                raise ValueError(
                    "MQTT_USERNAME does not match the provisioned node identity"
                )
            if settings.mqtt_client_id != settings.expected_mqtt_client_id:
                raise ValueError(
                    "MQTT_CLIENT_ID does not match the provisioned node identity"
                )
            if settings.mqtt_password_file is None:
                raise ValueError(
                    "MQTT_PASSWORD_FILE is required when "
                    "MQTT_AUTH_REQUIRED=true"
                )
            read_mounted_secret(
                settings.mqtt_password_file,
                label="MQTT password",
            )
        elif (
            settings.mqtt_username is not None
            or settings.mqtt_password_file is not None
        ):
            raise ValueError(
                "MQTT username/password require MQTT_AUTH_REQUIRED=true"
            )
        return settings

    @property
    def expected_mqtt_username(self) -> str | None:
        if self.organization_id is None:
            return None
        return f"node:{self.organization_id}:{self.node_id}"

    @property
    def expected_mqtt_client_id(self) -> str:
        if self.organization_id is None:
            return self.node_id
        return f"nexolab-{self.organization_id}-{self.node_id}"

    @property
    def resolved_telemetry_topic(self) -> str:
        if self.organization_id is None:
            return self.mqtt_topic
        return f"nexolab/v1/{self.organization_id}/{self.node_id}/telemetry"


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
    def __init__(
        self,
        database_path: Path,
        *,
        busy_timeout_ms: int = 2000,
        busy_retry_attempts: int = 3,
        busy_retry_delay_seconds: float = 0.05,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        if busy_retry_attempts <= 0:
            raise ValueError("busy_retry_attempts must be positive")
        if busy_retry_delay_seconds < 0:
            raise ValueError("busy_retry_delay_seconds must be non-negative")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
            timeout=busy_timeout_ms / 1000,
        )
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._lock = threading.Lock()
        self._busy_retry_attempts = busy_retry_attempts
        self._busy_retry_delay_seconds = busy_retry_delay_seconds
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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS node_stream_sequences (
                    stream TEXT PRIMARY KEY,
                    last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0)
                )
                """
            )

    @staticmethod
    def _is_busy_error(error: sqlite3.OperationalError) -> bool:
        message = str(error).casefold()
        return "locked" in message or "busy" in message

    def _retry_busy(self, label: str, operation: Callable[[], Any]) -> Any:
        for attempt in range(1, self._busy_retry_attempts + 1):
            try:
                return operation()
            except sqlite3.OperationalError as error:
                if self._connection.in_transaction:
                    self._connection.rollback()
                if (
                    not self._is_busy_error(error)
                    or attempt >= self._busy_retry_attempts
                ):
                    raise
                LOG.warning(
                    "SQLite queue %s deferred by lock contention; retry %s/%s",
                    label,
                    attempt,
                    self._busy_retry_attempts,
                )
                if self._busy_retry_delay_seconds:
                    time.sleep(self._busy_retry_delay_seconds * attempt)
        raise RuntimeError("SQLite busy retry loop exhausted unexpectedly")

    def enqueue(self, topic: str, payload: str, event_id: str) -> None:
        def operation() -> None:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO outbound_queue(event_id, topic, payload, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        topic,
                        payload,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

        with self._lock:
            self._retry_busy("enqueue", operation)

    def oldest(self, limit: int = 100) -> list[tuple[int, str, str]]:
        def operation() -> list[tuple[int, str, str]]:
            rows = self._connection.execute(
                "SELECT id, topic, payload FROM outbound_queue ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

        with self._lock:
            return self._retry_busy("oldest", operation)

    def delete(self, record_id: int) -> None:
        def operation() -> None:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM outbound_queue WHERE id = ?",
                    (record_id,),
                )

        with self._lock:
            self._retry_busy("delete", operation)

    def size(self) -> int:
        def operation() -> int:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM outbound_queue"
            ).fetchone()
            return int(row[0] if row else 0)

        with self._lock:
            return int(self._retry_busy("size", operation))

    def next_sequence(self, stream: str) -> int:
        normalized = stream.strip().lower()
        if not normalized:
            raise ValueError("stream is required")

        def operation() -> int:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO node_stream_sequences(stream, last_sequence)
                    VALUES (?, 0)
                    ON CONFLICT(stream) DO NOTHING
                    """,
                    (normalized,),
                )
                self._connection.execute(
                    """
                    UPDATE node_stream_sequences
                    SET last_sequence = last_sequence + 1
                    WHERE stream = ?
                    """,
                    (normalized,),
                )
                row = self._connection.execute(
                    "SELECT last_sequence FROM node_stream_sequences WHERE stream = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("node stream sequence allocation failed")
                return int(row[0])

        with self._lock:
            return int(self._retry_busy("next_sequence", operation))


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
        configured_points = (
            [
                f"{unit_id}-{channel:02d}"
                for unit_id, channel in settings.xjp60d_points
            ]
            if mode_uses_xjp60d(settings.device_mode)
            else []
        )
        configured_devices = (
            [f"LE01MP-{unit_id}" for unit_id in settings.le01mp_unit_ids]
            if mode_uses_le01mp(settings.device_mode)
            else []
        )
        with self._lock:
            return {
                "status": "ok" if self.last_error is None else "degraded",
                "node_id": settings.node_id,
                "device_mode": settings.device_mode,
                "configured_points": configured_points,
                "configured_devices": configured_devices,
                "mqtt_connected": self.mqtt_connected,
                "queue_size": queue_size,
                "queue_depth": queue_size,
                "uptime_seconds": max(
                    0,
                    int((datetime.now(timezone.utc) - self.started_at).total_seconds()),
                ),
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
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id or settings.node_id,
        )
        if settings.mqtt_auth_required:
            if (
                settings.mqtt_username is None
                or settings.mqtt_password_file is None
            ):
                raise RuntimeError("Secure MQTT settings were not validated")
            mqtt_password = read_mounted_secret(
                settings.mqtt_password_file,
                label="MQTT password",
            )
            self.client.username_pw_set(
                settings.mqtt_username,
                mqtt_password,
            )
            del mqtt_password
        self.mqtt_tls = MQTTTLSConfig.from_environment()
        self.mqtt_tls.apply(self.client)
        self.client.enable_logger(LOG)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.operational: NodeOperationalPublisher | None = None
        if settings.organization_id is not None:
            self.operational = NodeOperationalPublisher(
                self.client,
                organization_id=settings.organization_id,
                node_id=settings.node_id,
                software_version=settings.software_version,
                device_mode=settings.device_mode,
                health_interval_seconds=settings.health_interval_seconds,
                next_sequence=self.queue.next_sequence,
                state_snapshot=lambda: self.state.snapshot(
                    self.queue.size(), self.settings
                ),
            )
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

        if mode_uses_xjp60d(settings.device_mode) and settings.xjp60d_points:
            if self.modbus_client is None:
                raise RuntimeError("Modbus client was not initialized")
            self.xjp60d_reader = XJP60DReader(
                self.modbus_client,
                scale=settings.xjp60d_scale,
                unit="degC",
            )

        if mode_uses_le01mp(settings.device_mode) and settings.le01mp_unit_ids:
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
        if connected and self.operational is not None:
            if not self.operational.on_connected():
                self.state.update(last_error="online status publish failed")
            self.operational.publish_health_if_due(force=True)
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
        if self.operational is not None:
            self.operational.prepare_connection()
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.connect_async(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            keepalive=30,
        )
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
                        equipment_id=f"SIM-{self.settings.node_id}",
                        channel_id="ambient-temperature",
                    )
                ],
                None,
            )

        captured_at = datetime.now(timezone.utc).isoformat()
        records: list[TelemetryRecord] = []
        errors: list[str] = []
        if mode_uses_xjp60d(self.settings.device_mode):
            self._sample_xjp60d(captured_at, records, errors)
        if mode_uses_le01mp(self.settings.device_mode):
            self._sample_le01mp(captured_at, records, errors)

        if not records:
            raise RuntimeError("No Modbus telemetry sources are configured")

        error = "; ".join(errors) if errors else None
        return records, error

    def publish_or_queue(self, record: TelemetryRecord) -> bool:
        payload_data = asdict(record)
        if self.settings.organization_id is not None:
            payload_data["node_sequence"] = self.queue.next_sequence("telemetry")
        payload = json.dumps(
            payload_data, separators=(",", ":"), ensure_ascii=False
        )
        topic = self.settings.resolved_telemetry_topic

        # Persist before touching the network. A successful ``publish()`` return
        # only means Paho accepted the message locally; durability starts only
        # after the QoS 1 acknowledgement is observed and the queued row is
        # deleted. This also preserves FIFO ordering across reconnects.
        self.queue.enqueue(topic, payload, record.event_id)
        if not self.state.mqtt_connected:
            return False
        return self.flush_queue()

    def flush_queue(self) -> bool:
        if not self.state.mqtt_connected:
            return False

        for record_id, topic, payload in self.queue.oldest():
            try:
                result = self.client.publish(topic, payload, qos=1)
                result.wait_for_publish(timeout=5)
            except (RuntimeError, ValueError, OSError) as exc:
                LOG.warning("MQTT queue flush deferred: %s", exc)
                return False

            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                LOG.warning(
                    "MQTT queue flush deferred: publish rc=%s",
                    result.rc,
                )
                return False
            if not result.is_published():
                LOG.warning(
                    "MQTT queue flush deferred: QoS 1 acknowledgement timed out"
                )
                return False

            self.queue.delete(record_id)
            self.state.update(
                last_publish_at=datetime.now(timezone.utc).isoformat(),
            )
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
                    if (
                        self.operational is not None
                        and self.state.mqtt_connected
                        and self.operational.publish_health_if_due() is False
                    ):
                        self.state.update(last_error="node health publish failed")
                except Exception as exc:  # noqa: BLE001
                    LOG.exception("Device-agent cycle failed")
                    self.state.update(last_error=str(exc))
                self.stop_event.wait(self.settings.sample_interval_seconds)
        finally:
            if self.modbus_client is not None:
                self.modbus_client.close()
            if self.operational is not None and self.state.mqtt_connected:
                self.operational.publish_graceful_offline()
            self.client.disconnect()
            self.client.loop_stop()


class HealthHandler(BaseHTTPRequestHandler):
    agent: DeviceAgent

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/health", "/ready"}:
            self.send_response(404)
            self.end_headers()
            return

        payload = self.agent.state.snapshot(
            self.agent.queue.size(),
            self.agent.settings,
        )
        status = 200 if payload["status"] in {"ok", "degraded"} else 503
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.debug("health: " + format, *args)


def run_agent_with_health_server(
    agent: DeviceAgent,
    server: ThreadingHTTPServer,
    *,
    endpoint_label: str,
) -> None:
    """Tie HTTP availability to the top-level acquisition runtime lifetime."""

    server_errors: list[Exception] = []

    def serve() -> None:
        try:
            server.serve_forever(poll_interval=0.5)
        except Exception as error:  # noqa: BLE001
            server_errors.append(error)
            agent.state.update(last_error=f"health server failed: {error}")
            agent.stop_event.set()

    server_thread = threading.Thread(
        target=serve,
        name="device-agent-health",
        daemon=True,
    )
    server_thread.start()
    LOG.info(
        "%s listening on %s:%s",
        endpoint_label,
        agent.settings.health_host,
        agent.settings.health_port,
    )

    runtime_error: Exception | None = None
    try:
        agent.run()
        if not agent.stop_event.is_set():
            runtime_error = RuntimeError("device-agent runtime exited unexpectedly")
    except Exception as error:  # noqa: BLE001
        runtime_error = error
        agent.state.update(last_error=f"device-agent runtime failed: {error}")
        LOG.exception("Device-agent runtime failed closed")
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=10)

    if server_thread.is_alive():
        raise RuntimeError("device-agent health server failed to stop")
    if runtime_error is not None:
        raise RuntimeError("device-agent runtime failed") from runtime_error
    if server_errors:
        raise RuntimeError("device-agent health server failed") from server_errors[0]


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = DeviceAgent(settings)
    HealthHandler.agent = agent
    server = ThreadingHTTPServer(
        (settings.health_host, settings.health_port),
        HealthHandler,
    )

    def stop(signum: int, frame: Any) -> None:
        del frame
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    run_agent_with_health_server(
        agent,
        server,
        endpoint_label="Health endpoint",
    )

if __name__ == "__main__":
    main()
