#!/usr/bin/env python3
"""Deterministic local fixture for browser-to-acquisition isolation acceptance."""

from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "127.0.0.1"
PORT = int(os.getenv("ACQUISITION_FIXTURE_PORT", "18081"))
REQUESTS_PER_SECOND = float(os.getenv("ACQUISITION_FIXTURE_REQUESTS_PER_SECOND", "20"))
STARTED_AT = time.monotonic()
LOCK = threading.Lock()
DISCOVERY_REQUESTS = 0
CONFIGURATION_MUTATIONS = 0


def normal_requests_total() -> int:
    return max(0, int((time.monotonic() - STARTED_AT) * REQUESTS_PER_SECOND))


def metrics_payload() -> dict[str, Any]:
    with LOCK:
        discovery = DISCOVERY_REQUESTS
        mutations = CONFIGURATION_MUTATIONS
    requests = normal_requests_total()
    return {
        "schema_version": 1,
        "node_id": "edge-invariant-fixture",
        "acquisition": {
            "schema_version": 1,
            "polling_policy": "deterministic_fixed_rate_fixture",
            "configured_logical_targets": 2,
            "normal": {
                "physical_requests_total": requests,
                "retry_attempts_total": 0,
                "bus_busy_seconds_total": round(requests * 0.002, 6),
                "outcomes": {"success": requests},
            },
            "service_operations": {
                "discovery": {"physical_requests_total": discovery},
                "configuration_mutation": {"requests_total": mutations},
            },
            "cycle": {
                "completed_total": requests // 4,
                "overrun_total": 0,
                "skipped_total": 0,
            },
        },
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path in {"/health", "/ready"}:
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/metrics":
            self._send_json(HTTPStatus.OK, metrics_payload())
            return
        if path == "/api/v1/xjp60d/configuration":
            self._send_json(
                HTTPStatus.OK,
                {
                    "node_id": "edge-invariant-fixture",
                    "active_points": ["106-03", "106-04"],
                    "discovery_units": [106],
                    "last_discovery": None,
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        global DISCOVERY_REQUESTS
        path = self.path.split("?", maxsplit=1)[0]
        if path != "/api/v1/xjp60d/discovery":
            self._send_json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        with LOCK:
            DISCOVERY_REQUESTS += 1
        self._send_json(HTTPStatus.OK, {"detail": "explicit discovery recorded"})

    def do_PUT(self) -> None:  # noqa: N802
        global CONFIGURATION_MUTATIONS
        with LOCK:
            CONFIGURATION_MUTATIONS += 1
        self._send_json(HTTPStatus.OK, {"detail": "configuration mutation recorded"})

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


def main() -> None:
    if REQUESTS_PER_SECOND <= 0:
        raise SystemExit("ACQUISITION_FIXTURE_REQUESTS_PER_SECOND must be positive")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"acquisition invariant fixture listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
