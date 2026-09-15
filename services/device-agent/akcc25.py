from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class HoldingRegisterReader(Protocol):
    def read_holding_register(self, unit_id: int, address: int) -> int: ...


PROFILE_VERSION = "danfoss-ak-cc25-pro-sw1.3x-fc03-v1"


@dataclass(frozen=True)
class AKCC25ProRegister:
    key: str
    code: str
    adu_address: int
    metric: str
    unit: str
    minimum: int
    maximum: int
    binary: bool = False
    signed: bool = False
    source_access: str = "R"

    @property
    def address(self) -> int:
        """Zero-based Modbus PDU address derived from Danfoss one-based Modbus ADU."""
        return self.adu_address - 1


REGISTERS: tuple[AKCC25ProRegister, ...] = (
    AKCC25ProRegister("control_state", "u00", 2007, "refrigeration.control_state", "state", 0, 55),
    AKCC25ProRegister("compressor_state", "u58", 2510, "compressor.state", "state", 0, 1, True),
    AKCC25ProRegister("compressor_speed", "u52", 2685, "compressor.speed", "%", 0, 100),
    AKCC25ProRegister("fan_state", "u59", 2511, "fan.evaporator.state", "state", 0, 1, True),
    AKCC25ProRegister("defrost_state", "u60", 2512, "defrost.state", "state", 0, 1, True),
    AKCC25ProRegister("network_status", "U45", 2682, "controller.network_status", "%", 0, 100),
    AKCC25ProRegister("alarm_status", "x16", 2541, "controller.alarm_state", "state", 0, 1, True),
    AKCC25ProRegister("network_address", "o03", 2008, "controller.network_address", "address", -1, 240, signed=True, source_access="RW"),
    AKCC25ProRegister("baudrate_setting", "oa1", 2251, "controller.serial_baudrate_setting", "enum", 1, 5, source_access="RW"),
    AKCC25ProRegister("parity_setting", "oa2", 2255, "controller.serial_parity_setting", "enum", 0, 2, source_access="RW"),
)
REGISTER_BY_KEY = {item.key: item for item in REGISTERS}

SETTING_SEMANTICS = {
    "baudrate_setting": {1: "auto", 2: "9600", 3: "19200", 4: "38400", 5: "115200"},
    "parity_setting": {0: "none", 1: "even", 2: "odd"},
}


CONTROL_STATES = {
    0: "normal_control",
    1: "hold_after_defrost",
    2: "minimum_on_timer",
    3: "minimum_off_timer",
    4: "drip_off",
    10: "main_switch_off",
    11: "thermostat_cut_out",
    12: "frost_protection_s4",
    14: "defrost",
    15: "fan_delay",
    17: "door_open",
    18: "melt_period",
    19: "modulating_temperature_control",
    20: "emergency_control",
    25: "manual_control",
    29: "case_cleaning",
    30: "forced_cooling",
    32: "power_up_delay",
    33: "air_heating",
    34: "compressor_safety_cut_out",
    41: "high_condenser_temperature",
    45: "controller_shutdown",
    50: "high_s7_brine_inlet",
    51: "oil_recovery",
    52: "temperature_pulldown",
    53: "compressor_lockout",
    54: "leak_action",
    55: "wrong_io_configuration",
}


@dataclass(frozen=True)
class AKCC25ProReading:
    unit_id: int
    key: str
    code: str
    address: int
    adu_address: int
    metric: str
    raw_value: int
    value: float | None
    unit: str
    quality: str
    semantic: str | None = None


def decode_register(
    unit_id: int,
    register: AKCC25ProRegister,
    raw_value: int,
) -> AKCC25ProReading:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit ID must be 1..247, got {unit_id}")
    if not 0 <= raw_value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {raw_value}")

    numeric = raw_value - 0x10000 if register.signed and raw_value & 0x8000 else raw_value
    valid = register.minimum <= numeric <= register.maximum
    semantic: str | None = None
    if register.key == "control_state":
        semantic = CONTROL_STATES.get(numeric)
        valid = semantic is not None
    elif register.key in SETTING_SEMANTICS:
        semantic = SETTING_SEMANTICS[register.key].get(numeric)
        valid = semantic is not None
    elif register.binary and valid:
        semantic = "on" if numeric == 1 else "off"

    return AKCC25ProReading(
        unit_id=unit_id,
        key=register.key,
        code=register.code,
        address=register.address,
        adu_address=register.adu_address,
        metric=register.metric,
        raw_value=raw_value,
        value=float(numeric) if valid else None,
        unit=register.unit,
        quality="valid" if valid else "unknown",
        semantic=semantic,
    )


class AKCC25ProReader:
    """FC03-only reader for the documented AK-CC25 Pro SW 1.3x integer probe set.

    The discovery profile uses FC03 only. It includes a bounded integer service
    subset plus read-only observation of o03/oa1/oa2. Danfoss documents one-based
    Modbus ADU numbers; FC03 requests use the observed zero-based PDU address ADU-1.
    Decimal temperature values remain excluded from production semantics until display correlation.
    """

    def __init__(self, client: HoldingRegisterReader) -> None:
        self.client = client

    def read_metric(self, unit_id: int, key: str) -> AKCC25ProReading:
        try:
            register = REGISTER_BY_KEY[key]
        except KeyError as exc:
            raise ValueError(f"Unknown AK-CC25 Pro metric key: {key}") from exc
        raw_value = self.client.read_holding_register(unit_id, register.address)
        return decode_register(unit_id, register, raw_value)
