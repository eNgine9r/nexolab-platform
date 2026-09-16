from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class DeviceAgentPreflightError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DeviceAgentPreflightCommand:
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    profile_id: str
    profile_version: str
    deadline_seconds: float

    def payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "bus_id": self.bus_id,
            "stable_transport_identifier": self.stable_transport_identifier,
            "unit_id": self.unit_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "deadline_seconds": self.deadline_seconds,
        }


class DeviceAgentPreflightClient:
    def __init__(self, base_url: str, *, transport_timeout_seconds: float = 12.0) -> None:
        self._base_url = validated_device_agent_base_url(base_url)
        self._transport_timeout_seconds = max(1.0, min(float(transport_timeout_seconds), 15.0))

    def list_connections(self) -> dict[str, Any]:
        request = Request(
            f"{self._base_url}/api/v1/commissioning/connections",
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=min(self._transport_timeout_seconds, 5.0)) as response:  # noqa: S310 - URL is validated configuration
                body = response.read(256 * 1024 + 1)
                if len(body) > 256 * 1024:
                    raise DeviceAgentPreflightError("device_agent_response_too_large", "Device Agent connection inventory is too large")
                payload = json.loads(body.decode("utf-8"))
        except HTTPError as error:
            raise DeviceAgentPreflightError(
                "device_agent_rejected",
                f"Device Agent rejected connection inventory with HTTP {error.code}",
            ) from error
        except (URLError, socket.timeout, TimeoutError) as error:
            raise DeviceAgentPreflightError("device_agent_unavailable", "Device Agent connection inventory is unavailable or timed out") from error
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent returned malformed connection inventory") from error
        return validate_connection_inventory(payload)

    def run(self, command: DeviceAgentPreflightCommand) -> dict[str, Any]:
        encoded = json.dumps(command.payload(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self._base_url}/api/v1/commissioning/preflight",
            data=encoded,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        timeout = min(self._transport_timeout_seconds, command.deadline_seconds + 2.0)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated configuration
                body = response.read(256 * 1024 + 1)
                if len(body) > 256 * 1024:
                    raise DeviceAgentPreflightError("device_agent_response_too_large", "Device Agent preflight response is too large")
                payload = json.loads(body.decode("utf-8"))
        except HTTPError as error:
            raise DeviceAgentPreflightError(
                "device_agent_rejected",
                f"Device Agent rejected the bounded preflight request with HTTP {error.code}",
            ) from error
        except (URLError, socket.timeout, TimeoutError) as error:
            raise DeviceAgentPreflightError("device_agent_unavailable", "Device Agent preflight endpoint is unavailable or timed out") from error
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent returned malformed preflight evidence") from error
        return validate_preflight_evidence(payload, command)


def validate_connection_inventory(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("node_id"), str):
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent connection inventory header is invalid")
    connections = payload.get("connections")
    if not isinstance(connections, list):
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent connection inventory is missing connections")
    sanitized: list[dict[str, Any]] = []
    seen_bus_ids: set[str] = set()
    seen_paths: set[str] = set()
    for item in connections:
        if not isinstance(item, dict):
            raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent connection entry is invalid")
        bus_id = item.get("bus_id")
        stable = item.get("stable_transport_identifier")
        ownership = item.get("ownership")
        present = item.get("present")
        available = item.get("available_for_preflight")
        serial = item.get("serial")
        if (
            not isinstance(bus_id, str) or not bus_id or bus_id in seen_bus_ids
            or not isinstance(stable, str) or not stable.startswith("/dev/serial/by-id/") or stable in seen_paths
            or ownership not in {"production_bus", "available_commissioning"}
            or not isinstance(present, bool) or not isinstance(available, bool)
        ):
            raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent connection identity is invalid")
        if serial is not None:
            if (
                not isinstance(serial, dict)
                or not isinstance(serial.get("baudrate"), int) or serial["baudrate"] <= 0
                or serial.get("parity") not in {"N", "E", "O"}
                or serial.get("stopbits") not in {1, 2}
                or not isinstance(serial.get("timeout_seconds"), (int, float)) or isinstance(serial.get("timeout_seconds"), bool) or serial["timeout_seconds"] <= 0
                or not isinstance(serial.get("retries"), int) or isinstance(serial.get("retries"), bool) or serial["retries"] < 0
            ):
                raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent connection serial contract is invalid")
            serial = {
                "baudrate": serial["baudrate"],
                "parity": serial["parity"],
                "stopbits": serial["stopbits"],
                "timeout_seconds": float(serial["timeout_seconds"]),
                "retries": serial["retries"],
            }
        if ownership == "available_commissioning" and serial is not None:
            raise DeviceAgentPreflightError("device_agent_response_invalid", "Unowned commissioning adapters must not claim production serial configuration")
        seen_bus_ids.add(bus_id)
        seen_paths.add(stable)
        sanitized.append({
            "bus_id": bus_id,
            "stable_transport_identifier": stable,
            "ownership": ownership,
            "present": present,
            "available_for_preflight": available,
            "serial": serial,
        })
    return {"schema_version": 1, "node_id": payload["node_id"], "connections": sanitized}


def validate_preflight_evidence(payload: object, command: DeviceAgentPreflightCommand) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight evidence must be an object")
    required_exact = {
        "schema_version": 1,
        "node_id": command.node_id,
        "bus_id": command.bus_id,
        "stable_transport_identifier": command.stable_transport_identifier,
        "unit_id": command.unit_id,
        "profile_id": command.profile_id,
        "profile_version": command.profile_version,
        "read_method": "modbus_rtu_fc03",
        "modbus_writes": "none",
        "hardware_writes": "none",
    }
    for key, expected in required_exact.items():
        if payload.get(key) != expected:
            raise DeviceAgentPreflightError(
                "device_agent_response_invalid",
                f"Device Agent preflight evidence has invalid {key}",
            )
    if payload.get("result") not in {"passed", "failed"}:
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight result is invalid")
    if payload.get("evidence_level") not in {"hardware_verified", "partially_verified", "unsupported", "unverified"}:
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent evidence level is invalid")
    if payload.get("function_codes") != [3]:
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight must prove FC03-only execution")
    if not isinstance(payload.get("code"), str) or not isinstance(payload.get("checks"), list):
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight evidence is incomplete")
    if not isinstance(payload.get("observations"), list) or not isinstance(payload.get("warnings"), list):
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight evidence collections are invalid")
    if not isinstance(payload.get("duration_ms"), int) or payload["duration_ms"] < 0:
        raise DeviceAgentPreflightError("device_agent_response_invalid", "Device Agent preflight duration is invalid")
    # Persist only the bounded contract fields; unknown agent fields never become evidence.
    return {
        "schema_version": 1,
        "result": payload["result"],
        "code": payload["code"],
        "evidence_level": payload["evidence_level"],
        "node_id": payload["node_id"],
        "bus_id": payload["bus_id"],
        "stable_transport_identifier": payload["stable_transport_identifier"],
        "unit_id": payload["unit_id"],
        "profile_id": payload["profile_id"],
        "profile_version": payload["profile_version"],
        "read_method": "modbus_rtu_fc03",
        "function_codes": [3],
        "checks": payload["checks"],
        "observations": payload["observations"],
        "warnings": payload["warnings"],
        "duration_ms": payload["duration_ms"],
        "modbus_writes": "none",
        "hardware_writes": "none",
    }


def validated_device_agent_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("COMMISSIONING_DEVICE_AGENT_BASE_URL must be an http(s) service origin")
    if parsed.query or parsed.fragment or (parsed.path not in {"", "/"}):
        raise ValueError("COMMISSIONING_DEVICE_AGENT_BASE_URL must not contain a path, query, or fragment")
    host = parsed.hostname
    assert host is not None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != "localhost" and re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", host) is None:
            raise ValueError(
                "COMMISSIONING_DEVICE_AGENT_BASE_URL must use loopback, a private IP, or a local single-label service name"
            )
    else:
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise ValueError("COMMISSIONING_DEVICE_AGENT_BASE_URL must not target a public IP")
    return normalized
