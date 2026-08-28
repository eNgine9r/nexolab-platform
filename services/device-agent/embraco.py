from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class HoldingRegisterReader(Protocol):
    def read_holding_register(self, unit_id: int, address: int) -> int: ...


PROFILE_VERSION = "embraco-sync-fc03-v1.00.04"


@dataclass(frozen=True)
class EmbracoRegister:
    key: str
    address: int
    metric: str
    unit: str
    engineering_scale: str | None = None


REGISTERS: tuple[EmbracoRegister, ...] = (
    EmbracoRegister("hysteresis", 0, "refrigeration.hysteresis", "degC", "control"),
    EmbracoRegister("setpoint", 1, "refrigeration.setpoint", "degC", "control"),
    EmbracoRegister("cabinet_temperature", 2, "temperature.cabinet", "degC", "temperature"),
    EmbracoRegister("evaporator_temperature", 3, "temperature.evaporator", "degC", "temperature"),
    EmbracoRegister("condenser_temperature", 4, "temperature.condenser", "degC", "temperature"),
    EmbracoRegister("ambient_temperature", 5, "temperature.ambient", "degC", "temperature"),
    EmbracoRegister("door_temperature", 6, "temperature.door", "degC", "temperature"),
    EmbracoRegister("auxiliary_temperature", 7, "temperature.auxiliary", "degC", "temperature"),
    EmbracoRegister("evaporator_2_temperature", 8, "temperature.evaporator_2", "degC", "temperature"),
    EmbracoRegister("control_state", 9, "refrigeration.control_state", "state"),
    EmbracoRegister("relay_state_bits", 10, "controller.relay_state_bits", "bitfield"),
    EmbracoRegister("compressor_speed", 11, "compressor.speed", "rpm"),
    EmbracoRegister("alarm_state_bits", 12, "controller.alarm_state_bits", "bitfield"),
)
REGISTER_BY_KEY = {item.key: item for item in REGISTERS}
CONTROL_STATES = {
    0: "idle",
    1: "cooling",
    2: "prepare_defrost",
    3: "defrost",
    4: "post_defrost",
    5: "pulldown",
}
RELAY_BITS = {0: "relay_1", 1: "relay_2", 2: "relay_3", 3: "relay_4"}
ALARM_BITS = {
    1: "high_cabinet_temperature",
    2: "low_cabinet_temperature",
    3: "high_condenser_temperature",
    4: "low_cooling_capacity",
    5: "external_alarm",
    6: "open_door",
    7: "faulty_temperature_probe",
    8: "faulty_inverter_communication",
    9: "defrost_incomplete",
    10: "rtc_not_configured",
    11: "high_auxiliary_temperature",
    12: "low_auxiliary_temperature",
}


@dataclass(frozen=True)
class EmbracoReading:
    unit_id: int
    key: str
    address: int
    metric: str
    raw_value: int
    value: float | None
    unit: str
    quality: str
    semantic: str | None = None


def signed_int16(value: int) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {value}")
    return value - 0x10000 if value & 0x8000 else value


def active_bits(value: int, mapping: dict[int, str]) -> tuple[str, ...]:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {value}")
    return tuple(name for bit, name in mapping.items() if value & (1 << bit))


def decode_register(
    unit_id: int,
    register: EmbracoRegister,
    raw_value: int,
    *,
    temperature_scale: float | None = None,
    control_scale: float | None = None,
) -> EmbracoReading:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit ID must be 1..247, got {unit_id}")
    numeric = signed_int16(raw_value)

    if register.engineering_scale == "temperature":
        if temperature_scale is None:
            value, quality = None, "unknown"
        else:
            if temperature_scale <= 0:
                raise ValueError("temperature_scale must be positive")
            value, quality = numeric * temperature_scale, "valid"
    elif register.engineering_scale == "control":
        if control_scale is None:
            value, quality = None, "unknown"
        else:
            if control_scale <= 0:
                raise ValueError("control_scale must be positive")
            value, quality = numeric * control_scale, "valid"
    elif register.key == "control_state":
        value = float(raw_value) if raw_value in CONTROL_STATES else None
        quality = "valid" if value is not None else "unknown"
    elif register.key == "compressor_speed":
        value = float(numeric) if numeric >= 0 else None
        quality = "valid" if value is not None else "unknown"
    else:
        value, quality = float(raw_value), "valid"

    semantic = CONTROL_STATES.get(raw_value) if register.key == "control_state" else None
    return EmbracoReading(
        unit_id=unit_id,
        key=register.key,
        address=register.address,
        metric=register.metric,
        raw_value=raw_value,
        value=value,
        unit=register.unit,
        quality=quality,
        semantic=semantic,
    )


class EmbracoSyncReader:
    """Strict FC03-only reader for the verified Embraco Sync v1.00.04 map."""

    def __init__(
        self,
        client: HoldingRegisterReader,
        *,
        temperature_scale: float | None = None,
        control_scale: float | None = None,
    ) -> None:
        if temperature_scale is not None and temperature_scale <= 0:
            raise ValueError("temperature_scale must be positive")
        if control_scale is not None and control_scale <= 0:
            raise ValueError("control_scale must be positive")
        self.client = client
        self.temperature_scale = temperature_scale
        self.control_scale = control_scale

    def read_metric(self, unit_id: int, key: str) -> EmbracoReading:
        try:
            register = REGISTER_BY_KEY[key]
        except KeyError as exc:
            raise ValueError(f"Unknown Embraco Sync metric key: {key}") from exc
        raw_value = self.client.read_holding_register(unit_id, register.address)
        return decode_register(
            unit_id,
            register,
            raw_value,
            temperature_scale=self.temperature_scale,
            control_scale=self.control_scale,
        )
