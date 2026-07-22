#!/usr/bin/env python3
"""Read-only Modbus RTU discovery for NEXOLAB RS-485 buses."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_QUICK_PROFILES = (
    (9600, "N", 1),
    (9600, "E", 1),
    (19200, "N", 1),
    (19200, "E", 1),
)
DEFAULT_FULL_BAUDS = (9600, 19200, 38400, 115200)
DEFAULT_FULL_PARITIES = ("N", "E", "O")
DEFAULT_FULL_STOP_BITS = (1, 2)


@dataclass(frozen=True)
class SerialProfile:
    baudrate: int
    parity: str
    stopbits: int


@dataclass
class ProbeResult:
    unit_id: int
    serial: SerialProfile
    probe_function: int
    probe_address: int
    exception_code: int | None
    device_information: dict[str, str]
    candidate_key: str
    candidate_name: str
    confidence: float
    identification_method: str
    fingerprint: dict[str, Any]


@dataclass
class ScanWarning:
    serial: SerialProfile
    unit_id: int
    message: str


def crc16_modbus(data: bytes) -> int:
    """Return the Modbus RTU CRC16 for *data*."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def add_crc(payload: bytes) -> bytes:
    crc = crc16_modbus(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def has_valid_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    expected = frame[-2] | (frame[-1] << 8)
    return crc16_modbus(frame[:-2]) == expected


def build_read_request(unit_id: int, function: int, address: int, count: int = 1) -> bytes:
    if function not in {3, 4}:
        raise ValueError("Only read functions 03 and 04 are supported")
    payload = bytes(
        (
            unit_id,
            function,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        )
    )
    return add_crc(payload)


def build_device_id_request(unit_id: int) -> bytes:
    return add_crc(bytes((unit_id, 0x2B, 0x0E, 0x01, 0x00)))


def _frame_length_at(buffer: bytes, offset: int, function: int) -> int | None:
    remaining = len(buffer) - offset
    if remaining < 5:
        return None

    response_function = buffer[offset + 1]
    if response_function == (function | 0x80):
        return 5

    if response_function != function:
        return None

    if function in {3, 4}:
        byte_count = buffer[offset + 2]
        return 5 + byte_count

    if function == 0x2B:
        if remaining < 10 or buffer[offset + 2] != 0x0E:
            return None
        object_count = buffer[offset + 7]
        cursor = offset + 8
        for _ in range(object_count):
            if len(buffer) < cursor + 2:
                return None
            object_length = buffer[cursor + 1]
            cursor += 2 + object_length
            if len(buffer) < cursor:
                return None
        return cursor - offset + 2

    return None


def extract_response(buffer: bytes, unit_id: int, function: int) -> bytes | None:
    """Extract the first valid matching RTU response from a noisy byte buffer."""
    for offset in range(len(buffer)):
        if buffer[offset] != unit_id:
            continue
        if offset + 1 >= len(buffer):
            break
        if buffer[offset + 1] not in {function, function | 0x80}:
            continue
        frame_length = _frame_length_at(buffer, offset, function)
        if frame_length is None or len(buffer) < offset + frame_length:
            continue
        frame = buffer[offset : offset + frame_length]
        if has_valid_crc(frame):
            return frame
    return None


def decode_register_response(frame: bytes) -> tuple[list[int], int | None]:
    function = frame[1]
    if function & 0x80:
        return [], frame[2]
    byte_count = frame[2]
    data = frame[3 : 3 + byte_count]
    if byte_count % 2:
        return [], None
    registers = [
        int.from_bytes(data[index : index + 2], "big")
        for index in range(0, len(data), 2)
    ]
    return registers, None


def decode_device_information(frame: bytes) -> dict[str, str]:
    if len(frame) < 10 or frame[1] != 0x2B or frame[2] != 0x0E:
        return {}
    names = {
        0x00: "vendor_name",
        0x01: "product_code",
        0x02: "revision",
        0x03: "vendor_url",
        0x04: "product_name",
        0x05: "model_name",
        0x06: "application_name",
    }
    object_count = frame[7]
    cursor = 8
    result: dict[str, str] = {}
    for _ in range(object_count):
        if cursor + 2 > len(frame) - 2:
            break
        object_id = frame[cursor]
        object_length = frame[cursor + 1]
        cursor += 2
        raw = frame[cursor : cursor + object_length]
        cursor += object_length
        key = names.get(object_id, f"object_{object_id:02x}")
        result[key] = raw.decode("ascii", errors="replace").strip("\x00 ")
    return result


def signed_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def identify_device(
    information: dict[str, str],
    fingerprint: dict[str, Any],
) -> tuple[str, str, float, str]:
    identity_text = " ".join(information.values()).lower()
    if "le-01mp" in identity_text or (
        "f&f" in identity_text and "le-01" in identity_text
    ):
        return "fif-le01mp", "F&F LE-01MP", 1.0, "modbus-device-identification"
    if "xjp60d" in identity_text or (
        "dixell" in identity_text and "xjp60" in identity_text
    ):
        return "dixell-xjp60d", "Dixell XJP60D", 1.0, "modbus-device-identification"

    values = fingerprint.get("registers_256")
    if isinstance(values, list) and values:
        signed_values = [signed_16(int(value)) for value in values]
        plausible = [value for value in signed_values if -500 <= value <= 1500]
        if len(plausible) >= min(3, len(signed_values)):
            return (
                "dixell-xjp-family",
                "Dixell XJP family (candidate)",
                0.55,
                "read-only-register-fingerprint",
            )

    return "unknown-modbus", "Unknown Modbus RTU device", 0.2, "responsive-endpoint"


def parse_id_spec(spec: str) -> list[int]:
    values: set[int] = set()
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            values.update(range(start, end + 1))
        else:
            values.add(int(token))
    invalid = [value for value in values if not 1 <= value <= 247]
    if invalid:
        raise ValueError(f"Modbus unit IDs must be in 1..247: {invalid}")
    return sorted(values)


def parse_csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def parse_csv_strings(value: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def serial_profiles(args: argparse.Namespace) -> list[SerialProfile]:
    if args.quick:
        return [SerialProfile(*profile) for profile in DEFAULT_QUICK_PROFILES]
    return [
        SerialProfile(baudrate, parity, stopbits)
        for baudrate in parse_csv_ints(args.baud_rates)
        for parity in parse_csv_strings(args.parities)
        for stopbits in parse_csv_ints(args.stop_bits)
    ]


def read_response(
    port: Any,
    request: bytes,
    unit_id: int,
    function: int,
    timeout: float,
) -> tuple[bytes | None, bytes]:
    port.reset_input_buffer()
    port.reset_output_buffer()
    port.write(request)
    port.flush()

    deadline = time.monotonic() + timeout
    buffer = bytearray()
    while time.monotonic() < deadline:
        waiting = int(getattr(port, "in_waiting", 0))
        chunk = port.read(waiting if waiting > 0 else 1)
        if chunk:
            buffer.extend(chunk)
            if len(buffer) >= len(request) and bytes(buffer[: len(request)]) == request:
                del buffer[: len(request)]
            frame = extract_response(bytes(buffer), unit_id, function)
            if frame is not None:
                return frame, bytes(buffer)
    return None, bytes(buffer)


def probe_endpoint(
    port: Any,
    unit_id: int,
    timeout: float,
    deep: bool,
) -> tuple[bytes | None, int, int, bytes]:
    probes = [(3, 0), (4, 0)]
    if deep:
        probes.extend(((3, 256), (4, 256)))
    last_buffer = b""
    for function, address in probes:
        request = build_read_request(unit_id, function, address)
        response, buffer = read_response(port, request, unit_id, function, timeout)
        last_buffer = buffer
        if response is not None:
            return response, function, address, buffer
    return None, 0, 0, last_buffer


def collect_fingerprint(port: Any, unit_id: int, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for function in (3, 4):
        request = build_read_request(unit_id, function, 256, 6)
        response, _ = read_response(port, request, unit_id, function, timeout)
        if response is None:
            continue
        registers, exception = decode_register_response(response)
        if exception is None and registers:
            result["registers_256"] = registers
            result["registers_256_function"] = function
            break
        if exception is not None:
            result[f"registers_256_function_{function}_exception"] = exception
    return result


def collect_device_information(
    port: Any,
    unit_id: int,
    timeout: float,
) -> dict[str, str]:
    request = build_device_id_request(unit_id)
    response, _ = read_response(port, request, unit_id, 0x2B, timeout)
    if response is None or response[1] & 0x80:
        return {}
    return decode_device_information(response)


def perform_scan(
    args: argparse.Namespace,
) -> tuple[list[ProbeResult], list[ScanWarning]]:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required: python3 -m pip install -r requirements.txt"
        ) from exc

    unit_ids = parse_id_spec(args.unit_ids)
    profiles = serial_profiles(args)
    results: list[ProbeResult] = []
    warnings: list[ScanWarning] = []
    seen: set[tuple[int, int, str, int]] = set()

    total = len(profiles) * len(unit_ids)
    completed = 0
    print(
        f"Scanning {args.port}: {len(profiles)} serial profiles, "
        f"{len(unit_ids)} unit IDs"
    )
    print("Read-only functions: 03, 04, 43/14. No register writes are performed.")

    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }

    for profile in profiles:
        print(
            f"\n[{profile.baudrate} baud, parity {profile.parity}, "
            f"{profile.stopbits} stop bit(s)]"
        )
        try:
            with serial.Serial(
                port=args.port,
                baudrate=profile.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=parity_map[profile.parity],
                stopbits=profile.stopbits,
                timeout=min(args.timeout, 0.05),
                write_timeout=args.timeout,
                inter_byte_timeout=0.02,
                exclusive=True,
            ) as port:
                for unit_id in unit_ids:
                    completed += 1
                    response, function, address, raw_buffer = probe_endpoint(
                        port,
                        unit_id,
                        args.timeout,
                        args.deep,
                    )
                    if response is None:
                        if raw_buffer:
                            warnings.append(
                                ScanWarning(
                                    serial=profile,
                                    unit_id=unit_id,
                                    message=(
                                        "Bytes were received but no valid CRC response was decoded; "
                                        "possible address collision, local echo, noise, or wrong "
                                        "serial settings"
                                    ),
                                )
                            )
                        if args.progress and completed % 50 == 0:
                            print(f"  progress {completed}/{total}", flush=True)
                        time.sleep(args.delay)
                        continue

                    key = (
                        unit_id,
                        profile.baudrate,
                        profile.parity,
                        profile.stopbits,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    _, exception_code = decode_register_response(response)
                    information = collect_device_information(
                        port,
                        unit_id,
                        args.timeout,
                    )
                    fingerprint = collect_fingerprint(port, unit_id, args.timeout)
                    candidate_key, candidate_name, confidence, method = identify_device(
                        information,
                        fingerprint,
                    )
                    result = ProbeResult(
                        unit_id=unit_id,
                        serial=profile,
                        probe_function=function,
                        probe_address=address,
                        exception_code=exception_code,
                        device_information=information,
                        candidate_key=candidate_key,
                        candidate_name=candidate_name,
                        confidence=confidence,
                        identification_method=method,
                        fingerprint=fingerprint,
                    )
                    results.append(result)
                    print(
                        f"  FOUND unit={unit_id:3d} -> {candidate_name} "
                        f"(confidence {confidence:.0%})"
                    )
                    time.sleep(args.delay)
        except (OSError, serial.SerialException) as exc:
            raise RuntimeError(
                f"Cannot scan {args.port} with profile {profile}: {exc}"
            ) from exc

    return results, warnings


def build_report(
    args: argparse.Namespace,
    results: Iterable[ProbeResult],
    warnings: Iterable[ScanWarning],
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    devices = []
    for result in results:
        devices.append(
            {
                "registry_id": (
                    f"rs485-{result.serial.baudrate}-{result.serial.parity}-"
                    f"{result.serial.stopbits}-unit-{result.unit_id}"
                ),
                "status": (
                    "discovered"
                    if result.confidence >= 0.9
                    else "pending_confirmation"
                ),
                "display_name": result.candidate_name,
                "profile_key": result.candidate_key,
                "confidence": result.confidence,
                "identification_method": result.identification_method,
                "transport": {
                    "type": "modbus-rtu",
                    "port": os.path.realpath(args.port),
                    "stable_port": args.port,
                    "baudrate": result.serial.baudrate,
                    "parity": result.serial.parity,
                    "stopbits": result.serial.stopbits,
                    "bytesize": 8,
                    "unit_id": result.unit_id,
                },
                "device_information": result.device_information,
                "fingerprint": result.fingerprint,
                "probe": {
                    "function": result.probe_function,
                    "address": result.probe_address,
                    "exception_code": result.exception_code,
                },
                "first_seen_at": generated_at,
            }
        )
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "scanner": "nexolab-rs485-discovery",
        "scan_mode": "quick" if args.quick else "full",
        "read_only": True,
        "serial_port": args.port,
        "devices": devices,
        "warnings": [
            {
                "serial": asdict(warning.serial),
                "unit_id": warning.unit_id,
                "message": warning.message,
            }
            for warning in warnings
        ],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Discover Modbus RTU endpoints without writing to device registers."
    )
    result.add_argument(
        "--port",
        required=True,
        help="Stable serial path, preferably /dev/serial/by-id/...",
    )
    result.add_argument(
        "--quick",
        action="store_true",
        help="Scan four common serial profiles",
    )
    result.add_argument(
        "--deep",
        action="store_true",
        help="Add fallback probes at register address 256",
    )
    result.add_argument(
        "--baud-rates",
        default=",".join(map(str, DEFAULT_FULL_BAUDS)),
    )
    result.add_argument("--parities", default=",".join(DEFAULT_FULL_PARITIES))
    result.add_argument(
        "--stop-bits",
        default=",".join(map(str, DEFAULT_FULL_STOP_BITS)),
    )
    result.add_argument("--unit-ids", default="1-247")
    result.add_argument(
        "--timeout",
        type=float,
        default=0.10,
        help="Response timeout per probe",
    )
    result.add_argument(
        "--delay",
        type=float,
        default=0.01,
        help="Delay between unit IDs",
    )
    result.add_argument("--progress", action="store_true")
    result.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/discovery/rs485-report.json"),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if args.timeout <= 0 or args.delay < 0:
        print(
            "timeout must be positive and delay must be non-negative",
            file=sys.stderr,
        )
        return 2
    try:
        results, warnings = perform_scan(args)
        report = build_report(args, results, warnings)
        write_report(args.output, report)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\nDiscovered endpoints: {len(results)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Report: {args.output}")
    if not results:
        print(
            "No valid endpoint was found. Check A/B polarity, power, termination, "
            "duplicate unit IDs, and run again without --quick.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
