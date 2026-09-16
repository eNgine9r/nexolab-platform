from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from commissioning_preflight import canonical_serial_identifier

RUNTIME_SERIAL_ROOT = Path("/host/dev/serial/by-id")
HOST_SERIAL_ROOT = Path("/dev/serial/by-id")
_COMMISSIONING_PREFIX = "commissioning-"


@dataclass(frozen=True, slots=True)
class StableSerialAdapter:
    stable_path: str
    runtime_path: str
    real_path: str
    symlink_target: str


def inventory_stable_adapters(root: Path = RUNTIME_SERIAL_ROOT) -> tuple[StableSerialAdapter, ...]:
    """Enumerate only present stable serial identities; never probe the serial bus."""
    if not root.is_dir():
        return ()
    result: list[StableSerialAdapter] = []
    for path in sorted(root.iterdir()):
        if not path.is_symlink():
            continue
        try:
            target = path.readlink()
            real_path = path.resolve(strict=True)
        except OSError:
            continue
        result.append(
            StableSerialAdapter(
                stable_path=_canonical_path(root, path.name),
                runtime_path=str(path),
                real_path=str(real_path),
                symlink_target=str(target),
            )
        )
    return tuple(result)


def commissioning_bus_id(stable_path: str) -> str:
    canonical = canonical_serial_identifier(stable_path)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{_COMMISSIONING_PREFIX}{digest}"


def connection_inventory(
    *,
    node_id: str,
    topology: Any,
    serial_root: Path = RUNTIME_SERIAL_ROOT,
) -> dict[str, Any]:
    adapters = inventory_stable_adapters(serial_root)
    present_by_path = {item.stable_path: item for item in adapters}
    production_paths = {
        canonical_serial_identifier(binding.serial_device): binding
        for binding in topology.bindings
    }
    missing_production_paths = tuple(
        sorted(stable_path for stable_path in production_paths if stable_path not in present_by_path)
    )
    production_real_paths = {
        adapter.real_path
        for stable_path in production_paths
        if (adapter := present_by_path.get(stable_path)) is not None
    }
    connections: list[dict[str, Any]] = []
    for binding in topology.bindings:
        stable_path = canonical_serial_identifier(binding.serial_device)
        adapter = present_by_path.get(stable_path)
        connections.append(
            {
                "bus_id": binding.bus_id,
                "stable_transport_identifier": stable_path,
                "ownership": "production_bus",
                "present": adapter is not None,
                "available_for_preflight": adapter is not None,
                "serial": {
                    "baudrate": binding.baudrate,
                    "parity": binding.parity,
                    "stopbits": binding.stopbits,
                    "timeout_seconds": binding.timeout_seconds,
                    "retries": binding.retries,
                },
            }
        )
    for adapter in adapters:
        if adapter.stable_path in production_paths or adapter.real_path in production_real_paths:
            continue
        connections.append(
            {
                "bus_id": commissioning_bus_id(adapter.stable_path),
                "stable_transport_identifier": adapter.stable_path,
                "ownership": "available_commissioning",
                "present": True,
                "available_for_preflight": not missing_production_paths,
                "serial": None,
            }
        )
    return {"schema_version": 1, "node_id": node_id, "connections": connections}


def resolve_commissioning_adapter(
    bus_id: str,
    *,
    topology: Any,
    serial_root: Path = RUNTIME_SERIAL_ROOT,
) -> StableSerialAdapter:
    if not bus_id.startswith(_COMMISSIONING_PREFIX):
        raise ValueError(f"Unknown commissioning RS-485 bus_id: {bus_id}")
    adapters = inventory_stable_adapters(serial_root)
    present_by_path = {item.stable_path: item for item in adapters}
    production_paths = {
        canonical_serial_identifier(binding.serial_device)
        for binding in topology.bindings
    }
    missing_production_paths = tuple(
        sorted(stable_path for stable_path in production_paths if stable_path not in present_by_path)
    )
    if missing_production_paths:
        raise ValueError(
            "Commissioning adapter ownership is ambiguous because a production RS-485 adapter is missing: "
            + ", ".join(missing_production_paths)
        )
    production_real_paths = {
        adapter.real_path
        for stable_path in production_paths
        if (adapter := present_by_path.get(stable_path)) is not None
    }
    matches = [
        adapter
        for adapter in adapters
        if commissioning_bus_id(adapter.stable_path) == bus_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Commissioning RS-485 adapter {bus_id} is unavailable or ambiguous")
    adapter = matches[0]
    if adapter.stable_path in production_paths or adapter.real_path in production_real_paths:
        raise ValueError("Refusing temporary commissioning access to a production-owned RS-485 adapter")
    return adapter


def _canonical_path(root: Path, name: str) -> str:
    if root in {RUNTIME_SERIAL_ROOT, HOST_SERIAL_ROOT}:
        return str(HOST_SERIAL_ROOT / name)
    return str(root / name)
