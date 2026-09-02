from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.commissioning.preflight_client import validated_device_agent_base_url


class DeviceAgentActivationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DeviceAgentActivationCommand:
    activation_id: str
    action: str
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    profile_id: str
    profile_version: str
    def payload(self) -> dict[str, object]:
        return {
            "activation_id": self.activation_id,
            "action": self.action,
            "node_id": self.node_id,
            "bus_id": self.bus_id,
            "stable_transport_identifier": self.stable_transport_identifier,
            "unit_id": self.unit_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
        }


class DeviceAgentActivationClient:
    def __init__(self, base_url: str, *, transport_timeout_seconds: float = 10.0) -> None:
        self._base_url = validated_device_agent_base_url(base_url)
        self._transport_timeout_seconds = max(
            1.0, min(float(transport_timeout_seconds), 20.0)
        )

    def execute(self, command: DeviceAgentActivationCommand) -> dict[str, Any]:
        payload = self._request_json(
            "/api/v1/commissioning/activation",
            method="POST",
            body=command.payload(),
        )
        return validate_activation_evidence(payload, command)
    def health(self, *, node_id: str, target_ids: list[str]) -> dict[str, Any]:
        payload = self._request_json("/health", method="GET")
        return validate_activation_health(
            payload,
            node_id=node_id,
            target_ids=target_ids,
        )

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        body: dict[str, object] | None = None,
    ) -> object:
        encoded = (
            json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if body is not None
            else None
        )
        request = Request(
            f"{self._base_url}{path}",
            data=encoded,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._transport_timeout_seconds) as response:  # noqa: S310
                raw = response.read(256 * 1024 + 1)
                if len(raw) > 256 * 1024:
                    raise DeviceAgentActivationError(
                        "device_agent_response_too_large",
                        "Device Agent activation response is too large",
                    )
                return json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            raise DeviceAgentActivationError(
                "device_agent_rejected",
                f"Device Agent rejected the activation request with HTTP {error.code}",
            ) from error
        except (URLError, socket.timeout, TimeoutError) as error:
            raise DeviceAgentActivationError(
                "device_agent_unavailable",
                "Device Agent activation endpoint is unavailable or timed out",
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise DeviceAgentActivationError(
                "device_agent_response_invalid",
                "Device Agent returned malformed activation evidence",
            ) from error


def validate_activation_evidence(
    payload: object,
    command: DeviceAgentActivationCommand,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Activation evidence must be an object"
        )
    exact = {
        "schema_version": 1,
        "activation_id": command.activation_id,
        "node_id": command.node_id,
        "bus_id": command.bus_id,
        "stable_transport_identifier": command.stable_transport_identifier,
        "unit_id": command.unit_id,
        "profile_id": command.profile_id,
        "profile_version": command.profile_version,
        "polling_mode": "read_only_fc03",
        "modbus_writes": "none",
        "hardware_writes": "none",
    }
    for key, expected in exact.items():
        if payload.get(key) != expected:
            raise DeviceAgentActivationError(
                "device_agent_response_invalid",
                f"Device Agent activation evidence has invalid {key}",
            )
    if payload.get("state") not in {
        "active", "rolled_back", "recovery_required"
    }:
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Device Agent activation state is invalid"
        )
    if not isinstance(payload.get("registry_revision"), int):
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Activation registry revision is invalid"
        )
    if not isinstance(payload.get("device_id"), str):
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Activation device identity is missing"
        )
    target_ids = payload.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids or any(
        not isinstance(item, str) or not item for item in target_ids
    ):
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Activation target identities are invalid"
        )
    if not isinstance(payload.get("telemetry_source"), str) or not isinstance(
        payload.get("telemetry_equipment_id"), str
    ):
        raise DeviceAgentActivationError(
            "device_agent_response_invalid", "Activation telemetry identity is invalid"
        )
    return {
        "schema_version": 1,
        "activation_id": payload["activation_id"],
        "state": payload["state"],
        "node_id": payload["node_id"],
        "bus_id": payload["bus_id"],
        "stable_transport_identifier": payload["stable_transport_identifier"],
        "unit_id": payload["unit_id"],
        "profile_id": payload["profile_id"],
        "profile_version": payload["profile_version"],
        "device_id": payload["device_id"],
        "target_ids": list(target_ids),
        "registry_revision": payload["registry_revision"],
        "telemetry_source": payload["telemetry_source"],
        "telemetry_equipment_id": payload["telemetry_equipment_id"],
        "polling_mode": "read_only_fc03",
        "modbus_writes": "none",
        "hardware_writes": "none",
        "reason": payload.get("reason"),
    }


def validate_activation_health(
    payload: object,
    *,
    node_id: str,
    target_ids: list[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeviceAgentActivationError(
            "device_agent_health_invalid", "Device Agent health must be an object"
        )
    if payload.get("node_id") != node_id or payload.get("status") != "ok":
        raise DeviceAgentActivationError(
            "device_agent_not_healthy", "Device Agent is not healthy for activation"
        )
    if payload.get("mqtt_connected") is not True:
        raise DeviceAgentActivationError(
            "device_agent_mqtt_disconnected", "Device Agent MQTT is not connected"
        )
    acquisition = payload.get("acquisition")
    scheduler = acquisition.get("scheduler") if isinstance(acquisition, dict) else None
    if not isinstance(scheduler, dict) or scheduler.get("workers_healthy") is not True:
        raise DeviceAgentActivationError(
            "device_agent_workers_unhealthy", "Device Agent acquisition workers are not healthy"
        )
    raw_targets = scheduler.get("targets")
    if not isinstance(raw_targets, list):
        raise DeviceAgentActivationError(
            "device_agent_health_invalid", "Device Agent scheduler targets are invalid"
        )
    observed = {
        str(item.get("target_id"))
        for item in raw_targets
        if isinstance(item, dict) and isinstance(item.get("target_id"), str)
    }
    missing = sorted(set(target_ids) - observed)
    if missing:
        raise DeviceAgentActivationError(
            "device_agent_targets_missing",
            "Device Agent scheduler is missing activated targets: " + ", ".join(missing),
        )
    return {
        "status": "ok",
        "node_id": node_id,
        "mqtt_connected": True,
        "workers_healthy": True,
        "expected_bus_workers": scheduler.get("expected_bus_workers"),
        "active_bus_workers": scheduler.get("active_bus_workers"),
        "target_ids": sorted(set(target_ids)),
    }
