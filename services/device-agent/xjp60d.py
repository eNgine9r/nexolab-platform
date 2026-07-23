from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class HoldingRegisterReader(Protocol):
    def read_holding_register(self, unit_id: int, address: int) -> int: ...


PROBE_REGISTERS: dict[int, tuple[int, int]] = {
    1: (256, 257),
    2: (258, 259),
    3: (260, 261),
    4: (262, 263),
    5: (264, 265),
    6: (266, 267),
}

STATUS_MASK = 0x0003
STATUS_NAMES = {
    0: "normal",
    1: "low",
    2: "high",
    3: "probe_error",
}


@dataclass(frozen=True)
class XJP60DReading:
    unit_id: int
    channel: int
    raw_value: int
    raw_status: int
    value: float | None
    unit: str
    quality: str
    alarm: str | None


def signed_int16(value: int) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"uint16 value expected, got {value}")
    return value - 0x10000 if value & 0x8000 else value


def decode_reading(
    unit_id: int,
    channel: int,
    raw_value: int,
    raw_status: int,
    *,
    scale: float = 0.1,
    unit: str = "degC",
) -> XJP60DReading:
    if channel not in PROBE_REGISTERS:
        raise ValueError(f"XJP60D channel must be 1..6, got {channel}")
    if scale <= 0:
        raise ValueError("scale must be positive")

    status_code = raw_status & STATUS_MASK
    status = STATUS_NAMES[status_code]
    if status == "probe_error":
        value = None
        quality = "sensor_error"
        alarm = "probe_error"
    else:
        value = signed_int16(raw_value) * scale
        quality = "valid"
        alarm = None if status == "normal" else status

    return XJP60DReading(
        unit_id=unit_id,
        channel=channel,
        raw_value=raw_value,
        raw_status=raw_status,
        value=value,
        unit=unit,
        quality=quality,
        alarm=alarm,
    )


class XJP60DReader:
    def __init__(
        self,
        client: HoldingRegisterReader,
        *,
        scale: float = 0.1,
        unit: str = "degC",
    ) -> None:
        if scale <= 0:
            raise ValueError("scale must be positive")
        self.client = client
        self.scale = scale
        self.unit = unit

    def read_channel(self, unit_id: int, channel: int) -> XJP60DReading:
        try:
            value_address, status_address = PROBE_REGISTERS[channel]
        except KeyError as exc:
            raise ValueError(f"XJP60D channel must be 1..6, got {channel}") from exc

        raw_value = self.client.read_holding_register(unit_id, value_address)
        raw_status = self.client.read_holding_register(unit_id, status_address)
        return decode_reading(
            unit_id,
            channel,
            raw_value,
            raw_status,
            scale=self.scale,
            unit=self.unit,
        )
