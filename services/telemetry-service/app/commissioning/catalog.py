from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupportedDeviceProfile:
    id: str
    version: str
    device_family: str
    device_class: str
    manufacturer: str
    models: tuple[str, ...]
    display_name: str
    transport_kind: str
    capability_status: str
    evidence_note: str
    read_only: bool = True


# Repository-owned mirror of the already accepted Device Agent FC03-only profile
# identities. Commissioning never imports or invokes Device Agent runtime code.
SUPPORTED_DEVICE_PROFILES: tuple[SupportedDeviceProfile, ...] = (
    SupportedDeviceProfile(
        id="dixell-xjp60d",
        version="dixell-xjp60d-fc03-v1",
        device_family="xjp60d",
        device_class="temperature-controller",
        manufacturer="Dixell",
        models=("XJP60D",),
        display_name="Dixell XJP60D",
        transport_kind="modbus_rtu",
        capability_status="repository_supported",
        evidence_note="Existing FC03 temperature-channel contract; physical portability remains device-specific.",
    ),
    SupportedDeviceProfile(
        id="f-and-f-le01mp",
        version="f-and-f-le01mp-fc03-v2",
        device_family="le01mp",
        device_class="energy-meter",
        manufacturer="F&F",
        models=("LE-01MP",),
        display_name="F&F LE-01MP",
        transport_kind="modbus_rtu",
        capability_status="repository_supported",
        evidence_note="Existing FC03 metering contract; controlled restart and rollover evidence remains separate.",
    ),
    SupportedDeviceProfile(
        id="embraco-sync",
        version="embraco-sync-fc03-v1.00.04",
        device_family="embraco",
        device_class="temperature-controller",
        manufacturer="Embraco",
        models=("Sync", "Embraco Sync"),
        display_name="Embraco Sync",
        transport_kind="modbus_rtu",
        capability_status="repository_supported_hardware_evidenced",
        evidence_note="Existing strict FC03-only Sync v1.00.04 contract; engineering temperature scale remains unverified.",
    ),
)

_PROFILES_BY_ID = {profile.id: profile for profile in SUPPORTED_DEVICE_PROFILES}


def supported_profile(profile_id: str | None) -> SupportedDeviceProfile | None:
    normalized = profile_id.strip() if profile_id is not None else ""
    return _PROFILES_BY_ID.get(normalized) if normalized else None


def resolve_supported_profile(
    *,
    profile_id: str | None,
    manufacturer: str,
    model: str,
) -> SupportedDeviceProfile | None:
    explicit = supported_profile(profile_id)
    if profile_id is not None and profile_id.strip():
        return explicit
    manufacturer_key = _key(manufacturer)
    model_key = _key(model)
    matches = [
        profile
        for profile in SUPPORTED_DEVICE_PROFILES
        if _key(profile.manufacturer) == manufacturer_key
        and model_key in {_key(item) for item in profile.models}
    ]
    return matches[0] if len(matches) == 1 else None


def profile_matches_identity(
    profile: SupportedDeviceProfile,
    *,
    device_class: str,
    manufacturer: str,
    model: str,
) -> bool:
    return (
        _key(profile.device_class) == _key(device_class)
        and _key(profile.manufacturer) == _key(manufacturer)
        and _key(model) in {_key(item) for item in profile.models}
    )


def _key(value: str) -> str:
    return " ".join(value.strip().lower().split())
