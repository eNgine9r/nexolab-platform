from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class HoldingRegisterReader(Protocol):
    def read_holding_register(self, unit_id: int, address: int) -> int: ...


@dataclass(frozen=True)
class LE01MPRegister:
    key: str
    address: int
    metric: str
    unit: str
    scale: float
    decimals: int
    signed: bool = False


REGISTERS: tuple[LE01MPRegister, ...] = (
    LE01MPRegister("voltage", 0, "electrical.voltage", "V", 0.1, 1),
    LE01MPRegister("current", 1, "electrical.current", "A", 0.1, 1),
    LE01MPRegister("frequency", 2, "electrical.frequency", "Hz", 0.1, 1),
    LE01MPRegister("active_power", 3, "electrical.power.active", "W", 1.0, 0),
    LE01MPRegister("reactive_power", 4, "electrical.power.reactive", "var", 1.0, 0),
    LE01MPRegister("apparent_power", 5, "electrical.power.apparent", "VA", 1.0, 0),
    LE01MPRegister("power_factor", 6, "electrical.power_factor", "ratio", 0.001, 3),
    LE01MPRegister(
        "internal_temperature",
        37,
        "temperature.internal",
        "degC",
        1.0,
        0,
        signed=True,
    ),
)
REGISTER_BY_KEY = {register.key: register for register in REGISTERS}


@dataclass(frozen=True)
class LE01MPReading:
    unit_id: int
    key: str
    address: int
    metric: str
    raw_value: int
    value: float
    unit: str
    quality: str = "valid"


def signed_int16(value: int) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {value}")
    return value - 0x10000 if value & 0x8000 else value


def decode_register(
    unit_id: int,
    register: LE01MPRegister,
    raw_value: int,
) -> LE01MPReading:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit ID must be 1..247, got {unit_id}")
    if not 0 <= raw_value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {raw_value}")

    numeric = signed_int16(raw_value) if register.signed else raw_value
    value = round(numeric * register.scale, register.decimals)
    return LE01MPReading(
        unit_id=unit_id,
        key=register.key,
        address=register.address,
        metric=register.metric,
        raw_value=raw_value,
        value=value,
        unit=register.unit,
    )


class LE01MPReader:
    def __init__(self, client: HoldingRegisterReader) -> None:
        self.client = client

    def read_metric(self, unit_id: int, key: str) -> LE01MPReading:
        try:
            register = REGISTER_BY_KEY[key]
        except KeyError as exc:
            raise ValueError(f"Unknown LE-01MP metric key: {key}") from exc

        raw_value = self.client.read_holding_register(unit_id, register.address)
        return decode_register(unit_id, register, raw_value)
