from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from acquisition_cadence import (
    CadenceMutation,
    CadencePolicy,
    apply_mutation as apply_cadence_mutation,
    build_bootstrap_policy,
    cadence_from_payload,
    cadence_to_payload,
    effective_interval,
    ensure_defaults_for_devices,
    validate_policy as validate_cadence_policy,
)
from embraco import PROFILE_VERSION as EMBRACO_PROFILE_VERSION, REGISTERS as EMBRACO_REGISTERS
from le01mp import REGISTERS as LE01MP_REGISTERS
from main import Settings, mode_uses_embraco, mode_uses_le01mp, mode_uses_xjp60d
from xjp60d import PROBE_REGISTERS

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
BUS_ID = "rs485-main"
READ_FUNCTION = 3
XJP60D_PROFILE_VERSION = "dixell-xjp60d-fc03-v1"
LE01MP_PROFILE_VERSION = "f-and-f-le01mp-fc03-v2"
_LEGACY_LE01MP_PROFILE_VERSION = "f-and-f-le01mp-fc03-v1"
LIFECYCLES = frozenset(
    {
        "active",
        "disabled",
        "reserve",
        "retired",
        "uninstalled",
        "discovery_only",
        "invalid",
    }
)
POLLING_LIFECYCLE = "active"


@dataclass(frozen=True)
class RegistryBus:
    bus_id: str
    protocol: str
    read_only: bool


@dataclass(frozen=True)
class RegistryDevice:
    device_id: str
    bus_id: str
    device_family: str
    unit_id: int
    profile_version: str
    lifecycle: str


@dataclass(frozen=True)
class RegistryTarget:
    target_id: str
    device_id: str
    kind: str
    key: str
    telemetry_channel_id: str
    metric: str
    unit: str
    profile_version: str
    lifecycle: str
    function: int
    addresses: tuple[int, ...]


@dataclass(frozen=True)
class RegistryDocument:
    schema_version: int
    revision: int
    buses: tuple[RegistryBus, ...]
    devices: tuple[RegistryDevice, ...]
    targets: tuple[RegistryTarget, ...]
    cadence: CadencePolicy
    updated_at: str


@dataclass(frozen=True)
class LifecycleMutation:
    target_id: str
    lifecycle: str


@dataclass(frozen=True)
class DeviceLifecycleMutation:
    device_id: str
    lifecycle: str


class RegistryRevisionConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_lifecycle(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in LIFECYCLES:
        raise ValueError(f"Unsupported acquisition lifecycle: {value!r}")
    return normalized


def _validate_document(document: RegistryDocument) -> RegistryDocument:
    if document.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported acquisition registry schema_version={document.schema_version}"
        )
    if document.revision < 1:
        raise ValueError("Acquisition registry revision must be positive")

    buses: dict[str, RegistryBus] = {}
    for bus in document.buses:
        if not bus.bus_id.strip():
            raise ValueError("Registry bus_id must not be empty")
        if bus.bus_id in buses:
            raise ValueError(f"Duplicate registry bus_id: {bus.bus_id}")
        if bus.protocol != "modbus_rtu" or not bus.read_only:
            raise ValueError("Acquisition buses must be read-only Modbus RTU")
        buses[bus.bus_id] = bus

    devices: dict[str, RegistryDevice] = {}
    bus_units: set[tuple[str, int]] = set()
    for device in document.devices:
        if device.device_id in devices:
            raise ValueError(f"Duplicate registry device_id: {device.device_id}")
        if device.bus_id not in buses:
            raise ValueError(f"Unknown bus for device {device.device_id}: {device.bus_id}")
        if not 1 <= device.unit_id <= 247:
            raise ValueError(f"Invalid Modbus Unit ID for {device.device_id}")
        identity = (device.bus_id, device.unit_id)
        if identity in bus_units:
            raise ValueError(
                f"Duplicate Modbus bus/Unit identity: {device.bus_id}/{device.unit_id}"
            )
        bus_units.add(identity)
        if device.device_family not in {"xjp60d", "le01mp", "embraco"}:
            raise ValueError(f"Unsupported device family: {device.device_family}")
        if not device.profile_version.strip():
            raise ValueError(f"Missing profile version for {device.device_id}")
        _validate_lifecycle(device.lifecycle)
        devices[device.device_id] = device

    validate_cadence_policy(
        document.cadence,
        bus_ids=buses,
        devices=document.devices,
    )

    target_ids: set[str] = set()
    telemetry_ids: set[tuple[str, str]] = set()
    for target in document.targets:
        if target.target_id in target_ids:
            raise ValueError(f"Duplicate registry target_id: {target.target_id}")
        target_ids.add(target.target_id)
        device = devices.get(target.device_id)
        if device is None:
            raise ValueError(f"Unknown target device: {target.device_id}")
        if target.profile_version != device.profile_version:
            raise ValueError(f"Profile mismatch for target {target.target_id}")
        if target.kind not in {"channel", "metric"}:
            raise ValueError(f"Unsupported target kind: {target.kind}")
        if target.function != READ_FUNCTION:
            raise ValueError(f"Registry target {target.target_id} is not read-only FC03")
        if not target.addresses or any(
            not 0 <= address <= 0xFFFF for address in target.addresses
        ):
            raise ValueError(f"Invalid read addresses for target {target.target_id}")
        _validate_lifecycle(target.lifecycle)
        telemetry_identity = (device.device_family, target.telemetry_channel_id)
        if telemetry_identity in telemetry_ids:
            raise ValueError(f"Duplicate telemetry channel identity: {telemetry_identity}")
        telemetry_ids.add(telemetry_identity)

    return document


def document_to_json(document: RegistryDocument) -> str:
    payload = {
        "schema_version": document.schema_version,
        "revision": document.revision,
        "buses": [asdict(item) for item in document.buses],
        "devices": [asdict(item) for item in document.devices],
        "targets": [
            {**asdict(item), "addresses": list(item.addresses)}
            for item in document.targets
        ],
        "cadence": {
            "family_defaults": cadence_to_payload(document.cadence)["family_defaults"],
            "device_overrides": cadence_to_payload(document.cadence)["device_overrides"],
        },
        "updated_at": document.updated_at,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _parse_buses(payload: dict[str, Any]) -> tuple[RegistryBus, ...]:
    return tuple(RegistryBus(**item) for item in payload.get("buses", []))


def _parse_devices(payload: dict[str, Any]) -> tuple[RegistryDevice, ...]:
    return tuple(RegistryDevice(**item) for item in payload.get("devices", []))


def _parse_targets(payload: dict[str, Any]) -> tuple[RegistryTarget, ...]:
    return tuple(
        RegistryTarget(**{**item, "addresses": tuple(item.get("addresses", []))})
        for item in payload.get("targets", [])
    )


def document_from_json(value: str) -> RegistryDocument:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("Acquisition registry payload must be an object")
    if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported acquisition registry schema_version={payload.get('schema_version', 0)}"
        )
    document = RegistryDocument(
        schema_version=SCHEMA_VERSION,
        revision=int(payload.get("revision", 0)),
        buses=_parse_buses(payload),
        devices=_parse_devices(payload),
        targets=_parse_targets(payload),
        cadence=cadence_from_payload(payload.get("cadence")),
        updated_at=str(payload.get("updated_at", "")),
    )
    return _validate_document(document)


def _migrate_v1_document(
    value: str,
    settings: Settings,
) -> tuple[RegistryDocument, list[dict[str, str]]]:
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("Acquisition registry payload must be an object")
    if int(payload.get("schema_version", 0)) != LEGACY_SCHEMA_VERSION:
        raise ValueError("Acquisition registry is not a v1 document")
    buses = _parse_buses(payload)
    devices = _parse_devices(payload)
    cadence = build_bootstrap_policy(
        legacy_interval_seconds=settings.sample_interval_seconds,
        bus_family_keys=(
            (device.bus_id, device.device_family) for device in devices
        ),
    )
    document = RegistryDocument(
        schema_version=SCHEMA_VERSION,
        revision=int(payload.get("revision", 0)) + 1,
        buses=buses,
        devices=devices,
        targets=_parse_targets(payload),
        cadence=cadence,
        updated_at=_now(),
    )
    changes: list[dict[str, str]] = [
        {"entity": "registry_schema", "id": "root", "from": "v1", "to": "v2"}
    ]
    for item in cadence.family_defaults:
        changes.append(
            {
                "entity": "cadence_family_default",
                "id": f"{item.bus_id}/{item.device_family}",
                "from": "legacy_priority_policy",
                "to": str(item.interval_seconds),
            }
        )
    return _validate_document(document), changes


def _xjp_target(unit_id: int, channel: int, lifecycle: str) -> RegistryTarget:
    value_address, status_address = PROBE_REGISTERS[channel]
    channel_id = f"{unit_id}-{channel:02d}"
    return RegistryTarget(
        target_id=f"xjp60d:{channel_id}",
        device_id=f"xjp60d-{unit_id}",
        kind="channel",
        key=f"channel-{channel:02d}",
        telemetry_channel_id=channel_id,
        metric="temperature.probe",
        unit="degC",
        profile_version=XJP60D_PROFILE_VERSION,
        lifecycle=lifecycle,
        function=READ_FUNCTION,
        addresses=(value_address, status_address),
    )


def _le_target(unit_id: int, key: str, lifecycle: str) -> RegistryTarget:
    register = next(item for item in LE01MP_REGISTERS if item.key == key)
    channel_id = f"{unit_id}-{key.replace('_', '-')}"
    return RegistryTarget(
        target_id=f"le01mp:{channel_id}",
        device_id=f"le01mp-{unit_id}",
        kind="metric",
        key=key,
        telemetry_channel_id=channel_id,
        metric=register.metric,
        unit=register.unit,
        profile_version=LE01MP_PROFILE_VERSION,
        lifecycle=lifecycle,
        function=READ_FUNCTION,
        addresses=register.addresses,
    )



def _embraco_target(unit_id: int, key: str, lifecycle: str) -> RegistryTarget:
    register = next(item for item in EMBRACO_REGISTERS if item.key == key)
    channel_id = f"{unit_id}-{key.replace('_', '-')}"
    return RegistryTarget(
        target_id=f"embraco:{channel_id}",
        device_id=f"embraco-{unit_id}",
        kind="metric",
        key=key,
        telemetry_channel_id=channel_id,
        metric=register.metric,
        unit=register.unit,
        profile_version=EMBRACO_PROFILE_VERSION,
        lifecycle=lifecycle,
        function=READ_FUNCTION,
        addresses=(register.address,),
    )

def _reconcile_le01mp_profile(
    document: RegistryDocument,
) -> tuple[RegistryDocument, list[dict[str, str]]]:
    migratable_versions = {_LEGACY_LE01MP_PROFILE_VERSION, LE01MP_PROFILE_VERSION}
    le_devices = {
        device.device_id: device
        for device in document.devices
        if device.device_family == "le01mp" and device.profile_version in migratable_versions
    }
    if not le_devices:
        return document, []

    canonical_registers = {item.key: item for item in LE01MP_REGISTERS}
    changes: list[dict[str, str]] = []
    devices: list[RegistryDevice] = []
    for device in document.devices:
        if device.device_id not in le_devices:
            devices.append(device)
            continue
        updated = replace(device, profile_version=LE01MP_PROFILE_VERSION)
        if updated != device:
            changes.append(
                {
                    "entity": "device_profile",
                    "id": device.device_id,
                    "from": device.profile_version,
                    "to": LE01MP_PROFILE_VERSION,
                }
            )
        devices.append(updated)

    targets: list[RegistryTarget] = []
    existing_keys: dict[str, set[str]] = {device_id: set() for device_id in le_devices}
    for target in document.targets:
        if target.device_id not in le_devices:
            targets.append(target)
            continue
        existing_keys[target.device_id].add(target.key)
        register = canonical_registers.get(target.key)
        updated = replace(target, profile_version=LE01MP_PROFILE_VERSION)
        if register is not None:
            updated = replace(
                updated,
                kind="metric",
                metric=register.metric,
                unit=register.unit,
                function=READ_FUNCTION,
                addresses=register.addresses,
            )
        if updated != target:
            changes.append(
                {
                    "entity": "target_profile",
                    "id": target.target_id,
                    "from": target.profile_version,
                    "to": LE01MP_PROFILE_VERSION,
                }
            )
        targets.append(updated)

    for device_id, device in sorted(le_devices.items()):
        for register in LE01MP_REGISTERS:
            if register.key in existing_keys[device_id]:
                continue
            target = _le_target(device.unit_id, register.key, "active")
            targets.append(target)
            changes.append(
                {"entity": "target", "id": target.target_id, "from": "absent", "to": "active"}
            )

    if not changes:
        return document, []
    reconciled = replace(
        document,
        revision=document.revision + 1,
        devices=tuple(devices),
        targets=tuple(targets),
        updated_at=_now(),
    )
    return _validate_document(reconciled), changes


def build_initial_document(
    settings: Settings,
    *,
    discovery_units: Iterable[int],
    legacy_active_points: tuple[tuple[int, int], ...],
) -> RegistryDocument:
    active_points = set(legacy_active_points) if mode_uses_xjp60d(settings.device_mode) else set()
    xjp_units = (
        {int(unit_id) for unit_id in discovery_units}
        | {unit_id for unit_id, _ in active_points}
        if mode_uses_xjp60d(settings.device_mode)
        else set()
    )
    le_units = set(settings.le01mp_unit_ids) if mode_uses_le01mp(settings.device_mode) else set()
    embraco_units = (
        set(settings.embraco_unit_ids) if mode_uses_embraco(settings.device_mode) else set()
    )
    family_units = {"xjp60d": xjp_units, "le01mp": le_units, "embraco": embraco_units}
    duplicate_units: set[int] = set()
    families = tuple(family_units)
    for index, left in enumerate(families):
        for right in families[index + 1 :]:
            duplicate_units.update(family_units[left] & family_units[right])
    if duplicate_units:
        rendered = ", ".join(str(item) for item in sorted(duplicate_units))
        raise ValueError(f"Duplicate Modbus Unit IDs across device families: {rendered}")

    devices: list[RegistryDevice] = []
    targets: list[RegistryTarget] = []
    for unit_id in sorted(xjp_units):
        device_active = any(point[0] == unit_id for point in active_points)
        devices.append(
            RegistryDevice(
                device_id=f"xjp60d-{unit_id}",
                bus_id=BUS_ID,
                device_family="xjp60d",
                unit_id=unit_id,
                profile_version=XJP60D_PROFILE_VERSION,
                lifecycle="active" if device_active else "discovery_only",
            )
        )
        for channel in range(1, 7):
            lifecycle = "active" if (unit_id, channel) in active_points else "discovery_only"
            targets.append(_xjp_target(unit_id, channel, lifecycle))

    for unit_id in sorted(le_units):
        devices.append(
            RegistryDevice(
                device_id=f"le01mp-{unit_id}",
                bus_id=BUS_ID,
                device_family="le01mp",
                unit_id=unit_id,
                profile_version=LE01MP_PROFILE_VERSION,
                lifecycle="active",
            )
        )
        for register in LE01MP_REGISTERS:
            targets.append(_le_target(unit_id, register.key, "active"))

    for unit_id in sorted(embraco_units):
        devices.append(
            RegistryDevice(
                device_id=f"embraco-{unit_id}",
                bus_id=BUS_ID,
                device_family="embraco",
                unit_id=unit_id,
                profile_version=EMBRACO_PROFILE_VERSION,
                lifecycle="active",
            )
        )
        for register in EMBRACO_REGISTERS:
            targets.append(_embraco_target(unit_id, register.key, "active"))

    cadence = build_bootstrap_policy(
        legacy_interval_seconds=settings.sample_interval_seconds,
        bus_family_keys=((device.bus_id, device.device_family) for device in devices),
    )
    return _validate_document(
        RegistryDocument(
            schema_version=SCHEMA_VERSION,
            revision=1,
            buses=(RegistryBus(bus_id=BUS_ID, protocol="modbus_rtu", read_only=True),),
            devices=tuple(devices),
            targets=tuple(targets),
            cadence=cadence,
            updated_at=_now(),
        )
    )


class AcquisitionRegistry:
    def __init__(self, document: RegistryDocument) -> None:
        self.document = _validate_document(document)
        self._devices = {item.device_id: item for item in document.devices}
        self._targets = {item.target_id: item for item in document.targets}

    @property
    def revision(self) -> int:
        return self.document.revision

    def effective_poll_eligible(self, target: RegistryTarget) -> bool:
        device = self._devices[target.device_id]
        return (
            device.lifecycle == POLLING_LIFECYCLE
            and target.lifecycle == POLLING_LIFECYCLE
            and target.function == READ_FUNCTION
        )

    def eligible_targets(self, family: str | None = None) -> tuple[RegistryTarget, ...]:
        return tuple(
            target
            for target in self.document.targets
            if (family is None or self._devices[target.device_id].device_family == family)
            and self.effective_poll_eligible(target)
        )

    def eligible_xjp60d_points(self) -> tuple[tuple[int, int], ...]:
        points: list[tuple[int, int]] = []
        for target in self.eligible_targets("xjp60d"):
            device = self._devices[target.device_id]
            channel = int(target.key.removeprefix("channel-"))
            points.append((device.unit_id, channel))
        return tuple(points)

    def eligible_le01mp_metrics(self) -> tuple[tuple[int, str], ...]:
        return tuple(
            (self._devices[target.device_id].unit_id, target.key)
            for target in self.eligible_targets("le01mp")
        )

    def eligible_embraco_metrics(self) -> tuple[tuple[int, str], ...]:
        return tuple(
            (self._devices[target.device_id].unit_id, target.key)
            for target in self.eligible_targets("embraco")
        )

    def effective_cadence_for_device(self, device_id: str) -> tuple[float, str]:
        try:
            device = self._devices[device_id]
        except KeyError as error:
            raise ValueError(f"Unknown registry device: {device_id}") from error
        return effective_interval(
            self.document.cadence,
            device_id=device.device_id,
            bus_id=device.bus_id,
            device_family=device.device_family,
        )

    def lifecycle_counts(self) -> dict[str, int]:
        counts = {value: 0 for value in sorted(LIFECYCLES)}
        for target in self.document.targets:
            counts[target.lifecycle] += 1
        return counts

    def sanitized(self, *, audit: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        devices = []
        for device in self.document.devices:
            device_targets = [target for target in self.document.targets if target.device_id == device.device_id]
            interval, cadence_source = self.effective_cadence_for_device(device.device_id)
            devices.append(
                {
                    **asdict(device),
                    "poll_eligible_targets": sum(
                        1 for target in device_targets if self.effective_poll_eligible(target)
                    ),
                    "inventory_targets": len(device_targets),
                    "effective_interval_seconds": interval,
                    "cadence_source": cadence_source,
                }
            )
        targets = []
        for target in self.document.targets:
            interval, cadence_source = self.effective_cadence_for_device(target.device_id)
            targets.append(
                {
                    **asdict(target),
                    "addresses": list(target.addresses),
                    "poll_eligible": self.effective_poll_eligible(target),
                    "effective_interval_seconds": interval,
                    "cadence_source": cadence_source,
                }
            )
        return {
            "schema_version": self.document.schema_version,
            "revision": self.document.revision,
            "updated_at": self.document.updated_at,
            "buses": [asdict(item) for item in self.document.buses],
            "devices": devices,
            "targets": targets,
            "cadence": cadence_to_payload(self.document.cadence),
            "summary": {
                "inventory_devices": len(self.document.devices),
                "inventory_targets": len(self.document.targets),
                "poll_eligible_targets": len(self.eligible_targets()),
                "lifecycle_counts": self.lifecycle_counts(),
            },
            "recent_audit": audit or [],
        }

    def with_mutations(
        self,
        *,
        device_mutations: tuple[DeviceLifecycleMutation, ...],
        target_mutations: tuple[LifecycleMutation, ...],
    ) -> tuple[RegistryDocument, list[dict[str, str]]]:
        device_ids = [item.device_id for item in device_mutations]
        target_ids = [item.target_id for item in target_mutations]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("Duplicate device mutation")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("Duplicate target mutation")
        device_changes = {item.device_id: _validate_lifecycle(item.lifecycle) for item in device_mutations}
        target_changes = {item.target_id: _validate_lifecycle(item.lifecycle) for item in target_mutations}
        unknown_devices = sorted(set(device_changes) - set(self._devices))
        unknown_targets = sorted(set(target_changes) - set(self._targets))
        if unknown_devices:
            raise ValueError(f"Unknown registry devices: {', '.join(unknown_devices)}")
        if unknown_targets:
            raise ValueError(f"Unknown registry targets: {', '.join(unknown_targets)}")

        changes: list[dict[str, str]] = []
        devices: list[RegistryDevice] = []
        for device in self.document.devices:
            lifecycle = device_changes.get(device.device_id, device.lifecycle)
            if lifecycle != device.lifecycle:
                changes.append(
                    {"entity": "device", "id": device.device_id, "from": device.lifecycle, "to": lifecycle}
                )
            devices.append(replace(device, lifecycle=lifecycle))
        targets: list[RegistryTarget] = []
        for target in self.document.targets:
            lifecycle = target_changes.get(target.target_id, target.lifecycle)
            if lifecycle != target.lifecycle:
                changes.append(
                    {"entity": "target", "id": target.target_id, "from": target.lifecycle, "to": lifecycle}
                )
            targets.append(replace(target, lifecycle=lifecycle))
        if not changes:
            raise ValueError("Registry mutation does not change acquisition eligibility")
        document = replace(
            self.document,
            revision=self.document.revision + 1,
            devices=tuple(devices),
            targets=tuple(targets),
            updated_at=_now(),
        )
        return _validate_document(document), changes

    def with_cadence_mutation(
        self,
        mutation: CadenceMutation,
    ) -> tuple[RegistryDocument, list[dict[str, str]], set[str]]:
        cadence, changes, affected = apply_cadence_mutation(
            self.document.cadence,
            mutation,
            bus_ids=(bus.bus_id for bus in self.document.buses),
            devices=self.document.devices,
        )
        document = replace(
            self.document,
            revision=self.document.revision + 1,
            cadence=cadence,
            updated_at=_now(),
        )
        return _validate_document(document), changes, affected

    def with_xjp60d_enrollment(
        self,
        unit_ids: Iterable[int],
        *,
        profile_version: str = XJP60D_PROFILE_VERSION,
    ) -> tuple[RegistryDocument, list[dict[str, str]]]:
        if profile_version != XJP60D_PROFILE_VERSION:
            raise ValueError(f"Unsupported XJP60D profile: {profile_version!r}")
        requested_values = tuple(unit_ids)
        if any(not isinstance(unit_id, int) or isinstance(unit_id, bool) for unit_id in requested_values):
            raise ValueError("XJP60D Modbus Unit IDs must be integers")
        requested = set(requested_values)
        if any(not 1 <= unit_id <= 247 for unit_id in requested):
            raise ValueError("Invalid XJP60D Modbus Unit ID")
        existing_by_identity = {(device.bus_id, device.unit_id): device for device in self.document.devices}
        additions: list[int] = []
        for unit_id in sorted(requested):
            existing = existing_by_identity.get((BUS_ID, unit_id))
            if existing is None:
                additions.append(unit_id)
                continue
            if existing.device_family != "xjp60d" or existing.profile_version != XJP60D_PROFILE_VERSION:
                raise ValueError(f"Conflicting Modbus bus/Unit identity: {BUS_ID}/{unit_id}")
        if not additions:
            return self.document, []

        devices = list(self.document.devices)
        targets = list(self.document.targets)
        changes: list[dict[str, str]] = []
        for unit_id in additions:
            device_id = f"xjp60d-{unit_id}"
            devices.append(
                RegistryDevice(
                    device_id=device_id,
                    bus_id=BUS_ID,
                    device_family="xjp60d",
                    unit_id=unit_id,
                    profile_version=XJP60D_PROFILE_VERSION,
                    lifecycle="discovery_only",
                )
            )
            changes.append(
                {"entity": "device", "id": device_id, "from": "absent", "to": "discovery_only"}
            )
            for channel in range(1, 7):
                target = _xjp_target(unit_id, channel, "discovery_only")
                targets.append(target)
                changes.append(
                    {"entity": "target", "id": target.target_id, "from": "absent", "to": "discovery_only"}
                )
        cadence = ensure_defaults_for_devices(self.document.cadence, devices)
        existing_default_keys = {
            (item.bus_id, item.device_family) for item in self.document.cadence.family_defaults
        }
        for item in cadence.family_defaults:
            if (item.bus_id, item.device_family) not in existing_default_keys:
                changes.append(
                    {
                        "entity": "cadence_family_default",
                        "id": f"{item.bus_id}/{item.device_family}",
                        "from": "absent",
                        "to": str(item.interval_seconds),
                    }
                )
        document = replace(
            self.document,
            revision=self.document.revision + 1,
            devices=tuple(devices),
            targets=tuple(targets),
            cadence=cadence,
            updated_at=_now(),
        )
        return _validate_document(document), changes

    def with_embraco_enrollment(
        self,
        unit_ids: Iterable[int],
        *,
        lifecycle: str = "active",
    ) -> tuple[RegistryDocument, list[dict[str, str]]]:
        requested_values = tuple(unit_ids)
        if any(not isinstance(unit_id, int) or isinstance(unit_id, bool) for unit_id in requested_values):
            raise ValueError("Embraco Modbus Unit IDs must be integers")
        requested = set(requested_values)
        if any(not 1 <= unit_id <= 247 for unit_id in requested):
            raise ValueError("Invalid Embraco Modbus Unit ID")
        desired_lifecycle = _validate_lifecycle(lifecycle)
        existing_by_identity = {(device.bus_id, device.unit_id): device for device in self.document.devices}
        additions: list[int] = []
        for unit_id in sorted(requested):
            existing = existing_by_identity.get((BUS_ID, unit_id))
            if existing is None:
                additions.append(unit_id)
                continue
            if existing.device_family != "embraco" or existing.profile_version != EMBRACO_PROFILE_VERSION:
                raise ValueError(f"Conflicting Modbus bus/Unit identity: {BUS_ID}/{unit_id}")
        if not additions:
            return self.document, []

        devices = list(self.document.devices)
        targets = list(self.document.targets)
        changes: list[dict[str, str]] = []
        for unit_id in additions:
            device_id = f"embraco-{unit_id}"
            devices.append(
                RegistryDevice(
                    device_id=device_id,
                    bus_id=BUS_ID,
                    device_family="embraco",
                    unit_id=unit_id,
                    profile_version=EMBRACO_PROFILE_VERSION,
                    lifecycle=desired_lifecycle,
                )
            )
            changes.append({"entity": "device", "id": device_id, "from": "absent", "to": desired_lifecycle})
            for register in EMBRACO_REGISTERS:
                target = _embraco_target(unit_id, register.key, desired_lifecycle)
                targets.append(target)
                changes.append({"entity": "target", "id": target.target_id, "from": "absent", "to": desired_lifecycle})
        cadence = ensure_defaults_for_devices(self.document.cadence, devices)
        document = replace(
            self.document,
            revision=self.document.revision + 1,
            devices=tuple(devices),
            targets=tuple(targets),
            cadence=cadence,
            updated_at=_now(),
        )
        return _validate_document(document), changes


class AcquisitionRegistryStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_registry_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_registry_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revision INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    changes TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                )
                """
            )

    def _write_state_locked(self, document: RegistryDocument, expected_revision: int | None = None) -> None:
        if expected_revision is None:
            self._connection.execute(
                """
                UPDATE acquisition_registry_state
                SET schema_version = ?, revision = ?, document = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (
                    document.schema_version,
                    document.revision,
                    document_to_json(document),
                    document.updated_at,
                ),
            )
            return
        cursor = self._connection.execute(
            """
            UPDATE acquisition_registry_state
            SET schema_version = ?, revision = ?, document = ?, updated_at = ?
            WHERE singleton = 1 AND revision = ?
            """,
            (
                document.schema_version,
                document.revision,
                document_to_json(document),
                document.updated_at,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise RegistryRevisionConflict(
                f"Expected revision {expected_revision}, registry update did not apply"
            )

    def _write_audit_locked(
        self,
        document: RegistryDocument,
        *,
        actor: str,
        reason: str,
        changes: list[dict[str, str]],
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO acquisition_registry_audit(
                revision, actor, reason, changes, changed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                document.revision,
                actor,
                reason,
                json.dumps(changes, separators=(",", ":"), ensure_ascii=False),
                document.updated_at,
            ),
        )

    def _commit_candidate(
        self,
        registry: AcquisitionRegistry,
        document: RegistryDocument,
        changes: list[dict[str, str]],
        *,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> AcquisitionRegistry:
        normalized_actor = actor.strip()[:200]
        normalized_reason = reason.strip()[:500]
        if not normalized_actor:
            raise ValueError("Registry mutation actor is required")
        if not normalized_reason:
            raise ValueError("Registry mutation reason is required")
        if expected_revision != registry.revision:
            raise RegistryRevisionConflict(
                f"Expected revision {expected_revision}, current revision is {registry.revision}"
            )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT revision FROM acquisition_registry_state WHERE singleton = 1"
                ).fetchone()
                database_revision = int(row[0]) if row else 0
                if database_revision != expected_revision:
                    raise RegistryRevisionConflict(
                        f"Expected revision {expected_revision}, database revision is {database_revision}"
                    )
                self._write_state_locked(document, expected_revision)
                self._write_audit_locked(
                    document,
                    actor=normalized_actor,
                    reason=normalized_reason,
                    changes=changes,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return AcquisitionRegistry(document)

    def load_or_migrate(
        self,
        settings: Settings,
        *,
        discovery_units: Iterable[int],
        legacy_active_points: tuple[tuple[int, int], ...],
    ) -> AcquisitionRegistry:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT document FROM acquisition_registry_state WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                raw = str(row[0])
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("Acquisition registry payload must be an object")
                schema = int(payload.get("schema_version", 0))
                if schema == LEGACY_SCHEMA_VERSION:
                    document, migration_changes = _migrate_v1_document(raw, settings)
                    self._write_state_locked(document)
                    self._write_audit_locked(
                        document,
                        actor="system:migration",
                        reason="Migrate acquisition registry v1 to persisted device cadence v2",
                        changes=migration_changes,
                    )
                elif schema == SCHEMA_VERSION:
                    document = document_from_json(raw)
                else:
                    raise ValueError(f"Unsupported acquisition registry schema_version={schema}")

                reconciled, changes = _reconcile_le01mp_profile(document)
                if changes:
                    self._write_state_locked(reconciled)
                    self._write_audit_locked(
                        reconciled,
                        actor="system:migration",
                        reason="Upgrade LE-01MP read-only profile with cumulative active energy",
                        changes=changes,
                    )
                registry = AcquisitionRegistry(reconciled)
                if settings.embraco_unit_ids:
                    candidate, embraco_changes = registry.with_embraco_enrollment(
                        settings.embraco_unit_ids, lifecycle="active"
                    )
                    if embraco_changes:
                        self._write_state_locked(candidate)
                        self._write_audit_locked(
                            candidate,
                            actor="system:configuration",
                            reason="Enroll explicitly configured read-only Embraco Sync units",
                            changes=embraco_changes,
                        )
                        registry = AcquisitionRegistry(candidate)
                return registry

            document = build_initial_document(
                settings,
                discovery_units=discovery_units,
                legacy_active_points=legacy_active_points,
            )
            self._connection.execute(
                """
                INSERT INTO acquisition_registry_state(
                    singleton, schema_version, revision, document, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                """,
                (
                    document.schema_version,
                    document.revision,
                    document_to_json(document),
                    document.updated_at,
                ),
            )
            self._write_audit_locked(
                document,
                actor="system:migration",
                reason="Migrate legacy acquisition topology into registry v2",
                changes=[
                    {"entity": "registry", "id": "root", "from": "absent", "to": "v2"},
                    *[
                        {
                            "entity": "cadence_family_default",
                            "id": f"{item.bus_id}/{item.device_family}",
                            "from": "legacy_priority_policy",
                            "to": str(item.interval_seconds),
                        }
                        for item in document.cadence.family_defaults
                    ],
                ],
            )
            return AcquisitionRegistry(document)

    def update(
        self,
        registry: AcquisitionRegistry,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
        device_mutations: tuple[DeviceLifecycleMutation, ...],
        target_mutations: tuple[LifecycleMutation, ...],
    ) -> AcquisitionRegistry:
        document, changes = registry.with_mutations(
            device_mutations=device_mutations,
            target_mutations=target_mutations,
        )
        return self._commit_candidate(
            registry,
            document,
            changes,
            expected_revision=expected_revision,
            actor=actor,
            reason=reason,
        )

    def update_cadence(
        self,
        registry: AcquisitionRegistry,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
        mutation: CadenceMutation,
    ) -> AcquisitionRegistry:
        document, changes, _affected = registry.with_cadence_mutation(mutation)
        return self._commit_candidate(
            registry,
            document,
            changes,
            expected_revision=expected_revision,
            actor=actor,
            reason=reason,
        )

    def enroll_xjp60d(
        self,
        registry: AcquisitionRegistry,
        *,
        expected_revision: int,
        unit_ids: Iterable[int],
        actor: str,
        reason: str,
        profile_version: str = XJP60D_PROFILE_VERSION,
    ) -> AcquisitionRegistry:
        document, changes = registry.with_xjp60d_enrollment(
            unit_ids,
            profile_version=profile_version,
        )
        if not changes:
            return registry
        return self._commit_candidate(
            registry,
            document,
            changes,
            expected_revision=expected_revision,
            actor=actor,
            reason=reason,
        )

    def recent_audit(self, limit: int = 20) -> list[dict[str, Any]]:
        bounded = min(100, max(1, limit))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT revision, actor, reason, changes, changed_at
                FROM acquisition_registry_audit
                ORDER BY id DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [
            {
                "revision": int(row[0]),
                "actor": str(row[1]),
                "reason": str(row[2]),
                "changes": json.loads(str(row[3])),
                "changed_at": str(row[4]),
            }
            for row in rows
        ]


def parse_registry_mutation(
    payload: dict[str, Any],
) -> tuple[
    int,
    str,
    tuple[DeviceLifecycleMutation, ...],
    tuple[LifecycleMutation, ...],
]:
    expected_revision = payload.get("expected_revision")
    reason = payload.get("reason")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        raise ValueError("expected_revision must be a positive integer")
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")
    raw_devices = payload.get("devices", [])
    raw_targets = payload.get("targets", [])
    if not isinstance(raw_devices, list) or not isinstance(raw_targets, list):
        raise ValueError("devices and targets must be arrays")
    if len(raw_devices) + len(raw_targets) > 500:
        raise ValueError("Registry mutation is too large")

    devices: list[DeviceLifecycleMutation] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            raise ValueError("Device mutations must be objects")
        device_id = item.get("device_id")
        lifecycle = item.get("lifecycle")
        if not isinstance(device_id, str) or not isinstance(lifecycle, str):
            raise ValueError("Device mutation requires device_id and lifecycle")
        devices.append(DeviceLifecycleMutation(device_id, lifecycle))

    targets: list[LifecycleMutation] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            raise ValueError("Target mutations must be objects")
        target_id = item.get("target_id")
        lifecycle = item.get("lifecycle")
        if not isinstance(target_id, str) or not isinstance(lifecycle, str):
            raise ValueError("Target mutation requires target_id and lifecycle")
        targets.append(LifecycleMutation(target_id, lifecycle))

    if not devices and not targets:
        raise ValueError("Registry mutation requires at least one device or target")
    return expected_revision, reason, tuple(devices), tuple(targets)
