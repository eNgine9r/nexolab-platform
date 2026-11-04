"""Bounded XJP60D address search; no HTTP endpoint or registry mutations.

The calling layer must authenticate the operator and supply a real isolation
attestation. A serial adapter's USB identity cannot prove physical isolation.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from commissioning_preflight import (
    PROFILES,
    PreflightBus,
    PreflightExecutionError,
    PreflightObservation,
    PreflightProfile,
    canonical_serial_identifier,
    is_stable_serial_identifier,
)

_FIELDS = frozenset(
    {
        "node_id",
        "bus_id",
        "stable_transport_identifier",
        "profile_id",
        "profile_version",
        "first_unit_id",
        "last_unit_id",
        "deadline_seconds",
        "isolated_bus_confirmed",
    }
)
_BUS_ID = re.compile(r"^commissioning-[0-9a-f]{16}$")
_SCAN_GUARD = threading.Lock()
_PROFILE_ID = "dixell-xjp60d"
_PROFILE_VERSION = "dixell-xjp60d-fc03-v1"
_READ_DEADLINE_SECONDS = 2.0
_MIN_INTERVAL_SECONDS = 0.025


@dataclass(frozen=True)
class SearchRequest:
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    first_unit_id: int
    last_unit_id: int
    deadline_seconds: float
    isolated_bus_confirmed: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id, str)
            or not self.node_id
            or self.node_id != self.node_id.strip()
            or len(self.node_id) > 64
            or any(ord(char) < 32 for char in self.node_id)
        ):
            raise ValueError("Invalid node identity")
        if not isinstance(self.bus_id, str) or not _BUS_ID.fullmatch(self.bus_id):
            raise ValueError("A commissioning-only bus identity is required")
        if (
            not isinstance(self.stable_transport_identifier, str)
            or len(self.stable_transport_identifier) > 255
            or self.stable_transport_identifier != self.stable_transport_identifier.strip()
            or any(ord(char) < 32 for char in self.stable_transport_identifier)
            or not is_stable_serial_identifier(self.stable_transport_identifier)
        ):
            raise ValueError("A stable adapter identity is required")
        if self.isolated_bus_confirmed is not True:
            raise ValueError("Physical isolation must be confirmed by the operator")
        first, last = self.first_unit_id, self.last_unit_id
        if (
            not isinstance(first, int)
            or isinstance(first, bool)
            or not isinstance(last, int)
            or isinstance(last, bool)
            or not 1 <= first <= last <= 247
        ):
            raise ValueError("Unit range must be within 1..247")
        deadline = self.deadline_seconds
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not 1 <= deadline <= 600:
            raise ValueError("Search deadline must be within 1..600 seconds")


@dataclass(frozen=True)
class SearchResult:
    state: str
    attempted: int
    total: int
    candidates: tuple[int, ...]
    exception_addresses: tuple[int, ...]
    error_code: str | None = None


class SearchRuntime(Protocol):
    node_id: str

    def commissioning_connections(self) -> dict[str, Any]: ...
    def preflight_bus(self, bus_id: str) -> PreflightBus: ...
    def preflight_read_profile(
        self,
        profile: PreflightProfile,
        *,
        bus_id: str,
        unit_id: int,
        deadline_monotonic: float,
        commissioning_only: bool,
    ) -> tuple[PreflightObservation, ...]: ...


def parse_search_request(payload: object) -> SearchRequest:
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise ValueError("Search request must contain exactly the supported fields")
    node, bus, stable = (payload[k] for k in ("node_id", "bus_id", "stable_transport_identifier"))
    if not isinstance(node, str) or not node or node != node.strip() or len(node) > 64:
        raise ValueError("Invalid node identity")
    if not isinstance(bus, str) or not _BUS_ID.fullmatch(bus):
        raise ValueError("A commissioning-only bus identity is required")
    if not isinstance(stable, str) or not is_stable_serial_identifier(stable):
        raise ValueError("A stable adapter identity is required")
    if payload["profile_id"] != _PROFILE_ID or payload["profile_version"] != _PROFILE_VERSION:
        raise ValueError("Unsupported search profile")
    if payload["isolated_bus_confirmed"] is not True:
        raise ValueError("Physical isolation must be confirmed by the operator")
    first, last = payload["first_unit_id"], payload["last_unit_id"]
    if (
        not isinstance(first, int)
        or isinstance(first, bool)
        or not isinstance(last, int)
        or isinstance(last, bool)
        or not 1 <= first <= last <= 247
    ):
        raise ValueError("Unit range must be within 1..247")
    deadline = payload["deadline_seconds"]
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not 1 <= deadline <= 600:
        raise ValueError("Search deadline must be within 1..600 seconds")
    return SearchRequest(node, bus, stable, first, last, float(deadline), True)


def _validate_connection(request: SearchRequest, runtime: SearchRuntime) -> None:
    if runtime.node_id != request.node_id:
        raise PreflightExecutionError("node_identity_mismatch", "Device Agent node changed")
    inventory = runtime.commissioning_connections()
    if (
        not isinstance(inventory, dict)
        or inventory.get("node_id") != request.node_id
        or inventory.get("schema_version") != 1
    ):
        raise PreflightExecutionError("inventory_unavailable", "Connection inventory is unavailable")
    entries = inventory.get("connections")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise PreflightExecutionError("inventory_unavailable", "Connection inventory is invalid")
    paths = [entry.get("stable_transport_identifier") for entry in entries]
    buses = [entry.get("bus_id") for entry in entries]
    if (
        not all(isinstance(value, str) for value in paths + buses)
        or len({canonical_serial_identifier(path) for path in paths}) != len(paths)
        or len(set(buses)) != len(buses)
    ):
        raise PreflightExecutionError("inventory_ambiguous", "Connection identities are ambiguous")
    if any(
        entry.get("ownership") not in {"production_bus", "available_commissioning"}
        or not isinstance(entry.get("present"), bool)
        or not isinstance(entry.get("available_for_preflight"), bool)
        for entry in entries
    ):
        raise PreflightExecutionError("inventory_unavailable", "Connection inventory is invalid")
    production = [entry for entry in entries if entry.get("ownership") == "production_bus"]
    if not production or any(entry.get("present") is not True for entry in production):
        raise PreflightExecutionError("adapter_unavailable", "Protected production adapter is missing")
    selected = [entry for entry in entries if entry.get("bus_id") == request.bus_id]
    if len(selected) != 1:
        raise PreflightExecutionError("adapter_unavailable", "Adapter is not present in inventory")
    entry = selected[0]
    if (
        entry.get("stable_transport_identifier") != request.stable_transport_identifier
        or entry.get("ownership") != "available_commissioning"
        or entry.get("present") is not True
        or entry.get("available_for_preflight") is not True
    ):
        raise PreflightExecutionError("adapter_unavailable", "Adapter is unavailable or protected")
    try:
        bus = runtime.preflight_bus(request.bus_id)
        if (
            bus.bus_id != request.bus_id
            or not bus.path_present
            or canonical_serial_identifier(bus.serial_device)
            != canonical_serial_identifier(request.stable_transport_identifier)
        ):
            raise ValueError("Adapter identity changed")
    except (ValueError, OSError, PreflightExecutionError) as error:
        raise PreflightExecutionError(
            "adapter_unavailable", "Adapter identity could not be verified"
        ) from error


def run_search(
    request: SearchRequest,
    runtime: SearchRuntime,
    *,
    cancelled: threading.Event,
    progress: Callable[[SearchResult], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> SearchResult:
    """Sequential profile reads. A candidate is not proof of model or live telemetry."""
    total = request.last_unit_id - request.first_unit_id + 1
    candidates: list[int] = []
    exceptions: list[int] = []
    attempted = 0

    def result(state: str, error: str | None = None) -> SearchResult:
        return SearchResult(state, attempted, total, tuple(candidates), tuple(exceptions), error)

    if not _SCAN_GUARD.acquire(blocking=False):
        return result("failed", "search_busy")
    try:
        deadline = monotonic() + request.deadline_seconds
        profile = PROFILES.get(_PROFILE_ID)
        if profile is None or profile.profile_version != _PROFILE_VERSION:
            return result("failed", "profile_unavailable")
        for unit_id in range(request.first_unit_id, request.last_unit_id + 1):
            if cancelled.is_set():
                return result("cancelled")
            if monotonic() >= deadline:
                return result("timed_out")
            try:
                _validate_connection(request, runtime)
                read_deadline = min(deadline, monotonic() + _READ_DEADLINE_SECONDS)
                attempted += 1
                observations = runtime.preflight_read_profile(
                    profile,
                    bus_id=request.bus_id,
                    unit_id=unit_id,
                    deadline_monotonic=read_deadline,
                    commissioning_only=True,
                )
                completed_at = monotonic()
                if completed_at >= deadline:
                    return result("timed_out")
                if completed_at > read_deadline:
                    return result("failed", "read_deadline_exceeded")
                _validate_connection(request, runtime)
                if cancelled.is_set():
                    return result("cancelled")
                if not observations:
                    return result("failed", "empty_response")
                candidates.append(unit_id)
            except PreflightExecutionError as error:
                if error.code in {"timeout", "profile_mismatch"}:
                    try:
                        _validate_connection(request, runtime)
                    except PreflightExecutionError as validation_error:
                        return result("failed", validation_error.code)
                    if cancelled.is_set():
                        return result("cancelled")
                    if monotonic() >= deadline:
                        return result("timed_out")
                    if error.code == "profile_mismatch":
                        exceptions.append(unit_id)
                else:
                    return result("failed", error.code)
            except (OSError, ValueError):
                return result("failed", "adapter_unavailable")
            if progress is not None:
                progress(result("running"))
            if cancelled.wait(_MIN_INTERVAL_SECONDS):
                return result("cancelled")
        return result("completed")
    finally:
        _SCAN_GUARD.release()
