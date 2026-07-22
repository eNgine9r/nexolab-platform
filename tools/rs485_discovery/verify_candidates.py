#!/usr/bin/env python3
"""Strict read-only verification for candidate Modbus RTU endpoints."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SerialProfile:
    baudrate: int
    parity: str
    stopbits: int


@dataclass
class Attempt:
    unit_id: int
    profile: SerialProfile
    function: int
    address: int
    count: int
    outcome: str
    registers: list[int]
    exception_code: int | None
    raw_hex: str


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def add_crc(payload: bytes) -> bytes:
    crc = crc16_modbus(payload)
    return payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def has_valid_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    expected = frame[-2] | (frame[-1] << 8)
    return crc16_modbus(frame[:-2]) == expected


def build_read_request(unit_id: int, function: int, address: int, count: int) -> bytes:
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


def extract_strict_response(
    buffer: bytes,
    unit_id: int,
    function: int,
    expected_registers: int,
) -> bytes | None:
    """Return only a CRC-valid exception or exact-length read response."""
    for offset in range(len(buffer)):
        if buffer[offset] != unit_id or offset + 1 >= len(buffer):
            continue

        response_function = buffer[offset + 1]
        if response_function == (function | 0x80):
            if len(buffer) >= offset + 5:
                frame = buffer[offset : offset + 5]
                if has_valid_crc(frame):
                    return frame
            continue

        if response_function != function or len(buffer) < offset + 3:
            continue

        byte_count = buffer[offset + 2]
        expected_bytes = expected_registers * 2
        if byte_count != expected_bytes:
            continue

        frame_length = 5 + byte_count
        if len(buffer) < offset + frame_length:
            continue
        frame = buffer[offset : offset + frame_length]
        if has_valid_crc(frame):
            return frame
    return None


def decode_response(frame: bytes) -> tuple[list[int], int | None]:
    if frame[1] & 0x80:
        return [], frame[2]
    byte_count = frame[2]
    data = frame[3 : 3 + byte_count]
    registers = [
        int.from_bytes(data[index : index + 2], "big")
        for index in range(0, len(data), 2)
    ]
    return registers, None


def transact(
    port: Any,
    request: bytes,
    unit_id: int,
    function: int,
    expected_registers: int,
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
        if not chunk:
            continue
        buffer.extend(chunk)

        if len(buffer) >= len(request) and bytes(buffer[: len(request)]) == request:
            del buffer[: len(request)]

        frame = extract_strict_response(
            bytes(buffer),
            unit_id,
            function,
            expected_registers,
        )
        if frame is not None:
            return frame, bytes(buffer)
    return None, bytes(buffer)


def parse_ids(spec: str) -> list[int]:
    result: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            result.update(range(start, end + 1))
        else:
            result.add(int(token))
    invalid = [value for value in result if not 1 <= value <= 247]
    if invalid:
        raise ValueError(f"Unit IDs must be in 1..247: {invalid}")
    return sorted(result)


def probe(
    port: Any,
    unit_id: int,
    profile: SerialProfile,
    function: int,
    address: int,
    count: int,
    timeout: float,
) -> Attempt:
    request = build_read_request(unit_id, function, address, count)
    frame, raw = transact(port, request, unit_id, function, count, timeout)
    if frame is None:
        return Attempt(
            unit_id,
            profile,
            function,
            address,
            count,
            "invalid_or_timeout" if raw else "timeout",
            [],
            None,
            raw.hex(),
        )

    registers, exception = decode_response(frame)
    return Attempt(
        unit_id,
        profile,
        function,
        address,
        count,
        "exception" if exception is not None else "registers",
        registers,
        exception,
        frame.hex(),
    )


def verify(args: argparse.Namespace) -> list[Attempt]:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyserial is required") from exc

    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }
    profiles = [
        SerialProfile(args.baudrate, parity.strip().upper(), args.stopbits)
        for parity in args.parities.split(",")
        if parity.strip()
    ]
    invalid_parities = [profile.parity for profile in profiles if profile.parity not in parity_map]
    if invalid_parities:
        raise ValueError(f"Unsupported parity values: {invalid_parities}")

    attempts: list[Attempt] = []
    for profile in profiles:
        print(
            f"\n[{profile.baudrate} baud, parity {profile.parity}, "
            f"{profile.stopbits} stop bit(s)]"
        )
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
            for unit_id in parse_ids(args.unit_ids):
                unit_attempts = [
                    probe(port, unit_id, profile, 3, 0, 1, args.timeout),
                    probe(port, unit_id, profile, 4, 0, 1, args.timeout),
                    probe(port, unit_id, profile, 3, 256, 6, args.timeout),
                    probe(port, unit_id, profile, 4, 256, 6, args.timeout),
                ]
                attempts.extend(unit_attempts)
                valid = [
                    attempt
                    for attempt in unit_attempts
                    if attempt.outcome in {"registers", "exception"}
                ]
                if valid:
                    details = ", ".join(
                        f"fc={item.function:02d}@{item.address}:{item.outcome}"
                        for item in valid
                    )
                    print(f"  CONFIRMED unit={unit_id:3d}: {details}")
                else:
                    print(f"  rejected unit={unit_id:3d}")
                time.sleep(args.delay)
    return attempts


def build_report(args: argparse.Namespace, attempts: list[Attempt]) -> dict[str, Any]:
    groups: dict[tuple[int, int, str, int], list[Attempt]] = {}
    for attempt in attempts:
        key = (
            attempt.unit_id,
            attempt.profile.baudrate,
            attempt.profile.parity,
            attempt.profile.stopbits,
        )
        groups.setdefault(key, []).append(attempt)

    endpoints = []
    for key, values in groups.items():
        valid = [
            value
            for value in values
            if value.outcome in {"registers", "exception"}
        ]
        if not valid:
            continue
        unit_id, baudrate, parity, stopbits = key
        endpoints.append(
            {
                "unit_id": unit_id,
                "baudrate": baudrate,
                "parity": parity,
                "stopbits": stopbits,
                "evidence_count": len(valid),
                "evidence": [asdict(value) for value in valid],
            }
        )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "nexolab-rs485-strict-verifier",
        "read_only": True,
        "port": args.port,
        "endpoints": endpoints,
        "attempts": [asdict(attempt) for attempt in attempts],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Strictly verify candidate Modbus RTU endpoints without writes."
    )
    result.add_argument("--port", required=True)
    result.add_argument("--unit-ids", default="1,200-203")
    result.add_argument("--baudrate", type=int, default=9600)
    result.add_argument("--parities", default="N,E")
    result.add_argument("--stopbits", type=int, default=1)
    result.add_argument("--timeout", type=float, default=0.20)
    result.add_argument("--delay", type=float, default=0.03)
    result.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/discovery/rs485-verify.json"),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        attempts = verify(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    report = build_report(args, attempts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nStrictly confirmed endpoints: {len(report['endpoints'])}")
    print(f"Report: {args.output}")
    return 0 if report["endpoints"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
