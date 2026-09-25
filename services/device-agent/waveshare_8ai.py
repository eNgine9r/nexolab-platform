from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

PROFILE_VERSION = "waveshare-modbus-rtu-analog-input-8ch-b-v3-readonly-v1"
CHANNEL_COUNT = 8
INPUT_BASE_ADDRESS = 0x0000
MODE_BASE_ADDRESS = 0x1000


class AnalogRegisterReader(Protocol):
    def read_holding_registers(
        self, unit_id: int, address: int, count: int
    ) -> tuple[int, ...]: ...

    def read_input_registers(
        self, unit_id: int, address: int, count: int
    ) -> tuple[int, ...]: ...


@dataclass(frozen=True)
class WaveshareMode:
    code: int
    label: str
    metric: str
    unit: str


MODES: dict[int, WaveshareMode] = {
    0: WaveshareMode(0, "0-10V", "analog.voltage", "mV"),
    1: WaveshareMode(1, "2-10V", "analog.voltage", "mV"),
    2: WaveshareMode(2, "0-20mA", "analog.current", "uA"),
    3: WaveshareMode(3, "4-20mA", "analog.current", "uA"),
    4: WaveshareMode(4, "adc-code", "analog.adc_code", "count"),
}


@dataclass(frozen=True)
class Waveshare8AIReading:
    unit_id: int
    channel: int
    mode: int
    mode_label: str
    metric: str
    raw_value: int
    value: float
    unit: str
    quality: str = "valid"


def _validate_word(value: int, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError(f"{label} must be one uint16 register word")
    return value


def decode_channel(
    unit_id: int,
    channel: int,
    *,
    mode_word: int,
    input_word: int,
) -> Waveshare8AIReading:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit ID must be 1..247, got {unit_id}")
    if not 1 <= channel <= CHANNEL_COUNT:
        raise ValueError(f"Waveshare channel must be 1..{CHANNEL_COUNT}, got {channel}")
    mode_code = _validate_word(mode_word, label="Waveshare mode")
    raw_value = _validate_word(input_word, label="Waveshare input")
    try:
        mode = MODES[mode_code]
    except KeyError as exc:
        raise ValueError(f"Unsupported Waveshare input mode: {mode_code}") from exc
    return Waveshare8AIReading(
        unit_id=unit_id,
        channel=channel,
        mode=mode.code,
        mode_label=mode.label,
        metric=mode.metric,
        raw_value=raw_value,
        value=float(raw_value),
        unit=mode.unit,
    )


class Waveshare8AIReader:
    """Strict read-only reader for Waveshare Analog Input 8CH (B) V3."""

    def __init__(self, client: AnalogRegisterReader) -> None:
        self.client = client

    def read_channel(self, unit_id: int, channel: int) -> Waveshare8AIReading:
        if not 1 <= channel <= CHANNEL_COUNT:
            raise ValueError(f"Waveshare channel must be 1..{CHANNEL_COUNT}, got {channel}")
        offset = channel - 1
        mode_values = self.client.read_holding_registers(
            unit_id, MODE_BASE_ADDRESS + offset, 1
        )
        input_values = self.client.read_input_registers(
            unit_id, INPUT_BASE_ADDRESS + offset, 1
        )
        if len(mode_values) != 1 or len(input_values) != 1:
            raise RuntimeError("Waveshare 8AI returned an invalid single-register payload")
        try:
            return decode_channel(
                unit_id,
                channel,
                mode_word=mode_values[0],
                input_word=input_values[0],
            )
        except ValueError as exc:
            raise RuntimeError("Waveshare 8AI returned an invalid channel payload") from exc
