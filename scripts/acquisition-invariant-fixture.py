#!/usr/bin/env python3
"""Deterministic local fixture for browser-to-acquisition isolation acceptance."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
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
CADENCE_REVISION = 7
CADENCE_UPDATED_AT = datetime.now(timezone.utc).isoformat()
FAMILY_DEFAULTS: dict[tuple[str, str], float] = {
    ("rs485-main", "xjp60d"): 60.0,
    ("rs485-main", "le01mp"): 30.0,
}
DEVICE_OVERRIDES: dict[str, float] = {"xjp60d-106": 60.0}


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


def _capacity_payload(*, safe: bool = True) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "model": "heterogeneous_device_utilization_v1",
        "safe": safe,
        "maximum_allowed_utilization_percent": 75.0,
        "safety_margin_percent": 25.0,
        "cooldown_capacity_credit": False,
        "buses": [
            {
                "bus_id": "rs485-main",
                "safe": safe,
                "active_device_count": 2,
                "active_target_count": 4,
                "estimated_utilization_percent": 38.0 if safe else 92.4,
                "maximum_allowed_utilization_percent": 75.0,
                "recommended_minimum_interval_seconds": None if safe else 30,
                "recommendation_scope": None if safe else "changed_devices_uniform_interval",
                "request_budget_seconds": 0.302,
                "request_budget_source": "serial_timeout_fallback",
                "measured_p95_minimum_samples": 20,
                "observed_sample_count": 0,
                "serial_timeout_seconds": 0.3,
                "retry_allowance": 1,
                "retry_reserve_fraction": 0.1,
                "inter_frame_seconds": 0.004,
                "cooldown_capacity_credit": False,
                "devices": [],
            }
        ],
    }


def _effective_interval(device_id: str, family: str) -> tuple[float, str]:
    override = DEVICE_OVERRIDES.get(device_id)
    if override is not None:
        return override, "device_override"
    return FAMILY_DEFAULTS[("rs485-main", family)], "family_default"


def cadence_payload() -> dict[str, Any]:
    with LOCK:
        revision = CADENCE_REVISION
        updated_at = CADENCE_UPDATED_AT
        defaults = [
            {
                "bus_id": bus_id,
                "device_family": family,
                "interval_seconds": interval,
            }
            for (bus_id, family), interval in sorted(FAMILY_DEFAULTS.items())
        ]
        overrides = [
            {"device_id": device_id, "interval_seconds": interval}
            for device_id, interval in sorted(DEVICE_OVERRIDES.items())
        ]
        xjp_interval, xjp_source = _effective_interval("xjp60d-106", "xjp60d")
        le_interval, le_source = _effective_interval("le01mp-200", "le01mp")
    return {
        "schema_version": 1,
        "registry_revision": revision,
        "updated_at": updated_at,
        "policy": {
            "presets_seconds": [10, 30, 60],
            "custom_min_seconds": 10,
            "maximum_seconds": 3600,
            "family_defaults": defaults,
            "device_overrides": overrides,
        },
        "effective_devices": [
            {
                "device_id": "xjp60d-106",
                "bus_id": "rs485-main",
                "device_family": "xjp60d",
                "lifecycle": "active",
                "effective_interval_seconds": xjp_interval,
                "cadence_source": xjp_source,
            },
            {
                "device_id": "le01mp-200",
                "bus_id": "rs485-main",
                "device_family": "le01mp",
                "lifecycle": "active",
                "effective_interval_seconds": le_interval,
                "cadence_source": le_source,
            },
        ],
        "capacity": _capacity_payload(),
    }


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > 65536:
        raise ValueError("invalid request body")
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    return payload


def _interval(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("interval_seconds must be numeric")
    resolved = float(value)
    if resolved < 10 or resolved > 3600:
        raise ValueError("interval_seconds must be between 10 and 3600 seconds")
    return resolved


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path in {"/health", "/ready"}:
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/metrics":
            self._send_json(HTTPStatus.OK, metrics_payload())
            return
        if path == "/api/v1/acquisition-cadence":
            self._send_json(HTTPStatus.OK, cadence_payload())
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
        path = self.path.split("?", maxsplit=1)[0]
        if path == "/api/v1/acquisition-cadence":
            self._put_cadence()
            return
        global CONFIGURATION_MUTATIONS
        with LOCK:
            CONFIGURATION_MUTATIONS += 1
        self._send_json(HTTPStatus.OK, {"detail": "configuration mutation recorded"})

    def _put_cadence(self) -> None:
        global CADENCE_REVISION, CADENCE_UPDATED_AT, CONFIGURATION_MUTATIONS
        try:
            payload = _read_json(self)
            expected_revision = payload.get("expected_revision")
            reason = payload.get("reason")
            if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
                raise ValueError("expected_revision must be a positive integer")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("reason must be a non-empty string")

            with LOCK:
                if expected_revision != CADENCE_REVISION:
                    self._send_json(
                        HTTPStatus.CONFLICT,
                        {"detail": f"Registry revision conflict: expected {expected_revision}, current {CADENCE_REVISION}"},
                    )
                    return

                family_updates: list[tuple[tuple[str, str], float]] = []
                for item in payload.get("family_defaults", []):
                    if not isinstance(item, dict):
                        raise ValueError("family default mutation must be an object")
                    key = (str(item.get("bus_id", "")), str(item.get("device_family", "")))
                    if key not in FAMILY_DEFAULTS:
                        raise ValueError("unknown family default")
                    family_updates.append((key, _interval(item.get("interval_seconds"))))

                device_updates: list[tuple[str, float | None]] = []
                for item in payload.get("device_overrides", []):
                    if not isinstance(item, dict):
                        raise ValueError("device override mutation must be an object")
                    device_id = str(item.get("device_id", ""))
                    if device_id not in {"xjp60d-106", "le01mp-200"}:
                        raise ValueError("unknown device override")
                    raw_interval = item.get("interval_seconds")
                    device_updates.append(
                        (device_id, None if raw_interval is None else _interval(raw_interval))
                    )

                requested_intervals = [interval for _, interval in family_updates] + [
                    interval for _, interval in device_updates if interval is not None
                ]
                if 10.0 in requested_intervals:
                    self._send_json(
                        HTTPStatus.UNPROCESSABLE_ENTITY,
                        {
                            "code": "acquisition_capacity_exceeded",
                            "detail": "Requested acquisition cadence exceeds RS-485 capacity: rs485-main",
                            "capacity": _capacity_payload(safe=False),
                        },
                    )
                    return
                if not family_updates and not device_updates:
                    raise ValueError("Cadence mutation requires at least one change")

                for key, interval in family_updates:
                    FAMILY_DEFAULTS[key] = interval
                for device_id, interval in device_updates:
                    if interval is None:
                        DEVICE_OVERRIDES.pop(device_id, None)
                    else:
                        DEVICE_OVERRIDES[device_id] = interval
                CADENCE_REVISION += 1
                CADENCE_UPDATED_AT = datetime.now(timezone.utc).isoformat()
                CONFIGURATION_MUTATIONS += 1
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": str(error)})
            return

        self._send_json(HTTPStatus.OK, cadence_payload())

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
