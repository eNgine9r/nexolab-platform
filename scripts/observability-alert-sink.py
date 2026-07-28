#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_BODY_BYTES = 1_048_576


class AlertStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._received_total = 0
        self._firing_total = 0
        self._resolved_total = 0
        self._last_received_timestamp = 0.0
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        alerts = payload.get("alerts")
        if not isinstance(alerts, list):
            raise ValueError("Alertmanager payload must contain an alerts array")

        firing = 0
        resolved = 0
        for index, alert in enumerate(alerts):
            if not isinstance(alert, dict):
                raise ValueError(f"alerts[{index}] must be an object")
            status = alert.get("status")
            if status == "firing":
                firing += 1
            elif status == "resolved":
                resolved += 1
            else:
                raise ValueError(f"alerts[{index}].status is unsupported")

        record = {
            "received_at": time.time(),
            "receiver": payload.get("receiver"),
            "status": payload.get("status"),
            "groupLabels": payload.get("groupLabels", {}),
            "commonLabels": payload.get("commonLabels", {}),
            "alerts": alerts,
        }
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"

        with self._lock:
            with self._path.open("ab") as destination:
                destination.write(encoded)
                destination.flush()
                os.fsync(destination.fileno())
            self._received_total += 1
            self._firing_total += firing
            self._resolved_total += resolved
            self._last_received_timestamp = record["received_at"]

    def metrics(self) -> str:
        with self._lock:
            values = {
                "received_total": self._received_total,
                "firing_total": self._firing_total,
                "resolved_total": self._resolved_total,
                "last_received_timestamp_seconds": self._last_received_timestamp,
            }
        lines = []
        for name, value in values.items():
            metric = f"nexolab_alert_sink_{name}"
            metric_type = "counter" if name.endswith("_total") else "gauge"
            lines.extend(
                [
                    f"# HELP {metric} NEXOLAB local alert audit sink {name}.",
                    f"# TYPE {metric} {metric_type}",
                    f"{metric} {value}",
                ]
            )
        return "\n".join(lines) + "\n"

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        result: list[dict[str, Any]] = []
        for line in lines[-200:]:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                result.append(payload)
        return result


class Handler(BaseHTTPRequestHandler):
    server: "AlertServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write(self, status: HTTPStatus, content: bytes, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write(
                HTTPStatus.OK,
                b'{"status":"ok"}\n',
                "application/json; charset=utf-8",
            )
            return
        if self.path == "/metrics":
            self._write(
                HTTPStatus.OK,
                self.server.store.metrics().encode("utf-8"),
                "text/plain; version=0.0.4; charset=utf-8",
            )
            return
        if self.path == "/events":
            content = json.dumps(
                self.server.store.events(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            self._write(HTTPStatus.OK, content, "application/json; charset=utf-8")
            return
        self._write(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/alerts":
            self._write(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")
            return
        content_length = self.headers.get("Content-Length")
        try:
            size = int(content_length or "")
        except ValueError:
            size = -1
        if size < 0 or size > MAX_BODY_BYTES:
            self._write(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                b"invalid content length\n",
                "text/plain; charset=utf-8",
            )
            return
        try:
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            self.server.store.append(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._write(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                (str(error) + "\n").encode("utf-8"),
                "text/plain; charset=utf-8",
            )
            return
        self._write(HTTPStatus.ACCEPTED, b'{"accepted":true}\n', "application/json; charset=utf-8")


class AlertServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], store: AlertStore) -> None:
        super().__init__(address, Handler)
        self.store = store


def main() -> int:
    host = os.getenv("NEXOLAB_ALERT_SINK_HOST", "0.0.0.0")
    port = int(os.getenv("NEXOLAB_ALERT_SINK_PORT", "8080"))
    path = Path(os.getenv("NEXOLAB_ALERT_SINK_PATH", "/var/lib/nexolab-alerts/events.jsonl"))
    server = AlertServer((host, port), AlertStore(path))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
