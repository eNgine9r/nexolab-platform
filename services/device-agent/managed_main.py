from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from main import (
    DeviceAgent,
    HealthHandler,
    Settings,
    mode_uses_xjp60d,
    parse_unit_ids,
    parse_xjp60d_points,
)
from modbus_rtu import ModbusError
from xjp60d import XJP60DReader

LOG = logging.getLogger("nexolab.device_agent")
DEFAULT_DISCOVERY_UNITS = (*range(101, 115), *range(126, 139))
_MAX_REQUEST_BYTES = 32 * 1024


def canonical_point(unit_id: int, channel: int) -> str:
    return f"{unit_id}-{channel:02d}"


def parse_control_points(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise ValueError("points must be an array")
    tokens: list[str] = []
    for item in value:
        if isinstance(item, str):
            normalized = item.strip().replace("-", ":", 1)
            tokens.append(normalized)
            continue
        if isinstance(item, dict):
            unit_id = item.get("unit_id")
            channel = item.get("channel")
            if not isinstance(unit_id, int) or not isinstance(channel, int):
                raise ValueError("point objects require integer unit_id and channel")
            tokens.append(f"{unit_id}:{channel}")
            continue
        raise ValueError("points must contain channel IDs or point objects")
    return parse_xjp60d_points(",".join(tokens))


class XJP60DPointStore:
    """Persist the operator-approved hot polling set in the edge SQLite volume."""

    _ACTIVE_KEY = "active_points"
    _DISCOVERY_KEY = "last_discovery"

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS xjp60d_runtime_configuration (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def load_or_initialize(
        self,
        default_points: tuple[tuple[int, int], ...],
    ) -> tuple[tuple[int, int], ...]:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT value FROM xjp60d_runtime_configuration WHERE key = ?",
                (self._ACTIVE_KEY,),
            ).fetchone()
            if row is None:
                self._write_locked(
                    self._ACTIVE_KEY,
                    json.dumps(
                        [canonical_point(unit_id, channel) for unit_id, channel in default_points],
                        separators=(",", ":"),
                    ),
                )
                return default_points
        return parse_control_points(json.loads(str(row[0])))

    def replace_points(self, points: tuple[tuple[int, int], ...]) -> None:
        payload = json.dumps(
            [canonical_point(unit_id, channel) for unit_id, channel in points],
            separators=(",", ":"),
        )
        with self._lock, self._connection:
            self._write_locked(self._ACTIVE_KEY, payload)

    def load_last_discovery(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM xjp60d_runtime_configuration WHERE key = ?",
                (self._DISCOVERY_KEY,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row[0]))
        return value if isinstance(value, dict) else None

    def save_last_discovery(self, result: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._write_locked(
                self._DISCOVERY_KEY,
                json.dumps(result, separators=(",", ":"), ensure_ascii=False),
            )

    def _write_locked(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO xjp60d_runtime_configuration(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE
            SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, datetime.now(timezone.utc).isoformat()),
        )


class XJP60DDiscoveryScanner:
    def __init__(self, reader: XJP60DReader, unit_ids: tuple[int, ...]) -> None:
        self._reader = reader
        self._unit_ids = unit_ids

    def scan(self) -> dict[str, Any]:
        started = time.monotonic()
        scanned_at = datetime.now(timezone.utc).isoformat()
        points: list[dict[str, Any]] = []
        controller_errors: list[dict[str, Any]] = []

        for unit_id in self._unit_ids:
            controller_reachable = False
            for channel in range(1, 7):
                try:
                    reading = self._reader.read_channel(unit_id, channel)
                except (ModbusError, OSError, RuntimeError) as error:
                    if not controller_reachable:
                        controller_errors.append(
                            {
                                "unit_id": unit_id,
                                "message": str(error),
                            }
                        )
                        # A failed first register is treated as a controller-level
                        # failure to keep discovery bounded on absent addresses.
                        break
                    points.append(
                        {
                            "channel_id": canonical_point(unit_id, channel),
                            "unit_id": unit_id,
                            "channel": channel,
                            "quality": "communication_error",
                            "value": None,
                            "unit": "degC",
                            "alarm": None,
                            "raw_status": None,
                        }
                    )
                    continue

                controller_reachable = True
                points.append(
                    {
                        "channel_id": canonical_point(unit_id, channel),
                        "unit_id": unit_id,
                        "channel": channel,
                        "quality": reading.quality,
                        "value": reading.value,
                        "unit": reading.unit,
                        "alarm": reading.alarm,
                        "raw_status": reading.raw_status,
                    }
                )

        available = [item for item in points if item["quality"] == "valid"]
        return {
            "scanned_at": scanned_at,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "controller_count": len(self._unit_ids),
            "reachable_controller_count": len({item["unit_id"] for item in points}),
            "available_points": available,
            "unavailable_points": [item for item in points if item["quality"] != "valid"],
            "controller_errors": controller_errors,
        }


class ManagedDeviceAgent(DeviceAgent):
    def __init__(self, settings: Settings) -> None:
        self._point_store = XJP60DPointStore(settings.database_path)
        active_points = self._point_store.load_or_initialize(settings.xjp60d_points)
        managed_settings = replace(settings, xjp60d_points=active_points)
        super().__init__(managed_settings)

        discovery_value = os.getenv("XJP60D_DISCOVERY_UNITS", "").strip()
        self.discovery_units = (
            parse_unit_ids(discovery_value, label="XJP60D discovery")
            if discovery_value
            else DEFAULT_DISCOVERY_UNITS
        )
        self._configuration_lock = threading.Lock()
        self._bus_operation_lock = threading.Lock()
        self._discovery_lock = threading.Lock()

    def sample_batch(self):  # type: ignore[no-untyped-def]
        with self._bus_operation_lock:
            return super().sample_batch()

    def configuration(self) -> dict[str, Any]:
        with self._configuration_lock:
            active_points = self.settings.xjp60d_points
        return {
            "node_id": self.settings.node_id,
            "active_points": [
                canonical_point(unit_id, channel)
                for unit_id, channel in active_points
            ],
            "discovery_units": list(self.discovery_units),
            "last_discovery": self._point_store.load_last_discovery(),
        }

    def replace_active_points(
        self,
        points: tuple[tuple[int, int], ...],
    ) -> dict[str, Any]:
        allowed = {
            (unit_id, channel)
            for unit_id in self.discovery_units
            for channel in range(1, 7)
        }
        unsupported = [point for point in points if point not in allowed]
        if unsupported:
            rendered = ", ".join(canonical_point(*point) for point in unsupported)
            raise ValueError(f"points are outside the configured discovery catalog: {rendered}")
        if (
            mode_uses_xjp60d(self.settings.device_mode)
            and not points
            and not self.settings.le01mp_unit_ids
        ):
            raise ValueError("at least one active XJP60D point is required")

        self._point_store.replace_points(points)
        with self._configuration_lock:
            self.settings = replace(self.settings, xjp60d_points=points)
        self.state.update(last_error=None)
        if self.operational is not None and self.state.mqtt_connected:
            self.operational.publish_health_if_due(force=True)
        return self.configuration()

    def discover_xjp60d(self) -> dict[str, Any]:
        if self.xjp60d_reader is None:
            raise RuntimeError("XJP60D reader is not initialized")
        if not self._discovery_lock.acquire(blocking=False):
            raise DiscoveryAlreadyRunningError
        try:
            with self._bus_operation_lock:
                result = XJP60DDiscoveryScanner(
                    self.xjp60d_reader,
                    self.discovery_units,
                ).scan()
            self._point_store.save_last_discovery(result)
            return {**self.configuration(), "last_discovery": result}
        finally:
            self._discovery_lock.release()


class DiscoveryAlreadyRunningError(RuntimeError):
    pass


class ManagedHealthHandler(HealthHandler):
    agent: ManagedDeviceAgent

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path == "/api/v1/xjp60d/configuration":
            self._send_json(HTTPStatus.OK, self.agent.configuration())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path != "/api/v1/xjp60d/discovery":
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        try:
            result = self.agent.discover_xjp60d()
        except DiscoveryAlreadyRunningError:
            self._send_json(
                HTTPStatus.CONFLICT,
                {"detail": "XJP60D discovery is already running"},
            )
            return
        except (RuntimeError, ValueError) as error:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": str(error)})
            return
        self._send_json(HTTPStatus.OK, result)

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path != "/api/v1/xjp60d/configuration":
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        try:
            payload = self._read_json_body()
            points = parse_control_points(payload.get("points"))
            result = self.agent.replace_active_points(points)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": str(error)})
            return
        self._send_json(HTTPStatus.OK, result)

    def _read_json_body(self) -> dict[str, Any]:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if not 1 <= length <= _MAX_REQUEST_BYTES:
            raise ValueError("request body size is invalid")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = ManagedDeviceAgent(settings)
    ManagedHealthHandler.agent = agent
    server = ThreadingHTTPServer(
        (settings.health_host, settings.health_port),
        ManagedHealthHandler,
    )

    def stop(signum: int, frame: Any) -> None:
        del frame
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker = threading.Thread(
        target=agent.run,
        name="device-agent",
        daemon=True,
    )
    worker.start()
    LOG.info(
        "Managed health endpoint listening on %s:%s",
        settings.health_host,
        settings.health_port,
    )
    server.serve_forever(poll_interval=0.5)
    worker.join(timeout=10)


if __name__ == "__main__":
    main()
