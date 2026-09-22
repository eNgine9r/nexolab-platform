from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Protocol

PROFILE_VERSION = "eastron-sdm120m-fc04-v1"


class InputRegisterReader(Protocol):
    def read_input_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]: ...


@dataclass(frozen=True)
class SDM120Register:
    key: str
    address: int
    metric: str
    unit: str
    decimals: int
    count: int = 2
    @property
    def addresses(self) -> tuple[int, ...]:
        return tuple(range(self.address, self.address + self.count))


REGISTERS: tuple[SDM120Register, ...] = (
    SDM120Register("voltage", 0x0000, "electrical.voltage", "V", 1),
    SDM120Register("current", 0x0006, "electrical.current", "A", 3),
    SDM120Register("active_power", 0x000C, "electrical.power.active", "W", 1),
    SDM120Register("apparent_power", 0x0012, "electrical.power.apparent", "VA", 1),
    SDM120Register("reactive_power", 0x0018, "electrical.power.reactive", "var", 1),
    SDM120Register("power_factor", 0x001E, "electrical.power_factor", "ratio", 3),
    SDM120Register("frequency", 0x0046, "electrical.frequency", "Hz", 2),
    SDM120Register("import_active_energy", 0x0048, "electrical.energy.active", "kWh", 3),
)
REGISTER_BY_KEY = {register.key: register for register in REGISTERS}


@dataclass(frozen=True)
class SDM120Reading:
    unit_id: int
    key: str
    address: int
    metric: str
    raw_value: int
    value: float
    unit: str
    quality: str = "valid"


def decode_float32_words(raw_values: tuple[int, ...]) -> tuple[int, float]:
    if len(raw_values) != 2:
        raise ValueError(f"SDM120 Float32 expects 2 register words, got {len(raw_values)}")
    if any(not 0 <= value <= 0xFFFF for value in raw_values):
        raise ValueError(f"SDM120 register words must be uint16: {raw_values!r}")
    high_word, low_word = raw_values
    raw_value = (high_word << 16) | low_word
    value = struct.unpack(">f", struct.pack(">HH", high_word, low_word))[0]
    if not math.isfinite(value):
        raise ValueError("SDM120 Float32 value must be finite")
    return raw_value, value


def decode_registers(
    unit_id: int,
    register: SDM120Register,
    raw_values: tuple[int, ...],
) -> SDM120Reading:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit ID must be 1..247, got {unit_id}")
    if len(raw_values) != register.count:
        raise ValueError(
            f"{register.key} expects {register.count} register words, got {len(raw_values)}"
        )
    raw_value, numeric = decode_float32_words(raw_values)
    return SDM120Reading(
        unit_id=unit_id,
        key=register.key,
        address=register.address,
        metric=register.metric,
        raw_value=raw_value,
        value=round(numeric, register.decimals),
        unit=register.unit,
    )


class SDM120Reader:
    def __init__(self, client: InputRegisterReader) -> None:
        self.client = client

    def read_metric(self, unit_id: int, key: str) -> SDM120Reading:
        try:
            register = REGISTER_BY_KEY[key]
        except KeyError as exc:
            raise ValueError(f"Unknown SDM120 metric key: {key}") from exc
        raw_values = self.client.read_input_registers(
            unit_id,
            register.address,
            register.count,
        )
        return decode_registers(unit_id, register, raw_values)
