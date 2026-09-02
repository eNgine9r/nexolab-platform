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
