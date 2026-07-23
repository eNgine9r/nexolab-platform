from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

try:
    import serial as _serial
except ModuleNotFoundError:  # pragma: no cover - incomplete runtime only
    _serial = None


class SerialPort(Protocol):
    timeout: float | None

    def write(self, data: bytes) -> int: ...

    def read(self, size: int = 1) -> bytes: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...

    def reset_input_buffer(self) -> None: ...

    def reset_output_buffer(self) -> None: ...


class ModbusError(RuntimeError):
    """Base error for strict Modbus RTU reads."""


class ModbusTimeoutError(ModbusError):
    """The slave did not return a complete frame before the deadline."""


class ModbusProtocolError(ModbusError):
    """The slave returned a malformed, unexpected, or CRC-invalid frame."""


class ModbusExceptionResponse(ModbusError):
    def __init__(self, unit_id: int, function: int, exception_code: int) -> None:
        self.unit_id = unit_id
        self.function = function
        self.exception_code = exception_code
        super().__init__(
            f"Modbus exception from unit {unit_id}: "
            f"function=0x{function:02X}, code=0x{exception_code:02X}"
        )


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def append_crc(payload: bytes) -> bytes:
    checksum = crc16(payload)
    return payload + bytes((checksum & 0xFF, checksum >> 8))


def build_read_holding_register_request(unit_id: int, address: int) -> bytes:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit_id must be 1..247, got {unit_id}")
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"Modbus address must be 0..65535, got {address}")
    return append_crc(
        bytes(
            (
                unit_id,
                0x03,
                address >> 8,
                address & 0xFF,
                0x00,
                0x01,
            )
        )
    )


def parse_read_holding_register_response(frame: bytes, unit_id: int) -> int:
    if len(frame) not in {5, 7}:
        raise ModbusProtocolError(f"Unexpected Modbus frame length: {len(frame)}")
    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], byteorder="little"):
        raise ModbusProtocolError("Modbus response CRC mismatch")
    if frame[0] != unit_id:
        raise ModbusProtocolError(
            f"Unexpected Modbus unit: expected {unit_id}, received {frame[0]}"
        )

    function = frame[1]
    if function == 0x83:
        if len(frame) != 5:
            raise ModbusProtocolError("Malformed Modbus exception response")
        raise ModbusExceptionResponse(unit_id, 0x03, frame[2])
    if function != 0x03:
        raise ModbusProtocolError(f"Unexpected Modbus function: 0x{function:02X}")
    if len(frame) != 7 or frame[2] != 2:
        raise ModbusProtocolError("Expected exactly one holding register in the response")
    return int.from_bytes(frame[3:5], byteorder="big", signed=False)


class ModbusRTUClient:
    """Strict read-only Modbus RTU client for one-register FC03 requests."""

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 9600,
        parity: str = "N",
        stopbits: int = 1,
        timeout: float = 0.3,
        retries: int = 1,
        serial_factory: Callable[..., SerialPort] | None = None,
    ) -> None:
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if parity not in {"N", "E", "O"}:
            raise ValueError("parity must be N, E, or O")
        if stopbits not in {1, 2}:
            raise ValueError("stopbits must be 1 or 2")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")

        self.port = port
        self.baudrate = baudrate
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.retries = retries
        self._serial_factory = serial_factory
        self._serial: SerialPort | None = None
        self._lock = threading.Lock()

    def _open(self) -> SerialPort:
        if self._serial is not None:
            return self._serial
        factory = self._serial_factory
        if factory is None:
            if _serial is None:
                raise RuntimeError("pyserial is required for Modbus hardware mode")
            factory = _serial.Serial
        self._serial = factory(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=8,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )
        return self._serial

    def close(self) -> None:
        with self._lock:
            if self._serial is not None:
                self._serial.close()
                self._serial = None

    def _read_exact(self, port: SerialPort, size: int) -> bytes:
        deadline = time.monotonic() + self.timeout
        chunks = bytearray()
        while len(chunks) < size:
            chunk = port.read(size - len(chunks))
            if chunk:
                chunks.extend(chunk)
                continue
            if time.monotonic() >= deadline:
                raise ModbusTimeoutError(
                    f"Timed out after receiving {len(chunks)} of {size} bytes"
                )
        return bytes(chunks)

    def _read_response(self, port: SerialPort) -> bytes:
        header = self._read_exact(port, 3)
        function = header[1]
        if function & 0x80:
            return header + self._read_exact(port, 2)
        byte_count = header[2]
        if byte_count != 2:
            raise ModbusProtocolError(
                f"Expected byte_count=2 for one register, received {byte_count}"
            )
        return header + self._read_exact(port, byte_count + 2)

    def read_holding_register(self, unit_id: int, address: int) -> int:
        request = build_read_holding_register_request(unit_id, address)
        last_timeout: ModbusTimeoutError | None = None

        with self._lock:
            port = self._open()
            for _attempt in range(self.retries + 1):
                try:
                    port.reset_input_buffer()
                    port.reset_output_buffer()
                    written = port.write(request)
                    if written != len(request):
                        raise ModbusProtocolError(
                            f"Serial write incomplete: {written}/{len(request)} bytes"
                        )
                    port.flush()
                    frame = self._read_response(port)
                    return parse_read_holding_register_response(frame, unit_id)
                except ModbusTimeoutError as exc:
                    last_timeout = exc

        assert last_timeout is not None
        raise last_timeout
