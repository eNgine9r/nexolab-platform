from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from acquisition_cadence import rebind_policy
from acquisition_registry import AcquisitionRegistry, RegistryBus
from main import Settings

BUS_CONFIG_ENV = "RS485_BUS_CONFIG_JSON"
LEGACY_BUS_ID = "rs485-main"
_BUS_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_STABLE_DEVICE_PREFIXES = (
    "/dev/serial/by-id/",
    "/host/dev/serial/by-id/",
)
_ALLOWED_FIELDS = {
    "bus_id",
    "serial_device",
    "unit_ids",
    "baudrate",
    "parity",
    "stopbits",
    "timeout_seconds",
    "retries",
}


@dataclass(frozen=True)
class RS485BusBinding:
    bus_id: str
    serial_device: str
    unit_ids: tuple[int, ...]
    baudrate: int
    parity: str
    stopbits: int
    timeout_seconds: float
    retries: int


class RS485BusTopology:
    """Validated logical-bus to stable serial-device bindings.

    The explicit JSON contract is authoritative when present. When absent the
    existing single-bus SERIAL_* settings remain authoritative so existing
    installations keep the exact legacy runtime path.
    """

    def __init__(
        self,
        bindings: tuple[RS485BusBinding, ...],
        *,
        explicit: bool,
    ) -> None:
        if not bindings:
            raise ValueError("At least one RS-485 bus binding is required")
        self.bindings = bindings
        self.explicit = explicit
        self._by_bus = {item.bus_id: item for item in bindings}
        self._unit_to_bus: dict[int, str] = {}
        for binding in bindings:
            for unit_id in binding.unit_ids:
                if unit_id in self._unit_to_bus:
                    raise ValueError(
                        "Modbus Unit ID is assigned to multiple physical buses: "
                        f"{unit_id}"
                    )
                self._unit_to_bus[unit_id] = binding.bus_id

    @classmethod
    def from_environment(
        cls,
        settings: Settings,
        registry: AcquisitionRegistry | None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "RS485BusTopology":
        source = os.environ if environ is None else environ
        raw = source.get(BUS_CONFIG_ENV, "").strip()
        if not raw:
            if registry is None:
                raise ValueError(
                    f"{BUS_CONFIG_ENV} is required for explicit topology parsing"
                )
            existing_bus_ids = {item.bus_id for item in registry.document.buses}
            if existing_bus_ids - {LEGACY_BUS_ID}:
                raise ValueError(
                    "Persisted multi-bus acquisition registry requires "
                    f"{BUS_CONFIG_ENV}"
                )
            known_units = tuple(
                sorted({item.unit_id for item in registry.document.devices})
            )
            return cls(
                (
                    RS485BusBinding(
                        bus_id=LEGACY_BUS_ID,
                        serial_device=settings.serial_device,
                        unit_ids=known_units,
                        baudrate=settings.serial_baudrate,
                        parity=settings.serial_parity,
                        stopbits=settings.serial_stopbits,
                        timeout_seconds=settings.serial_timeout_seconds,
                        retries=settings.serial_retries,
                    ),
                ),
                explicit=False,
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"{BUS_CONFIG_ENV} must contain valid JSON") from error
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{BUS_CONFIG_ENV} must be a non-empty array")
        if len(payload) > 8:
            raise ValueError("At most 8 RS-485 buses may be configured")

        bindings: list[RS485BusBinding] = []
        bus_ids: set[str] = set()
        serial_devices: set[str] = set()
        unit_owners: dict[int, str] = {}
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError(f"{BUS_CONFIG_ENV}[{index}] must be an object")
            unknown = sorted(set(item) - _ALLOWED_FIELDS)
            if unknown:
                raise ValueError(
                    f"{BUS_CONFIG_ENV}[{index}] contains unsupported fields: "
                    + ", ".join(unknown)
                )

            bus_id = str(item.get("bus_id", "")).strip().casefold()
            if not _BUS_ID_PATTERN.fullmatch(bus_id):
                raise ValueError(f"{BUS_CONFIG_ENV}[{index}].bus_id is invalid")
            if bus_id in bus_ids:
                raise ValueError(f"Duplicate RS-485 bus_id: {bus_id}")
            bus_ids.add(bus_id)

            serial_device = str(item.get("serial_device", "")).strip()
            if not serial_device.startswith(_STABLE_DEVICE_PREFIXES):
                raise ValueError(
                    f"RS-485 bus {bus_id} must use a stable /dev/serial/by-id path"
                )
            if serial_device in serial_devices:
                raise ValueError(
                    "Two physical RS-485 buses cannot use the same serial path: "
                    f"{serial_device}"
                )
            serial_devices.add(serial_device)

            raw_units = item.get("unit_ids")
            if not isinstance(raw_units, list):
                raise ValueError(f"RS-485 bus {bus_id} unit_ids must be an array")
            units: list[int] = []
            for raw_unit in raw_units:
                if not isinstance(raw_unit, int) or isinstance(raw_unit, bool):
                    raise ValueError(f"RS-485 bus {bus_id} Unit IDs must be integers")
                if not 1 <= raw_unit <= 247:
                    raise ValueError(f"RS-485 bus {bus_id} Unit ID must be 1..247")
                if raw_unit in units:
                    raise ValueError(
                        f"Duplicate Unit ID {raw_unit} inside RS-485 bus {bus_id}"
                    )
                previous = unit_owners.get(raw_unit)
                if previous is not None:
                    raise ValueError(
                        f"Modbus Unit ID {raw_unit} is assigned to both {previous} and {bus_id}"
                    )
                units.append(raw_unit)
                unit_owners[raw_unit] = bus_id

            baudrate = _positive_int(
                item.get("baudrate", settings.serial_baudrate),
                label=f"RS-485 bus {bus_id} baudrate",
            )
            parity = str(item.get("parity", settings.serial_parity)).strip().upper()
            if parity not in {"N", "E", "O"}:
                raise ValueError(f"RS-485 bus {bus_id} parity must be N, E, or O")
            stopbits = _positive_int(
                item.get("stopbits", settings.serial_stopbits),
                label=f"RS-485 bus {bus_id} stopbits",
            )
            if stopbits not in {1, 2}:
                raise ValueError(f"RS-485 bus {bus_id} stopbits must be 1 or 2")
            timeout_seconds = _positive_float(
                item.get("timeout_seconds", settings.serial_timeout_seconds),
                label=f"RS-485 bus {bus_id} timeout_seconds",
            )
            retries = _non_negative_int(
                item.get("retries", settings.serial_retries),
                label=f"RS-485 bus {bus_id} retries",
            )
            bindings.append(
                RS485BusBinding(
                    bus_id=bus_id,
                    serial_device=serial_device,
                    unit_ids=tuple(units),
                    baudrate=baudrate,
                    parity=parity,
                    stopbits=stopbits,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                )
            )

        if registry is not None:
            known_units = {item.unit_id for item in registry.document.devices}
            missing = sorted(known_units - set(unit_owners))
            if missing:
                rendered = ", ".join(str(item) for item in missing)
                raise ValueError(
                    "Every registry device must have one explicit RS-485 bus; "
                    f"missing Unit IDs: {rendered}"
                )
        return cls(tuple(bindings), explicit=True)

    @classmethod
    def explicit_from_environment(
        cls,
        settings: Settings,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "RS485BusTopology | None":
        source = os.environ if environ is None else environ
        if not source.get(BUS_CONFIG_ENV, "").strip():
            return None
        return cls.from_environment(settings, None, environ=source)

    def binding(self, bus_id: str) -> RS485BusBinding:
        try:
            return self._by_bus[bus_id]
        except KeyError as error:
            raise ValueError(f"Unknown RS-485 bus_id: {bus_id}") from error

    def bus_for_unit(self, unit_id: int) -> str:
        try:
            return self._unit_to_bus[unit_id]
        except KeyError as error:
            raise ValueError(
                f"Modbus Unit ID {unit_id} has no configured physical bus"
            ) from error

    def units_for_bus(self, bus_id: str) -> tuple[int, ...]:
        return self.binding(bus_id).unit_ids

    def bind_registry(self, registry: AcquisitionRegistry) -> AcquisitionRegistry:
        if not self.explicit:
            return registry
        configured_bus_ids = set(self._by_bus)
        devices = []
        for device in registry.document.devices:
            static_owner = self._unit_to_bus.get(device.unit_id)
            if static_owner is not None:
                bus_id = static_owner
            elif device.bus_id in configured_bus_ids:
                bus_id = device.bus_id
            else:
                raise ValueError(
                    f"Persisted registry bus {device.bus_id!r} for Unit ID {device.unit_id} is not configured"
                )
            devices.append(replace(device, bus_id=bus_id))
        devices = tuple(devices)
        cadence = rebind_policy(
            registry.document.cadence,
            old_devices=registry.document.devices,
            new_devices=devices,
        )
        document = replace(
            registry.document,
            buses=tuple(
                RegistryBus(
                    bus_id=item.bus_id,
                    protocol="modbus_rtu",
                    read_only=True,
                )
                for item in self.bindings
            ),
            devices=devices,
            cadence=cadence,
        )
        return AcquisitionRegistry(document)

    def diagnostics(
        self,
        registry: AcquisitionRegistry,
        *,
        scheduler_snapshot: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        devices = {item.device_id: item for item in registry.document.devices}
        scheduler_buses = (
            scheduler_snapshot.get("buses", {})
            if scheduler_snapshot is not None
            else {}
        )
        result: list[dict[str, Any]] = []
        for binding in self.bindings:
            bus_devices = [
                item
                for item in registry.document.devices
                if item.bus_id == binding.bus_id
            ]
            active_devices = [item for item in bus_devices if item.lifecycle == "active"]
            active_targets = [
                target
                for target in registry.eligible_targets()
                if devices[target.device_id].bus_id == binding.bus_id
            ]
            path_present = Path(binding.serial_device).exists()
            result.append(
                {
                    "bus_id": binding.bus_id,
                    "serial_device": binding.serial_device,
                    "device_path_present": path_present,
                    "hardware_state": (
                        "present_unverified" if path_present else "configured_unavailable"
                    ),
                    "acceptance_state": "hardware_unverified",
                    "configuration_source": (
                        "explicit_multi_bus" if self.explicit else "legacy_single_bus"
                    ),
                    "configured_unit_count": len(binding.unit_ids),
                    "registry_device_count": len(bus_devices),
                    "active_device_count": len(active_devices),
                    "active_target_count": len(active_targets),
                    "serial": {
                        "baudrate": binding.baudrate,
                        "parity": binding.parity,
                        "stopbits": binding.stopbits,
                        "timeout_seconds": binding.timeout_seconds,
                        "retries": binding.retries,
                    },
                    "scheduler": scheduler_buses.get(binding.bus_id),
                }
            )
        return result


def _positive_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _positive_float(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    resolved = float(value)
    if resolved <= 0:
        raise ValueError(f"{label} must be positive")
    return resolved
