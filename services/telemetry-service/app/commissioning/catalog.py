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
    activation_supported: bool = True


# Repository-owned mirror of the accepted Device Agent read-only profile
# identities. Commissioning never imports or invokes Device Agent runtime code.
SUPPORTED_DEVICE_PROFILES: tuple[SupportedDeviceProfile, ...] = (
    SupportedDeviceProfile(
        id="waveshare-8ai-b-v3", version="waveshare-modbus-rtu-analog-input-8ch-b-v3-readonly-v1",
        device_family="waveshare_8ai", device_class="analog-input", manufacturer="Waveshare",
        models=("Modbus RTU Analog Input 8CH (B) V3",), display_name="Waveshare Analog Input 8CH (B) V3",
        transport_kind="modbus_rtu", capability_status="repository_supported",
        evidence_note="Read-only FC03 mode and FC04 channel data; connected sensor and calibration are not inferred.",
    ),
    SupportedDeviceProfile(
        id="eastron-sdm120m",
        version="eastron-sdm120m-fc04-v1",
        device_family="sdm120",
        device_class="energy-meter",
        manufacturer="Eastron",
        models=("SDM120M",),
        display_name="Eastron SDM120M",
        transport_kind="modbus_rtu",
        capability_status="repository_supported",
        evidence_note="FC04 read-only preflight; live evidence is required for activation.",
    ),
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
    SupportedDeviceProfile(
        id="danfoss-ak-cc25-pro",
        version="danfoss-ak-cc25-pro-sw1.3x-fc03-v1",
        device_family="akcc25",
        device_class="temperature-controller",
        manufacturer="Danfoss",
        models=("AK-CC25 Pro",),
        display_name="Danfoss AK-CC25 Pro",
        transport_kind="modbus_rtu",
        capability_status="repository_supported_hardware_evidenced",
        evidence_note=(
            "Real Unit 35 FC03 discovery is hardware-evidenced at 9600 8E1; "
            "production activation and temperature engineering semantics remain disabled."
        ),
        activation_supported=False,
    ),
)

def section_probe_count(profile_id: str | None) -> int | None:
    prefix = "dixell-xjp60d-sections-"
    if not profile_id or not profile_id.startswith(prefix):
        return None
    value = profile_id.removeprefix(prefix)
    return int(value) if value in {str(i) for i in range(1, 7)} else None


def profile_unit_ids(profile_id: str | None, base: int) -> range:
    if section_probe_count(profile_id) is not None:
        if not 1 <= base <= 242:
            raise ValueError("Six section addresses must fit within 1..247")
        return range(base, base + 6)
    return range(base, base + 1)


SUPPORTED_DEVICE_PROFILES += tuple(
    SupportedDeviceProfile(
        id=f"dixell-xjp60d-sections-{count}", version=f"dixell-xjp60d-sections-v1-{count}",
        device_family="xjp60d", device_class="temperature-controller", manufacturer="Dixell", models=("XJP60D",),
        display_name=f"Dixell XJP60D · секції · {count} датчиків", transport_kind="modbus_rtu",
        capability_status="repository_supported_hardware_evidenced",
        evidence_note="Six consecutive section addresses, FC03 256/257 per section; attached count is operator supplied. Other inputs stay reserve.",
    ) for count in range(1, 7)
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
        if section_probe_count(profile.id) is None
        and _key(profile.manufacturer) == manufacturer_key
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
