from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from acquisition_cadence import ensure_defaults_for_devices
from acquisition_registry import (
    AcquisitionRegistry,
    AcquisitionRegistryStore,
    RegistryDevice,
    RegistryRevisionConflict,
    RegistryTarget,
    XJP60D_PROFILE_VERSION,
    document_to_json,
)
from xjp60d import PROBE_REGISTERS


class TopologyAwareEnrollmentStore(AcquisitionRegistryStore):
    """Persist discovery-only XJP60D devices on their explicit physical bus."""

    def __init__(
        self,
        database_path: Path,
        *,
        bus_for_unit: Callable[[int], str],
        bind_registry: Callable[[AcquisitionRegistry], AcquisitionRegistry],
    ) -> None:
        super().__init__(
            database_path,
            registry_binding=bind_registry,
            embraco_bus_for_unit=bus_for_unit,
        )
        self._bus_for_unit = bus_for_unit

    def enroll_xjp60d(
        self,
        registry: AcquisitionRegistry,
        *,
        expected_revision: int,
        unit_ids: Iterable[int],
        actor: str,
        reason: str,
        profile_version: str = XJP60D_PROFILE_VERSION,
        bus_for_unit: Callable[[int], str] | None = None,
    ) -> AcquisitionRegistry:
        normalized_actor = actor.strip()[:200]
        normalized_reason = reason.strip()[:500]
        if not normalized_actor:
            raise ValueError("Registry enrollment actor is required")
        if not normalized_reason:
            raise ValueError("Registry enrollment reason is required")
        if profile_version != XJP60D_PROFILE_VERSION:
            raise ValueError(f"Unsupported XJP60D profile: {profile_version!r}")
        if expected_revision != registry.revision:
            raise RegistryRevisionConflict(
                f"Expected revision {expected_revision}, current revision is {registry.revision}"
            )

        requested_values = tuple(unit_ids)
        if any(
            not isinstance(unit_id, int) or isinstance(unit_id, bool)
            for unit_id in requested_values
        ):
            raise ValueError("XJP60D Modbus Unit IDs must be integers")
        requested = set(requested_values)
        if any(not 1 <= unit_id <= 247 for unit_id in requested):
            raise ValueError("Invalid XJP60D Modbus Unit ID")

        configured_buses = {bus.bus_id for bus in registry.document.buses}
        existing_by_unit: dict[int, list[RegistryDevice]] = {}
        for device in registry.document.devices:
            existing_by_unit.setdefault(device.unit_id, []).append(device)

        additions: list[tuple[int, str]] = []
        for unit_id in sorted(requested):
            bus_id = (bus_for_unit or self._bus_for_unit)(unit_id)
            if bus_id not in configured_buses:
                raise ValueError(
                    f"Configured bus {bus_id!r} is absent from acquisition registry"
                )
            existing = existing_by_unit.get(unit_id, [])
            if existing:
                if len(existing) != 1:
                    raise ValueError(
                        f"Ambiguous Modbus Unit ID {unit_id} across registry buses"
                    )
                device = existing[0]
                if (
                    device.bus_id != bus_id
                    or device.device_family != "xjp60d"
                    or device.profile_version != XJP60D_PROFILE_VERSION
                ):
                    raise ValueError(
                        "Conflicting Modbus Unit ownership for discovery enrollment: "
                        f"unit={unit_id}, registry_bus={device.bus_id}, configured_bus={bus_id}"
                    )
                continue
            additions.append((unit_id, bus_id))

        if not additions:
            return registry

        devices = list(registry.document.devices)
        targets = list(registry.document.targets)
        changes: list[dict[str, str]] = []
        for unit_id, bus_id in additions:
            device_id = f"xjp60d-{unit_id}"
            devices.append(
                RegistryDevice(
                    device_id=device_id,
                    bus_id=bus_id,
                    device_family="xjp60d",
                    unit_id=unit_id,
                    profile_version=XJP60D_PROFILE_VERSION,
                    lifecycle="discovery_only",
                )
            )
            changes.append(
                {
                    "entity": "device",
                    "id": device_id,
                    "from": "absent",
                    "to": f"discovery_only@{bus_id}",
                }
            )
            for channel in range(1, 7):
                value_address, status_address = PROBE_REGISTERS[channel]
                channel_id = f"{unit_id}-{channel:02d}"
                target = RegistryTarget(
                    target_id=f"xjp60d:{channel_id}",
                    device_id=device_id,
                    kind="channel",
                    key=f"channel-{channel:02d}",
                    telemetry_channel_id=channel_id,
                    metric="temperature.probe",
                    unit="degC",
                    profile_version=XJP60D_PROFILE_VERSION,
                    lifecycle="discovery_only",
                    function=3,
                    addresses=(value_address, status_address),
                )
                targets.append(target)
                changes.append(
                    {
                        "entity": "target",
                        "id": target.target_id,
                        "from": "absent",
                        "to": "discovery_only",
                    }
                )

        cadence = ensure_defaults_for_devices(registry.document.cadence, devices)
        old_defaults = {
            (item.bus_id, item.device_family) for item in registry.document.cadence.family_defaults
        }
        for item in cadence.family_defaults:
            if (item.bus_id, item.device_family) not in old_defaults:
                changes.append(
                    {
                        "entity": "cadence_family_default",
                        "id": f"{item.bus_id}/{item.device_family}",
                        "from": "absent",
                        "to": str(item.interval_seconds),
                    }
                )

        updated_at = datetime.now(timezone.utc).isoformat()
        updated = AcquisitionRegistry(
            replace(
                registry.document,
                revision=registry.document.revision + 1,
                devices=tuple(devices),
                targets=tuple(targets),
                cadence=cadence,
                updated_at=updated_at,
            )
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
                cursor = self._connection.execute(
                    """
                    UPDATE acquisition_registry_state
                    SET schema_version = ?, revision = ?, document = ?, updated_at = ?
                    WHERE singleton = 1 AND revision = ?
                    """,
                    (
                        updated.document.schema_version,
                        updated.document.revision,
                        document_to_json(updated.document),
                        updated.document.updated_at,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RegistryRevisionConflict(
                        f"Expected revision {expected_revision}, registry update did not apply"
                    )
                self._connection.execute(
                    """
                    INSERT INTO acquisition_registry_audit(
                        revision, actor, reason, changes, changed_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        updated.document.revision,
                        normalized_actor,
                        normalized_reason,
                        json.dumps(changes, separators=(",", ":"), ensure_ascii=False),
                        updated.document.updated_at,
                    ),
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return updated
