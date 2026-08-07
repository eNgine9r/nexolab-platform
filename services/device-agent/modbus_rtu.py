from __future__ import annotations

import termios
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ModbusRequestContext:
    """Bounded labels attached to a physical request measurement."""

    device_family: str = "unclassified"
    target_id: str = "unclassified"
    operation: str = "normal"


@dataclass(frozen=True)
class ModbusRequestMeasurement:
    """One physical serial request attempt, including retries."""

    bus: str
    device_family: str
    target_id: str
    operation: str
    unit_id: int
    function: int
    address: int
    count: int
    attempt: int
    outcome: str
    duration_seconds: float


RequestObserver = Callable[[ModbusRequestMeasurement], None]


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


def build_read_holding_registers_request(
    unit_id: int,
    address: int,
    count: int,
) -> bytes:
    if not 1 <= unit_id <= 247:
        raise ValueError(f"Modbus unit_id must be 1..247, got {unit_id}")
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"Modbus address must be 0..65535, got {address}")
    if not 1 <= count <= 125:
        raise ValueError(f"Modbus register count must be 1..125, got {count}")
    if address + count - 1 > 0xFFFF:
        raise ValueError("Modbus register range exceeds address 65535")
    return append_crc(
        bytes(
            (
                unit_id,
                0x03,
                address >> 8,
                address & 0xFF,
                count >> 8,
                count & 0xFF,
            )
        )
    )


def build_read_holding_register_request(unit_id: int, address: int) -> bytes:
    return build_read_holding_registers_request(unit_id, address, 1)


def parse_read_holding_registers_response(
    frame: bytes,
    unit_id: int,
    count: int,
) -> tuple[int, ...]:
    if not 1 <= count <= 125:
        raise ValueError(f"Modbus register count must be 1..125, got {count}")
    expected_byte_count = count * 2
    expected_length = expected_byte_count + 5
    if len(frame) not in {5, expected_length}:
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
    if len(frame) != expected_length or frame[2] != expected_byte_count:
        raise ModbusProtocolError(
            f"Expected {expected_byte_count} register-data bytes, "
            f"received {frame[2]}"
        )
    return tuple(
        int.from_bytes(frame[offset : offset + 2], byteorder="big", signed=False)
        for offset in range(3, 3 + expected_byte_count, 2)
    )


def parse_read_holding_register_response(frame: bytes, unit_id: int) -> int:
    return parse_read_holding_registers_response(frame, unit_id, 1)[0]


class ModbusRTUClient:
    """Strict read-only Modbus RTU client for FC03 register reads."""

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
        request_observer: RequestObserver | None = None,
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
        self._request_observer = request_observer
        self._request_context = threading.local()

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

    def _invalidate_serial(self, port: SerialPort) -> None:
        """Drop a serial handle after transport I/O failure without hiding it."""

        if self._serial is port:
            self._serial = None
        try:
            port.close()
        except Exception:
            # The original transport exception is authoritative. Closing a
            # broken descriptor is best-effort and must never mask that error.
            pass

    @contextmanager
    def instrumentation_scope(
        self,
        *,
        device_family: str,
        target_id: str,
        operation: str = "normal",
    ) -> Iterator[None]:
        previous = getattr(self._request_context, "value", None)
        self._request_context.value = ModbusRequestContext(
            device_family=device_family,
            target_id=target_id,
            operation=operation,
        )
        try:
            yield
        finally:
            if previous is None:
                try:
                    del self._request_context.value
                except AttributeError:
                    pass
            else:
                self._request_context.value = previous

    def _context(self) -> ModbusRequestContext:
        value = getattr(self._request_context, "value", None)
        return value if isinstance(value, ModbusRequestContext) else ModbusRequestContext()

    def _observe_request(
        self,
        *,
        context: ModbusRequestContext,
        unit_id: int,
        address: int,
        count: int,
        attempt: int,
        outcome: str,
        started_at: float,
    ) -> None:
        if self._request_observer is None:
            return
        measurement = ModbusRequestMeasurement(
            bus=self.port,
            device_family=context.device_family,
            target_id=context.target_id,
            operation=context.operation,
            unit_id=unit_id,
            function=3,
            address=address,
            count=count,
            attempt=attempt,
            outcome=outcome,
            duration_seconds=max(0.0, time.monotonic() - started_at),
        )
        try:
            self._request_observer(measurement)
        except Exception:
            # Observability must never interrupt the read-only acquisition path.
            pass

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

    def _read_response(self, port: SerialPort, expected_count: int) -> bytes:
        header = self._read_exact(port, 3)
        function = header[1]
        if function & 0x80:
            return header + self._read_exact(port, 2)
        byte_count = header[2]
        expected_byte_count = expected_count * 2
        if byte_count != expected_byte_count:
            raise ModbusProtocolError(
                f"Expected byte_count={expected_byte_count}, received {byte_count}"
            )
        return header + self._read_exact(port, byte_count + 2)

    def read_holding_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]:
        request = build_read_holding_registers_request(unit_id, address, count)
        last_timeout: ModbusTimeoutError | None = None
        context = self._context()

        with self._lock:
            port = self._open()
            for attempt_index in range(self.retries + 1):
                attempt = attempt_index + 1
                request_started_at = 0.0
                request_attempted = False
                try:
                    port.reset_input_buffer()
                    port.reset_output_buffer()
                    request_started_at = time.monotonic()
                    request_attempted = True
                    written = port.write(request)
                    if written != len(request):
                        raise ModbusProtocolError(
                            f"Serial write incomplete: {written}/{len(request)} bytes"
                        )
                    port.flush()
                    frame = self._read_response(port, count)
                    result = parse_read_holding_registers_response(
                        frame,
                        unit_id,
                        count,
                    )
                except ModbusTimeoutError as exc:
                    if request_attempted:
                        self._observe_request(
                            context=context,
                            unit_id=unit_id,
                            address=address,
                            count=count,
                            attempt=attempt,
                            outcome="timeout",
                            started_at=request_started_at,
                        )
                    last_timeout = exc
                    continue
                except ModbusExceptionResponse:
                    if request_attempted:
                        self._observe_request(
                            context=context,
                            unit_id=unit_id,
                            address=address,
                            count=count,
                            attempt=attempt,
                            outcome="exception_response",
                            started_at=request_started_at,
                        )
                    raise
                except ModbusProtocolError:
                    if request_attempted:
                        self._observe_request(
                            context=context,
                            unit_id=unit_id,
                            address=address,
                            count=count,
                            attempt=attempt,
                            outcome="protocol_error",
                            started_at=request_started_at,
                        )
                    raise
                except (OSError, termios.error):
                    if request_attempted:
                        self._observe_request(
                            context=context,
                            unit_id=unit_id,
                            address=address,
                            count=count,
                            attempt=attempt,
                            outcome="io_error",
                            started_at=request_started_at,
                        )
                    self._invalidate_serial(port)
                    raise
                else:
                    self._observe_request(
                        context=context,
                        unit_id=unit_id,
                        address=address,
                        count=count,
                        attempt=attempt,
                        outcome="success",
                        started_at=request_started_at,
                    )
                    return result

        assert last_timeout is not None
        raise last_timeout

    def read_holding_register(self, unit_id: int, address: int) -> int:
        return self.read_holding_registers(unit_id, address, 1)[0]
