"""Strict, stateless single-address search transport for the commissioning wizard."""

from __future__ import annotations

import json
import socket
import threading
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.commissioning.preflight_client import DeviceAgentPreflightError, validated_device_agent_base_url


class AddressSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str = Field(min_length=1, max_length=64)
    bus_id: str = Field(pattern=r"^commissioning-[0-9a-f]{16}$")
    stable_transport_identifier: str = Field(pattern=r"^/dev/serial/by-id/[^/\s]+$", max_length=255)
    unit_id: int = Field(ge=1, le=247)
    profile_id: Literal["dixell-xjp60d"]
    profile_version: Literal["dixell-xjp60d-fc03-v1"]
    isolated_bus_confirmed: bool

    @field_validator("isolated_bus_confirmed")
    @classmethod
    def require_isolation(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Confirm a separate test connection before searching")
        return value


class AddressSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    profile_id: Literal["dixell-xjp60d"]
    profile_version: Literal["dixell-xjp60d-fc03-v1"]
    state: Literal["completed", "failed", "cancelled", "timed_out"]
    attempted: int = Field(ge=0, le=1)
    total: Literal[1]
    candidates: list[int] = Field(max_length=1)
    exception_addresses: list[int] = Field(max_length=1)
    error_code: str | None = Field(max_length=80)
    modbus_writes: Literal["none"]
    hardware_writes: Literal["none"]


_SEARCH_LOCK = threading.Lock()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _open_address_request(request: Request, *, timeout: float):  # type: ignore[no-untyped-def]
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def search_address(base_url: str, command: AddressSearchRequest) -> AddressSearchResponse:
    if not _SEARCH_LOCK.acquire(blocking=False):
        raise DeviceAgentPreflightError("search_busy", "An address search request is already running")
    try:
        return _search_address(base_url, command)
    finally:
        _SEARCH_LOCK.release()


def _search_address(base_url: str, command: AddressSearchRequest) -> AddressSearchResponse:
    base = validated_device_agent_base_url(base_url)
    wire = command.model_dump(exclude={"unit_id"})
    wire.update(first_unit_id=command.unit_id, last_unit_id=command.unit_id, deadline_seconds=2.0)
    request = Request(
        f"{base}/api/v1/commissioning/address-search",
        method="POST",
        data=json.dumps(wire).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with _open_address_request(request, timeout=4.0) as response:
            body = response.read(8193)
        if len(body) > 8192:
            raise ValueError("Search response too large")
        result = AddressSearchResponse.model_validate(json.loads(body.decode("utf-8")))
        for name in (
            "node_id",
            "bus_id",
            "stable_transport_identifier",
            "unit_id",
            "profile_id",
            "profile_version",
        ):
            if getattr(result, name) != getattr(command, name):
                raise ValueError("Search response identity mismatch")
        if any(unit != command.unit_id for unit in result.candidates + result.exception_addresses):
            raise ValueError("Search response address mismatch")
        if (result.candidates or result.exception_addresses) and (
            result.state != "completed" or result.attempted != 1
        ):
            raise ValueError("Search candidate has no completed read evidence")
        if result.candidates and result.exception_addresses:
            raise ValueError("Conflicting search evidence")
        if result.state == "completed" and (result.attempted != 1 or result.error_code is not None):
            raise ValueError("Invalid completed search evidence")
        return result
    except HTTPError as error:
        raise DeviceAgentPreflightError(
            "search_rejected", f"Device Agent rejected search with HTTP {error.code}"
        ) from error
    except (URLError, socket.timeout, TimeoutError) as error:
        raise DeviceAgentPreflightError(
            "search_unavailable", "Address search is unavailable or timed out"
        ) from error
    except (ValueError, UnicodeDecodeError, ValidationError) as error:
        raise DeviceAgentPreflightError(
            "search_response_invalid", "Invalid address search response"
        ) from error
