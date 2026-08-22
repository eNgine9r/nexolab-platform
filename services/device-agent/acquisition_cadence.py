from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

CADENCE_PRESETS_SECONDS = (10, 30, 60)
CADENCE_MIN_SECONDS = 10.0
CADENCE_MAX_SECONDS = 3600.0
SUPPORTED_DEVICE_FAMILIES = frozenset({"xjp60d", "le01mp"})


@dataclass(frozen=True)
class FamilyCadenceDefault:
    bus_id: str
    device_family: str
    interval_seconds: float


@dataclass(frozen=True)
class DeviceCadenceOverride:
    device_id: str
    interval_seconds: float


@dataclass(frozen=True)
class CadencePolicy:
    family_defaults: tuple[FamilyCadenceDefault, ...]
    device_overrides: tuple[DeviceCadenceOverride, ...]


@dataclass(frozen=True)
class FamilyCadenceMutation:
    bus_id: str
    device_family: str
    interval_seconds: float


@dataclass(frozen=True)
class DeviceCadenceMutation:
    device_id: str
    interval_seconds: float | None


@dataclass(frozen=True)
class CadenceMutation:
    family_defaults: tuple[FamilyCadenceMutation, ...]
    device_overrides: tuple[DeviceCadenceMutation, ...]


def _interval(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    resolved = float(value)
    if not CADENCE_MIN_SECONDS <= resolved <= CADENCE_MAX_SECONDS:
        raise ValueError(
            f"{label} must be between {int(CADENCE_MIN_SECONDS)} and "
            f"{int(CADENCE_MAX_SECONDS)} seconds"
        )
    return resolved


def _legacy_interval(
    name: str,
    default: float,
    *,
    environ: Mapping[str, str],
) -> float:
    raw = environ.get(name, "").strip()
    value = default if not raw else float(raw)
    if not 1.0 <= value <= CADENCE_MAX_SECONDS:
        raise ValueError(f"{name} must be between 1 and 3600 seconds")
    return value


def legacy_priority_intervals(
    legacy_interval_seconds: float,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[float, float, float]:
    source = os.environ if environ is None else environ
    high = _legacy_interval(
        "ACQUISITION_HIGH_INTERVAL_SECONDS",
        max(5.0, legacy_interval_seconds),
        environ=source,
    )
    medium = _legacy_interval(
        "ACQUISITION_MEDIUM_INTERVAL_SECONDS",
        max(10.0, high),
        environ=source,
    )
    low = _legacy_interval(
        "ACQUISITION_LOW_INTERVAL_SECONDS",
        max(30.0, medium),
        environ=source,
    )
    if not high <= medium <= low:
        raise ValueError("Adaptive intervals must satisfy high <= medium <= low")
    return high, medium, low


def build_bootstrap_policy(
    *,
    legacy_interval_seconds: float,
    bus_family_keys: Iterable[tuple[str, str]],
    environ: Mapping[str, str] | None = None,
) -> CadencePolicy:
    high, _medium, low = legacy_priority_intervals(
        legacy_interval_seconds,
        environ=environ,
    )
    defaults: list[FamilyCadenceDefault] = []
    for bus_id, family in sorted(set(bus_family_keys)):
        if family not in SUPPORTED_DEVICE_FAMILIES:
            raise ValueError(f"Unsupported cadence device family: {family}")
        # Migration must never accelerate the old priority policy. XJP60D was
        # high-priority, so the new 10-second product floor can only slow it.
        # LE-01MP previously mixed medium and low targets; one device-scoped
        # cadence therefore inherits the slowest previous class to avoid a
        # silent increase in physical request rate.
        interval = max(
            CADENCE_MIN_SECONDS,
            high if family == "xjp60d" else low,
        )
        defaults.append(
            FamilyCadenceDefault(
                bus_id=bus_id,
                device_family=family,
                interval_seconds=min(CADENCE_MAX_SECONDS, interval),
            )
        )
    return CadencePolicy(tuple(defaults), ())


def cadence_to_payload(policy: CadencePolicy) -> dict[str, Any]:
    return {
        "presets_seconds": list(CADENCE_PRESETS_SECONDS),
        "custom_min_seconds": int(CADENCE_MIN_SECONDS),
        "maximum_seconds": int(CADENCE_MAX_SECONDS),
        "family_defaults": [asdict(item) for item in policy.family_defaults],
        "device_overrides": [asdict(item) for item in policy.device_overrides],
    }


def cadence_from_payload(payload: object) -> CadencePolicy:
    if not isinstance(payload, dict):
        raise ValueError("cadence must be an object")
    raw_defaults = payload.get("family_defaults", [])
    raw_overrides = payload.get("device_overrides", [])
    if not isinstance(raw_defaults, list) or not isinstance(raw_overrides, list):
        raise ValueError("cadence family_defaults and device_overrides must be arrays")

    defaults: list[FamilyCadenceDefault] = []
    for index, item in enumerate(raw_defaults):
        if not isinstance(item, dict):
            raise ValueError(f"cadence.family_defaults[{index}] must be an object")
        bus_id = item.get("bus_id")
        family = item.get("device_family")
        if not isinstance(bus_id, str) or not bus_id.strip():
            raise ValueError(f"cadence.family_defaults[{index}].bus_id is required")
        if not isinstance(family, str) or family not in SUPPORTED_DEVICE_FAMILIES:
            raise ValueError(
                f"cadence.family_defaults[{index}].device_family is invalid"
            )
        defaults.append(
            FamilyCadenceDefault(
                bus_id=bus_id.strip(),
                device_family=family,
                interval_seconds=_interval(
                    item.get("interval_seconds"),
                    label=f"cadence.family_defaults[{index}].interval_seconds",
                ),
            )
        )

    overrides: list[DeviceCadenceOverride] = []
    for index, item in enumerate(raw_overrides):
        if not isinstance(item, dict):
            raise ValueError(f"cadence.device_overrides[{index}] must be an object")
        device_id = item.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError(f"cadence.device_overrides[{index}].device_id is required")
        overrides.append(
            DeviceCadenceOverride(
                device_id=device_id.strip(),
                interval_seconds=_interval(
                    item.get("interval_seconds"),
                    label=f"cadence.device_overrides[{index}].interval_seconds",
                ),
            )
        )
    return CadencePolicy(tuple(defaults), tuple(overrides))


def validate_policy(
    policy: CadencePolicy,
    *,
    bus_ids: Iterable[str],
    devices: Iterable[object],
) -> CadencePolicy:
    known_buses = set(bus_ids)
    device_rows = tuple(devices)
    device_by_id = {str(getattr(item, "device_id")): item for item in device_rows}
    required_keys = {
        (str(getattr(item, "bus_id")), str(getattr(item, "device_family")))
        for item in device_rows
    }

    defaults: dict[tuple[str, str], FamilyCadenceDefault] = {}
    for item in policy.family_defaults:
        key = (item.bus_id, item.device_family)
        if key in defaults:
            raise ValueError(f"Duplicate cadence family default: {item.bus_id}/{item.device_family}")
        if item.bus_id not in known_buses:
            raise ValueError(f"Cadence default references unknown bus: {item.bus_id}")
        if item.device_family not in SUPPORTED_DEVICE_FAMILIES:
            raise ValueError(f"Unsupported cadence device family: {item.device_family}")
        _interval(item.interval_seconds, label="cadence family default")
        defaults[key] = item

    missing = sorted(required_keys - set(defaults))
    if missing:
        rendered = ", ".join(f"{bus}/{family}" for bus, family in missing)
        raise ValueError(f"Missing cadence family defaults: {rendered}")

    overrides: set[str] = set()
    for item in policy.device_overrides:
        if item.device_id in overrides:
            raise ValueError(f"Duplicate cadence device override: {item.device_id}")
        if item.device_id not in device_by_id:
            raise ValueError(f"Cadence override references unknown device: {item.device_id}")
        _interval(item.interval_seconds, label="cadence device override")
        overrides.add(item.device_id)
    return policy


def family_default_interval(
    policy: CadencePolicy,
    *,
    bus_id: str,
    device_family: str,
) -> float:
    for item in policy.family_defaults:
        if item.bus_id == bus_id and item.device_family == device_family:
            return item.interval_seconds
    raise ValueError(f"Missing cadence family default: {bus_id}/{device_family}")


def effective_interval(
    policy: CadencePolicy,
    *,
    device_id: str,
    bus_id: str,
    device_family: str,
) -> tuple[float, str]:
    for item in policy.device_overrides:
        if item.device_id == device_id:
            return item.interval_seconds, "device_override"
    return (
        family_default_interval(
            policy,
            bus_id=bus_id,
            device_family=device_family,
        ),
        "family_default",
    )


def apply_mutation(
    policy: CadencePolicy,
    mutation: CadenceMutation,
    *,
    bus_ids: Iterable[str],
    devices: Iterable[object],
) -> tuple[CadencePolicy, list[dict[str, str]], set[str]]:
    device_rows = tuple(devices)
    device_by_id = {str(getattr(item, "device_id")): item for item in device_rows}
    known_buses = set(bus_ids)
    defaults = {
        (item.bus_id, item.device_family): item for item in policy.family_defaults
    }
    overrides = {item.device_id: item for item in policy.device_overrides}
    changes: list[dict[str, str]] = []
    affected_devices: set[str] = set()

    family_keys = [(item.bus_id, item.device_family) for item in mutation.family_defaults]
    if len(family_keys) != len(set(family_keys)):
        raise ValueError("Duplicate cadence family mutation")
    device_ids = [item.device_id for item in mutation.device_overrides]
    if len(device_ids) != len(set(device_ids)):
        raise ValueError("Duplicate cadence device mutation")

    for item in mutation.family_defaults:
        if item.bus_id not in known_buses:
            raise ValueError(f"Cadence mutation references unknown bus: {item.bus_id}")
        if item.device_family not in SUPPORTED_DEVICE_FAMILIES:
            raise ValueError(f"Unsupported cadence device family: {item.device_family}")
        interval = _interval(item.interval_seconds, label="cadence family interval")
        key = (item.bus_id, item.device_family)
        current = defaults.get(key)
        if current is None:
            raise ValueError(f"Unknown cadence family default: {item.bus_id}/{item.device_family}")
        if current.interval_seconds == interval:
            continue
        defaults[key] = FamilyCadenceDefault(item.bus_id, item.device_family, interval)
        changes.append(
            {
                "entity": "cadence_family_default",
                "id": f"{item.bus_id}/{item.device_family}",
                "from": str(current.interval_seconds),
                "to": str(interval),
            }
        )
        for device in device_rows:
            if (
                str(getattr(device, "bus_id")) == item.bus_id
                and str(getattr(device, "device_family")) == item.device_family
                and str(getattr(device, "device_id")) not in overrides
            ):
                affected_devices.add(str(getattr(device, "device_id")))

    for item in mutation.device_overrides:
        device = device_by_id.get(item.device_id)
        if device is None:
            raise ValueError(f"Cadence mutation references unknown device: {item.device_id}")
        current = overrides.get(item.device_id)
        if item.interval_seconds is None:
            if current is None:
                continue
            del overrides[item.device_id]
            inherited = family_default_interval(
                CadencePolicy(tuple(defaults.values()), tuple(overrides.values())),
                bus_id=str(getattr(device, "bus_id")),
                device_family=str(getattr(device, "device_family")),
            )
            changes.append(
                {
                    "entity": "cadence_device_override",
                    "id": item.device_id,
                    "from": str(current.interval_seconds),
                    "to": f"inherited:{inherited}",
                }
            )
            affected_devices.add(item.device_id)
            continue
        interval = _interval(item.interval_seconds, label="cadence device interval")
        if current is not None and current.interval_seconds == interval:
            continue
        overrides[item.device_id] = DeviceCadenceOverride(item.device_id, interval)
        inherited = family_default_interval(
            CadencePolicy(tuple(defaults.values()), tuple(overrides.values())),
            bus_id=str(getattr(device, "bus_id")),
            device_family=str(getattr(device, "device_family")),
        )
        changes.append(
            {
                "entity": "cadence_device_override",
                "id": item.device_id,
                "from": str(current.interval_seconds) if current is not None else f"inherited:{inherited}",
                "to": str(interval),
            }
        )
        affected_devices.add(item.device_id)

    if not changes:
        raise ValueError("Cadence mutation does not change effective policy")
    updated = CadencePolicy(
        tuple(sorted(defaults.values(), key=lambda item: (item.bus_id, item.device_family))),
        tuple(sorted(overrides.values(), key=lambda item: item.device_id)),
    )
    validate_policy(updated, bus_ids=known_buses, devices=device_rows)
    return updated, changes, affected_devices


def parse_cadence_mutation(
    payload: dict[str, Any],
) -> tuple[int, str, CadenceMutation]:
    expected_revision = payload.get("expected_revision")
    reason = payload.get("reason")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        raise ValueError("expected_revision must be a positive integer")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    raw_defaults = payload.get("family_defaults", [])
    raw_overrides = payload.get("device_overrides", [])
    if not isinstance(raw_defaults, list) or not isinstance(raw_overrides, list):
        raise ValueError("family_defaults and device_overrides must be arrays")
    if len(raw_defaults) + len(raw_overrides) > 200:
        raise ValueError("Cadence mutation is too large")

    defaults: list[FamilyCadenceMutation] = []
    for index, item in enumerate(raw_defaults):
        if not isinstance(item, dict):
            raise ValueError(f"family_defaults[{index}] must be an object")
        bus_id = item.get("bus_id")
        family = item.get("device_family")
        if not isinstance(bus_id, str) or not bus_id.strip():
            raise ValueError(f"family_defaults[{index}].bus_id is required")
        if not isinstance(family, str) or family not in SUPPORTED_DEVICE_FAMILIES:
            raise ValueError(f"family_defaults[{index}].device_family is invalid")
        defaults.append(
            FamilyCadenceMutation(
                bus_id=bus_id.strip(),
                device_family=family,
                interval_seconds=_interval(
                    item.get("interval_seconds"),
                    label=f"family_defaults[{index}].interval_seconds",
                ),
            )
        )

    overrides: list[DeviceCadenceMutation] = []
    for index, item in enumerate(raw_overrides):
        if not isinstance(item, dict):
            raise ValueError(f"device_overrides[{index}] must be an object")
        device_id = item.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError(f"device_overrides[{index}].device_id is required")
        raw_interval = item.get("interval_seconds")
        overrides.append(
            DeviceCadenceMutation(
                device_id=device_id.strip(),
                interval_seconds=(
                    None
                    if raw_interval is None
                    else _interval(
                        raw_interval,
                        label=f"device_overrides[{index}].interval_seconds",
                    )
                ),
            )
        )

    if not defaults and not overrides:
        raise ValueError("Cadence mutation requires at least one change")
    return expected_revision, reason.strip(), CadenceMutation(tuple(defaults), tuple(overrides))


def ensure_defaults_for_devices(
    policy: CadencePolicy,
    devices: Iterable[object],
) -> CadencePolicy:
    rows = tuple(devices)
    defaults = {
        (item.bus_id, item.device_family): item for item in policy.family_defaults
    }
    by_family: dict[str, set[float]] = {}
    for item in policy.family_defaults:
        by_family.setdefault(item.device_family, set()).add(item.interval_seconds)

    for device in rows:
        bus_id = str(getattr(device, "bus_id"))
        family = str(getattr(device, "device_family"))
        key = (bus_id, family)
        if key in defaults:
            continue
        family_values = by_family.get(family, set())
        if len(family_values) == 1:
            interval = next(iter(family_values))
        elif not family_values:
            interval = float(CADENCE_PRESETS_SECONDS[-1])
        else:
            raise ValueError(
                f"Cannot infer cadence default for {bus_id}/{family} from conflicting family defaults"
            )
        defaults[key] = FamilyCadenceDefault(bus_id, family, interval)
        by_family.setdefault(family, set()).add(interval)

    return CadencePolicy(
        tuple(sorted(defaults.values(), key=lambda item: (item.bus_id, item.device_family))),
        policy.device_overrides,
    )


def rebind_policy(
    policy: CadencePolicy,
    *,
    old_devices: Iterable[object],
    new_devices: Iterable[object],
) -> CadencePolicy:
    old_by_id = {str(getattr(item, "device_id")): item for item in old_devices}
    new_rows = tuple(new_devices)
    defaults: dict[tuple[str, str], FamilyCadenceDefault] = {}

    for device in new_rows:
        device_id = str(getattr(device, "device_id"))
        bus_id = str(getattr(device, "bus_id"))
        family = str(getattr(device, "device_family"))
        key = (bus_id, family)
        if key in defaults:
            continue
        old = old_by_id.get(device_id)
        candidate_values: set[float] = set()
        if old is not None:
            try:
                candidate_values.add(
                    family_default_interval(
                        policy,
                        bus_id=str(getattr(old, "bus_id")),
                        device_family=family,
                    )
                )
            except ValueError:
                pass
        if not candidate_values:
            candidate_values = {
                item.interval_seconds
                for item in policy.family_defaults
                if item.device_family == family
            }
        if len(candidate_values) != 1:
            raise ValueError(
                f"Cannot deterministically rebind cadence default for {bus_id}/{family}"
            )
        defaults[key] = FamilyCadenceDefault(bus_id, family, next(iter(candidate_values)))

    rebound = CadencePolicy(
        tuple(sorted(defaults.values(), key=lambda item: (item.bus_id, item.device_family))),
        policy.device_overrides,
    )
    return rebound
