#!/usr/bin/env python3
"""Read-only, one-register-at-a-time Modbus RTU profiler for NEXOLAB."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class SerialProfile:
    baudrate: int
    parity: str
    stopbits: int


@dataclass
class Sample:
    unit_id: int
    function: int
    address: int
    sample_index: int
    outcome: str
    value_u16: int | None
    value_s16: int | None
    exception_code: int | None
    raw_hex: str
    elapsed_ms: float


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


def signed_16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def parse_range_spec(spec: str, minimum: int, maximum: int, label: str) -> list[int]:
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

    invalid = [value for value in values if not minimum <= value <= maximum]
    if invalid:
        raise ValueError(
            f"{label} must be in {minimum}..{maximum}: {sorted(invalid)}"
        )
    if not values:
        raise ValueError(f"{label} cannot be empty")
    return sorted(values)


def build_read_request(
    unit_id: int,
    function: int,
    address: int,
    count: int = 1,
) -> bytes:
    if function not in {3, 4}:
        raise ValueError("Only Modbus read functions 03 and 04 are supported")
    if count != 1:
        raise ValueError("Profiler intentionally reads exactly one register per request")

    payload = bytes(
        (
            unit_id,
            function,
            (address >> 8) & 0xFF,
            address & 0xFF,
            0x00,
            0x01,
        )
    )
    return add_crc(payload)


def extract_strict_response(
    buffer: bytes,
    unit_id: int,
    function: int,
) -> bytes | None:
    """Return only a CRC-valid exception or exact one-register response."""
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

        if response_function != function:
            continue

        if len(buffer) < offset + 7 or buffer[offset + 2] != 2:
            continue
        frame = buffer[offset : offset + 7]
        if has_valid_crc(frame):
            return frame

    return None


def transact(
    port: Any,
    request: bytes,
    unit_id: int,
    function: int,
    timeout: float,
) -> tuple[bytes | None, bytes, float]:
    port.reset_input_buffer()
    port.reset_output_buffer()

    started = time.monotonic()
    port.write(request)
    port.flush()

    deadline = started + timeout
    buffer = bytearray()
    while time.monotonic() < deadline:
        waiting = int(getattr(port, "in_waiting", 0))
        chunk = port.read(waiting if waiting > 0 else 1)
        if not chunk:
            continue

        buffer.extend(chunk)
        if len(buffer) >= len(request) and bytes(buffer[: len(request)]) == request:
            del buffer[: len(request)]

        frame = extract_strict_response(bytes(buffer), unit_id, function)
        if frame is not None:
            elapsed_ms = (time.monotonic() - started) * 1000
            return frame, bytes(buffer), elapsed_ms

    elapsed_ms = (time.monotonic() - started) * 1000
    return None, bytes(buffer), elapsed_ms


def decode_frame(frame: bytes) -> tuple[int | None, int | None]:
    if frame[1] & 0x80:
        return None, frame[2]
    value = int.from_bytes(frame[3:5], "big")
    return value, None


def read_sample(
    port: Any,
    unit_id: int,
    function: int,
    address: int,
    sample_index: int,
    timeout: float,
    retries: int,
) -> Sample:
    request = build_read_request(unit_id, function, address)

    last_raw = b""
    last_elapsed = 0.0
    for _ in range(retries + 1):
        frame, raw, elapsed_ms = transact(
            port,
            request,
            unit_id,
            function,
            timeout,
        )
        last_raw = raw
        last_elapsed = elapsed_ms

        if frame is None:
            continue

        value, exception = decode_frame(frame)
        if exception is not None:
            return Sample(
                unit_id=unit_id,
                function=function,
                address=address,
                sample_index=sample_index,
                outcome="exception",
                value_u16=None,
                value_s16=None,
                exception_code=exception,
                raw_hex=frame.hex(),
                elapsed_ms=round(elapsed_ms, 3),
            )

        assert value is not None
        return Sample(
            unit_id=unit_id,
            function=function,
            address=address,
            sample_index=sample_index,
            outcome="value",
            value_u16=value,
            value_s16=signed_16(value),
            exception_code=None,
            raw_hex=frame.hex(),
            elapsed_ms=round(elapsed_ms, 3),
        )

    return Sample(
        unit_id=unit_id,
        function=function,
        address=address,
        sample_index=sample_index,
        outcome="invalid_or_timeout" if last_raw else "timeout",
        value_u16=None,
        value_s16=None,
        exception_code=None,
        raw_hex=last_raw.hex(),
        elapsed_ms=round(last_elapsed, 3),
    )


def summarize(samples: Iterable[Sample]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int], list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[(sample.unit_id, sample.function, sample.address)].append(sample)

    result: list[dict[str, Any]] = []
    for (unit_id, function, address), rows in sorted(grouped.items()):
        values = [row.value_u16 for row in rows if row.value_u16 is not None]
        signed_values = [row.value_s16 for row in rows if row.value_s16 is not None]
        exceptions = sorted(
            {
                row.exception_code
                for row in rows
                if row.exception_code is not None
            }
        )
        successful = len(values)
        unique_values = sorted(set(values))
        result.append(
            {
                "unit_id": unit_id,
                "function": function,
                "address": address,
                "sample_count": len(rows),
                "success_count": successful,
                "timeout_count": sum(
                    row.outcome in {"timeout", "invalid_or_timeout"} for row in rows
                ),
                "exception_codes": exceptions,
                "values_u16": values,
                "values_s16": signed_values,
                "first_value_u16": values[0] if values else None,
                "minimum_u16": min(values) if values else None,
                "maximum_u16": max(values) if values else None,
                "changed": len(unique_values) > 1,
                "unique_value_count": len(unique_values),
                "stable": successful == len(rows) and len(unique_values) == 1,
            }
        )
    return result


def profile(args: argparse.Namespace) -> list[Sample]:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyserial is required: python3 -m pip install -r "
            "tools/rs485_discovery/requirements.txt"
        ) from exc

    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }
    parity = args.parity.upper()
    if parity not in parity_map:
        raise ValueError("Parity must be one of N, E, O")

    unit_ids = parse_range_spec(args.unit_ids, 1, 247, "Unit IDs")
    addresses = parse_range_spec(args.addresses, 0, 65535, "Register addresses")
    profile_config = SerialProfile(args.baudrate, parity, args.stopbits)

    total = len(unit_ids) * len(addresses) * args.samples
    completed = 0
    rows: list[Sample] = []

    print(
        f"Profiling {args.port}: units={args.unit_ids}, addresses={args.addresses}, "
        f"samples={args.samples}, FC={args.function:02d}"
    )
    print(
        f"Serial: {profile_config.baudrate} 8{profile_config.parity}"
        f"{profile_config.stopbits}; read-only; one register per request"
    )

    with serial.Serial(
        port=args.port,
        baudrate=profile_config.baudrate,
        bytesize=serial.EIGHTBITS,
        parity=parity_map[profile_config.parity],
        stopbits=profile_config.stopbits,
        timeout=min(args.timeout, 0.05),
        write_timeout=args.timeout,
        inter_byte_timeout=0.02,
        exclusive=True,
    ) as port:
        for sample_index in range(args.samples):
            print(f"\nSample pass {sample_index + 1}/{args.samples}")
            for unit_id in unit_ids:
                responsive = 0
                for address in addresses:
                    row = read_sample(
                        port=port,
                        unit_id=unit_id,
                        function=args.function,
                        address=address,
                        sample_index=sample_index,
                        timeout=args.timeout,
                        retries=args.retries,
                    )
                    rows.append(row)
                    completed += 1
                    if row.outcome in {"value", "exception"}:
                        responsive += 1
                    if args.progress and completed % 100 == 0:
                        print(f"  progress {completed}/{total}", flush=True)
                    time.sleep(args.delay)

                print(
                    f"  unit={unit_id:3d}: responsive addresses "
                    f"{responsive}/{len(addresses)}"
                )

            if sample_index + 1 < args.samples:
                time.sleep(args.sample_interval)

    return rows


def build_report(args: argparse.Namespace, rows: list[Sample]) -> dict[str, Any]:
    summary = summarize(rows)
    responsive = [
        item
        for item in summary
        if item["success_count"] > 0 or item["exception_codes"]
    ]
    dynamic = [item for item in responsive if item["changed"]]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "nexolab-rs485-register-profiler",
        "read_only": True,
        "one_register_per_request": True,
        "port": args.port,
        "resolved_port": os.path.realpath(args.port),
        "serial": {
            "baudrate": args.baudrate,
            "bytesize": 8,
            "parity": args.parity.upper(),
            "stopbits": args.stopbits,
        },
        "request": {
            "function": args.function,
            "unit_ids": parse_range_spec(args.unit_ids, 1, 247, "Unit IDs"),
            "addresses": parse_range_spec(
                args.addresses, 0, 65535, "Register addresses"
            ),
            "samples": args.samples,
            "sample_interval_seconds": args.sample_interval,
            "timeout_seconds": args.timeout,
            "retries": args.retries,
        },
        "statistics": {
            "raw_sample_count": len(rows),
            "register_summary_count": len(summary),
            "responsive_register_count": len(responsive),
            "dynamic_register_count": len(dynamic),
        },
        "dynamic_registers": dynamic,
        "registers": summary,
        "samples": [asdict(row) for row in rows],
    }


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "unit_id",
        "function",
        "address",
        "sample_count",
        "success_count",
        "timeout_count",
        "exception_codes",
        "first_value_u16",
        "minimum_u16",
        "maximum_u16",
        "changed",
        "unique_value_count",
        "stable",
        "values_u16",
        "values_s16",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in report["registers"]:
            row = dict(item)
            row["exception_codes"] = ",".join(map(str, row["exception_codes"]))
            row["values_u16"] = ",".join(map(str, row["values_u16"]))
            row["values_s16"] = ",".join(map(str, row["values_s16"]))
            writer.writerow({field: row.get(field) for field in fields})


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Profile Modbus RTU registers using strict, read-only, "
            "one-register-at-a-time requests."
        )
    )
    result.add_argument("--port", required=True)
    result.add_argument("--unit-ids", required=True)
    result.add_argument("--addresses", default="0-63")
    result.add_argument("--function", type=int, choices=(3, 4), default=3)
    result.add_argument("--baudrate", type=int, default=9600)
    result.add_argument("--parity", default="N")
    result.add_argument("--stopbits", type=int, choices=(1, 2), default=1)
    result.add_argument("--samples", type=int, default=3)
    result.add_argument("--sample-interval", type=float, default=2.0)
    result.add_argument("--timeout", type=float, default=0.15)
    result.add_argument("--retries", type=int, default=1)
    result.add_argument("--delay", type=float, default=0.01)
    result.add_argument("--progress", action="store_true")
    result.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/discovery/register-profile.json"),
    )
    result.add_argument(
        "--csv-output",
        type=Path,
        default=None,
    )
    return result


def main() -> int:
    args = parser().parse_args()
    if args.samples < 1:
        print("samples must be >= 1", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("timeout must be positive", file=sys.stderr)
        return 2
    if args.retries < 0 or args.delay < 0 or args.sample_interval < 0:
        print(
            "retries, delay and sample interval must be non-negative",
            file=sys.stderr,
        )
        return 2

    try:
        rows = profile(args)
        report = build_report(args, rows)
        write_json(args.output, report)
        csv_output = args.csv_output or args.output.with_suffix(".csv")
        write_csv(csv_output, report)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    stats = report["statistics"]
    print(f"\nJSON: {args.output}")
    print(f"CSV:  {csv_output}")
    print(f"Responsive registers: {stats['responsive_register_count']}")
    print(f"Dynamic registers:    {stats['dynamic_register_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
