"""Read-only scheme picker inventory from the local acquisition authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.commissioning.preflight_client import validated_device_agent_base_url


@dataclass(frozen=True, slots=True)
class CommissionedTemperature:
    channel_id: str
    equipment_id: str
    controller_label: str
    input_number: int


@dataclass(frozen=True, slots=True)
class CommissionedTemperatureInventory:
    node_id: str
    channels: tuple[CommissionedTemperature, ...]


SECTION_CHANNEL = re.compile(r"([A-Za-z0-9_-]+):([1-9][0-9]{0,2})-S0([1-6])\Z")


def section_temperature(channel_id: str) -> CommissionedTemperature | None:
    match = SECTION_CHANNEL.fullmatch(channel_id)
    if not match:
        return None
    bus_id, unit, section = match.groups()
    if int(unit) > 247:
        return None
    return CommissionedTemperature(
        channel_id, f"XJP60D-S:{bus_id}:{unit}", f"Dixell №{unit} · {bus_id}", int(section)
    )


def parse_temperature_inventory(
    registry: dict, configuration: dict
) -> CommissionedTemperatureInventory:
    node = configuration.get("node_id")
    revision = registry.get("revision")
    if not isinstance(node, str) or not node.strip() or len(node) > 64:
        raise ValueError("Missing Device Agent node")
    if (
        registry.get("schema_version") != 2
        or type(revision) is not int
        or revision < 1
        or configuration.get("registry_revision") != revision
    ):
        raise ValueError("Acquisition registry revision differs")
    buses = _index(registry.get("buses"), "bus_id")
    devices = _index(registry.get("devices"), "device_id")
    targets = _index(registry.get("targets"), "target_id")
    candidates: dict[str, CommissionedTemperature] = {}
    for target in targets.values():
        channel = target.get("telemetry_channel_id")
        identity = section_temperature(channel) if isinstance(channel, str) else None
        if identity is None:
            continue
        bus_id, _, suffix = channel.rpartition(":")
        unit, _, section = suffix.partition("-")
        device_id = f"xjp60d-sections:{bus_id}:{unit}"
        device = devices.get(device_id, {})
        bus = buses.get(bus_id, {})
        if (
            target.get("device_id") != device_id
            or target.get("target_id") != f"{device_id}-{section}"
            or target.get("lifecycle") != "active"
            or target.get("poll_eligible") is not True
            or target.get("function") != 3
            or target.get("metric") != "temperature.probe"
            or target.get("unit") != "degC"
            or device.get("device_family") != "xjp60d"
            or device.get("lifecycle") != "active"
            or device.get("bus_id") != bus_id
            or device.get("unit_id") != int(unit)
            or bus.get("read_only") is not True
            or bus.get("protocol") != "modbus_rtu"
        ):
            continue
        if channel in candidates:
            raise ValueError("Ambiguous temperature channel")
        candidates[channel] = identity
    return CommissionedTemperatureInventory(node, tuple(candidates.values()))


def _index(rows: object, key: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError("Missing acquisition registry collection")
    index: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid acquisition registry row")
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in index:
            raise ValueError("Invalid acquisition registry identity")
        index[identity] = row
    return index


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalCommissionedTemperatureReader:
    def __init__(self, base_url: str) -> None:
        self._base_url = validated_device_agent_base_url(base_url)
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def __call__(self) -> CommissionedTemperatureInventory | None:
        try:
            registry = self._read("/api/v1/acquisition-registry")
            configuration = self._read("/api/v1/xjp60d/configuration")
            return parse_temperature_inventory(registry, configuration)
        except (OSError, ValueError):
            return None

    def _read(self, path: str) -> dict:
        request = Request(
            self._base_url + path, headers={"Accept": "application/json"}, method="GET"
        )
        limit = 2 * 1024 * 1024
        with self._opener.open(request, timeout=2.0) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Acquisition inventory response too large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Acquisition inventory response must be an object")
        return value
