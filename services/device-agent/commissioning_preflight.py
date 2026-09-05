from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PreflightProfile:
    profile_id: str
    profile_version: str
    device_family: str
    evidence_level: str
    warnings: tuple[str, ...] = ()


PROFILES: dict[str, PreflightProfile] = {
    "dixell-xjp60d": PreflightProfile(
        profile_id="dixell-xjp60d",
        profile_version="dixell-xjp60d-fc03-v1",
        device_family="xjp60d",
        evidence_level="partially_verified",
        warnings=(
            "Live FC03 response verifies this exact controller path only; physical portability remains device-specific.",
        ),
    ),
    "f-and-f-le01mp": PreflightProfile(
        profile_id="f-and-f-le01mp",
        profile_version="f-and-f-le01mp-fc03-v2",
        device_family="le01mp",
        evidence_level="partially_verified",
        warnings=(
            "Live FC03 response verifies the bounded meter probe only; cumulative-energy rollover acceptance remains separate.",
        ),
    ),
    "embraco-sync": PreflightProfile(
        profile_id="embraco-sync",
        profile_version="embraco-sync-fc03-v1.00.04",
        device_family="embraco",
        evidence_level="hardware_verified",
        warnings=(
            "Engineering temperature/control scaling is not inferred by preflight and remains unverified where current production semantics are unknown.",
        ),
    ),
}

_ALLOWED_REQUEST_FIELDS = {
    "node_id",
    "bus_id",
    "stable_transport_identifier",
    "unit_id",
    "profile_id",
    "profile_version",
    "deadline_seconds",
}
_STABLE_PREFIX = "/dev/serial/by-id/"


@dataclass(frozen=True, slots=True)
class CommissioningPreflightRequest:
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    profile_id: str
    profile_version: str
    deadline_seconds: float


@dataclass(frozen=True, slots=True)
class PreflightBus:
    bus_id: str
    serial_device: str
    path_present: bool


@dataclass(frozen=True, slots=True)
class PreflightObservation:
    key: str
    quality: str
    semantic: str | None = None


class PreflightRuntime(Protocol):
    node_id: str

    def preflight_bus(self, bus_id: str) -> PreflightBus: ...

    def preflight_unit_owner(self, unit_id: int) -> str | None: ...

    def preflight_registry_identity(self, bus_id: str, unit_id: int) -> tuple[str, str] | None: ...

    def preflight_read_profile(
        self,
        profile: PreflightProfile,
        *,
        bus_id: str,
        unit_id: int,
        deadline_monotonic: float,
    ) -> tuple[PreflightObservation, ...]: ...


class PreflightExecutionError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def parse_preflight_request(payload: object) -> CommissioningPreflightRequest:
    if not isinstance(payload, dict):
        raise ValueError("preflight request body must be an object")
    unknown = sorted(set(payload) - _ALLOWED_REQUEST_FIELDS)
    if unknown:
        raise ValueError("unsupported preflight request fields: " + ", ".join(unknown))

    node_id = _required_text(payload.get("node_id"), "node_id", 64)
    bus_id = _required_text(payload.get("bus_id"), "bus_id", 64)
    stable = _required_text(payload.get("stable_transport_identifier"), "stable_transport_identifier", 255)
    if not is_stable_serial_identifier(stable):
        raise ValueError("stable_transport_identifier must use /dev/serial/by-id/<device-id>")
    unit_id = payload.get("unit_id")
    if not isinstance(unit_id, int) or isinstance(unit_id, bool) or not 1 <= unit_id <= 247:
        raise ValueError("unit_id must be an integer in 1..247")
    profile_id = _required_text(payload.get("profile_id"), "profile_id", 128)
    profile_version = _required_text(payload.get("profile_version"), "profile_version", 128)
    deadline = payload.get("deadline_seconds", 5.0)
    if not isinstance(deadline, (int, float)) or isinstance(deadline, bool):
        raise ValueError("deadline_seconds must be numeric")
    deadline_seconds = float(deadline)
    if not 1.0 <= deadline_seconds <= 10.0:
        raise ValueError("deadline_seconds must be between 1 and 10 seconds")
    return CommissioningPreflightRequest(
        node_id=node_id,
        bus_id=bus_id,
        stable_transport_identifier=stable,
        unit_id=unit_id,
        profile_id=profile_id,
        profile_version=profile_version,
        deadline_seconds=deadline_seconds,
    )


def execute_preflight(
    request: CommissioningPreflightRequest,
    runtime: PreflightRuntime,
    *,
    monotonic=time.monotonic,
) -> dict[str, Any]:
    started_at = monotonic()
    checks: list[dict[str, str]] = []

    def passed(key: str, detail: str) -> None:
        checks.append({"key": key, "state": "passed", "detail": detail})

    def failed(code: str, key: str, detail: str, *, evidence_level: str = "unverified") -> dict[str, Any]:
        checks.append({"key": key, "state": "failed", "detail": detail})
        return _result(
            request,
            result="failed",
            code=code,
            evidence_level=evidence_level,
            checks=checks,
            observations=(),
            warnings=(),
            duration_ms=_duration_ms(started_at, monotonic()),
        )

    if request.node_id != runtime.node_id:
        return failed("node_identity_mismatch", "node_identity", "Requested node does not match this Device Agent")
    passed("node_identity", "Device Agent node identity matches the commissioning draft")

    profile = PROFILES.get(request.profile_id)
    if profile is None:
        return failed("unsupported_profile", "profile", "Commissioning profile is not supported", evidence_level="unsupported")
    if request.profile_version != profile.profile_version:
        return failed("profile_mismatch", "profile", "Commissioning profile version does not match the repository-owned read contract")
    passed("profile", f"{profile.profile_id}@{profile.profile_version} is a fixed FC03-only profile")

    try:
        bus = runtime.preflight_bus(request.bus_id)
    except (KeyError, ValueError, PreflightExecutionError) as error:
        detail = error.detail if isinstance(error, PreflightExecutionError) else str(error)
        return failed("bus_unavailable", "bus", detail or "Requested RS-485 bus is unavailable")
    passed("bus", f"RS-485 bus {bus.bus_id} is configured")

    requested_serial = canonical_serial_identifier(request.stable_transport_identifier)
    configured_serial = canonical_serial_identifier(bus.serial_device)
    if requested_serial != configured_serial:
        return failed("adapter_identity_mismatch", "adapter_identity", "Configured stable adapter identity does not match the commissioning draft")
    if not bus.path_present:
        return failed("adapter_unavailable", "adapter_identity", "Configured stable serial adapter is not present")
    passed("adapter_identity", "Exact stable /dev/serial/by-id identity is present")

    owner = runtime.preflight_unit_owner(request.unit_id)
    if owner is not None and owner != request.bus_id:
        return failed("unit_id_conflict", "unit_identity", f"Unit ID {request.unit_id} is assigned to another physical bus")
    registry_identity = runtime.preflight_registry_identity(request.bus_id, request.unit_id)
    if registry_identity is not None and registry_identity != (profile.device_family, profile.profile_version):
        return failed("unit_id_conflict", "unit_identity", "Existing acquisition registry identity conflicts with the commissioning profile")
    passed("unit_identity", f"Unit ID {request.unit_id} has no conflicting bus/profile ownership")

    deadline_monotonic = started_at + request.deadline_seconds
    try:
        observations = runtime.preflight_read_profile(
            profile,
            bus_id=request.bus_id,
            unit_id=request.unit_id,
            deadline_monotonic=deadline_monotonic,
        )
    except PreflightExecutionError as error:
        return failed(error.code, "profile_read", error.detail)
    if monotonic() > deadline_monotonic:
        return failed("deadline_exceeded", "deadline", "Preflight exceeded its bounded execution deadline")
    passed("profile_read", "Fixed repository-owned FC03 verification reads completed")
    passed("write_safety", "Modbus writes = none; hardware writes = none")
    return _result(
        request,
        result="passed",
        code="preflight_passed",
        evidence_level=profile.evidence_level,
        checks=checks,
        observations=observations,
        warnings=profile.warnings,
        duration_ms=_duration_ms(started_at, monotonic()),
    )


def canonical_serial_identifier(value: str) -> str:
    normalized = value.strip()
    return normalized[5:] if normalized.startswith("/host/dev/serial/by-id/") else normalized


def is_stable_serial_identifier(value: str) -> bool:
    identifier = canonical_serial_identifier(value)
    device_id = identifier.removeprefix(_STABLE_PREFIX)
    return (
        identifier.startswith(_STABLE_PREFIX)
        and bool(device_id)
        and device_id not in {".", ".."}
        and "/" not in device_id
        and not any(character.isspace() for character in device_id)
    )


def _result(
    request: CommissioningPreflightRequest,
    *,
    result: str,
    code: str,
    evidence_level: str,
    checks: list[dict[str, str]],
    observations: tuple[PreflightObservation, ...],
    warnings: tuple[str, ...],
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "result": result,
        "code": code,
        "evidence_level": evidence_level,
        "node_id": request.node_id,
        "bus_id": request.bus_id,
        "stable_transport_identifier": request.stable_transport_identifier,
        "unit_id": request.unit_id,
        "profile_id": request.profile_id,
        "profile_version": request.profile_version,
        "read_method": "modbus_rtu_fc03",
        "function_codes": [3],
        "checks": checks,
        "observations": [
            {"key": item.key, "quality": item.quality, "semantic": item.semantic}
            for item in observations
        ],
        "warnings": list(warnings),
        "duration_ms": duration_ms,
        "modbus_writes": "none",
        "hardware_writes": "none",
    }


def _required_text(value: object, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


def _duration_ms(started_at: float, completed_at: float) -> int:
    return max(0, round((completed_at - started_at) * 1000))
