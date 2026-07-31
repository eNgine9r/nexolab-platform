from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class HoldingRegisterReader(Protocol):
    def read_holding_register(self, unit_id: int, address: int) -> int: ...

    def read_holding_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]: ...


PROBE_REGISTERS: dict[int, tuple[int, int]] = {
    1: (256, 257),
    2: (258, 259),
    3: (260, 261),
    4: (262, 263),
    5: (264, 265),
    6: (266, 267),
}
PROBE_BLOCK_START = 256
PROBE_BLOCK_COUNT = 12
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


@dataclass(frozen=True)
class _Snapshot:
    captured_monotonic: float
    registers: tuple[int, ...] | None
    error: Exception | None


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
        # The telemetry contract reserves alarm for threshold states only.
        # Probe presence/fault information remains available through quality
        # and raw_status without producing schema-invalid dead letters.
        alarm = None
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
        snapshot_ttl_seconds: float = 1.0,
    ) -> None:
        if scale <= 0:
            raise ValueError("scale must be positive")
        if snapshot_ttl_seconds <= 0:
            raise ValueError("snapshot_ttl_seconds must be positive")
        self.client = client
        self.scale = scale
        self.unit = unit
        self.snapshot_ttl_seconds = snapshot_ttl_seconds
        self._snapshots: dict[int, _Snapshot] = {}

    def read_channel(self, unit_id: int, channel: int) -> XJP60DReading:
        if channel not in PROBE_REGISTERS:
            raise ValueError(f"XJP60D channel must be 1..6, got {channel}")
        registers = self._read_probe_block(unit_id)
        offset = (channel - 1) * 2
        return decode_reading(
            unit_id,
            channel,
            registers[offset],
            registers[offset + 1],
            scale=self.scale,
            unit=self.unit,
        )

    def read_all_channels(self, unit_id: int) -> tuple[XJP60DReading, ...]:
        registers = self._read_probe_block(unit_id)
        return tuple(
            decode_reading(
                unit_id,
                channel,
                registers[(channel - 1) * 2],
                registers[(channel - 1) * 2 + 1],
                scale=self.scale,
                unit=self.unit,
            )
            for channel in range(1, 7)
        )

    def invalidate(self, unit_id: int | None = None) -> None:
        if unit_id is None:
            self._snapshots.clear()
            return
        self._snapshots.pop(unit_id, None)

    def _read_probe_block(self, unit_id: int) -> tuple[int, ...]:
        now = time.monotonic()
        cached = self._snapshots.get(unit_id)
        if cached is not None and now - cached.captured_monotonic <= self.snapshot_ttl_seconds:
            if cached.error is not None:
                raise cached.error
            assert cached.registers is not None
            return cached.registers

        try:
            registers = self.client.read_holding_registers(
                unit_id,
                PROBE_BLOCK_START,
                PROBE_BLOCK_COUNT,
            )
            if len(registers) != PROBE_BLOCK_COUNT:
                raise RuntimeError(
                    f"XJP60D unit {unit_id} returned {len(registers)} registers; "
                    f"expected {PROBE_BLOCK_COUNT}"
                )
        except Exception as error:
            self._snapshots[unit_id] = _Snapshot(now, None, error)
            raise

        self._snapshots[unit_id] = _Snapshot(now, registers, None)
        return registers
