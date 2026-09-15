#!/usr/bin/env python3
"""Fail-closed read-only AK-CC25 Pro probe for an isolated RS-485 adapter."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

THIS_FILE = Path(__file__).resolve()
DEVICE_AGENT_ROOT = THIS_FILE.parents[1]
REPOSITORY_ROOT = THIS_FILE.parents[3]
DISCOVERY_ROOT = REPOSITORY_ROOT / "tools" / "rs485_discovery"
for root in (DEVICE_AGENT_ROOT, THIS_FILE.parent, DISCOVERY_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from akcc25 import PROFILE_VERSION, REGISTERS, decode_register  # noqa: E402
from commission_rs485_bus import (  # noqa: E402
    DEFAULT_DEVICE_AGENT_CONTAINER,
    busy_pids,
    inventory_adapters,
    runtime_protected_ports,
    select_new_adapter,
)
from scan_rs485 import (  # noqa: E402
    build_read_request,
    decode_register_response,
    read_response,
)

PARITIES = {"N", "E", "O"}
STOP_BITS = {1, 2}
BAUD_RATES = {9600, 19200, 38400, 115200}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read the fixed AK-CC25 Pro FC03 discovery subset only on an adapter "
            "proven outside current NEXOLAB production ownership."
        )
    )
    parser.add_argument("--adapter", required=True, help="Stable /dev/serial/by-id/... path")
    parser.add_argument("--unit-id", type=int, default=35)
    parser.add_argument("--baudrate", type=int, required=True, choices=sorted(BAUD_RATES))
    parser.add_argument("--parity", required=True, choices=sorted(PARITIES))
    parser.add_argument("--stopbits", type=int, required=True, choices=sorted(STOP_BITS))
    parser.add_argument("--timeout", type=float, default=0.30)
    parser.add_argument("--device-agent-container", default=DEFAULT_DEVICE_AGENT_CONTAINER)
    parser.add_argument("--protected-port", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.unit_id <= 247:
        raise ValueError("unit-id must be in 1..247")
    if args.timeout <= 0 or args.timeout > 2:
        raise ValueError("timeout must be > 0 and <= 2 seconds")
    if not args.adapter.startswith("/dev/serial/by-id/"):
        raise ValueError("adapter must use a stable /dev/serial/by-id/... path")


def resolve_isolated_adapter(
    *,
    adapter_path: str,
    container: str,
    additional_protected: Sequence[str],
):
    runtime_ports = runtime_protected_ports(container)
    protected = tuple(sorted(set(runtime_ports) | set(additional_protected)))
    selected = select_new_adapter(
        inventory_adapters(),
        protected_ports=protected,
        requested_port=adapter_path,
    )
    pids = busy_pids(selected.stable_path)
    if pids:
        raise RuntimeError(
            "Refusing AK-CC25 probe because the isolated adapter is busy: "
            + ", ".join(pids)
        )
    return selected, protected


def probe_port(
    port: Any,
    *,
    unit_id: int,
    timeout: float,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for register in REGISTERS:
        request = build_read_request(unit_id, 3, register.address, 1)
        response, raw_buffer = read_response(port, request, unit_id, 3, timeout)
        item: dict[str, Any] = {
            "key": register.key,
            "danfoss_code": register.code,
            "address": register.address,
            "function_code": 3,
            "documented_access": register.source_access,
            "request_hex": request.hex(),
            "response_hex": response.hex() if response is not None else None,
            "raw_buffer_hex": raw_buffer.hex(),
        }
        if response is None:
            item.update({"status": "timeout", "quality": "unavailable"})
            observations.append(item)
            continue
        values, exception_code = decode_register_response(response)
        if exception_code is not None:
            item.update(
                {
                    "status": "modbus_exception",
                    "exception_code": exception_code,
                    "quality": "unavailable",
                }
            )
            observations.append(item)
            continue
        if len(values) != 1:
            item.update({"status": "malformed", "quality": "unavailable"})
            observations.append(item)
            continue
        reading = decode_register(unit_id, register, values[0])
        item.update(
            {
                "status": "ok",
                "raw_value": reading.raw_value,
                "value": reading.value,
                "unit": reading.unit,
                "quality": reading.quality,
                "semantic": reading.semantic,
            }
        )
        observations.append(item)
    return observations


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyserial is required for the AK-CC25 hardware probe") from exc

    selected, protected = resolve_isolated_adapter(
        adapter_path=args.adapter,
        container=args.device_agent_container,
        additional_protected=args.protected_port,
    )
    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
    }
    with serial.Serial(
        port=selected.stable_path,
        baudrate=args.baudrate,
        bytesize=serial.EIGHTBITS,
        parity=parity_map[args.parity],
        stopbits=args.stopbits,
        timeout=min(args.timeout, 0.05),
        write_timeout=args.timeout,
        inter_byte_timeout=0.02,
        exclusive=True,
    ) as port:
        observations = probe_port(port, unit_id=args.unit_id, timeout=args.timeout)

    passed = any(item["status"] == "ok" for item in observations)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe": "nexolab-ak-cc25-pro-read-only",
        "profile_version": PROFILE_VERSION,
        "read_only": True,
        "function_codes": [3],
        "modbus_writes": "none",
        "hardware_writes": "none",
        "production_activation_performed": False,
        "candidate_adapter": asdict(selected),
        "protected_production_ports": list(protected),
        "serial": {
            "baudrate": args.baudrate,
            "parity": args.parity,
            "stopbits": args.stopbits,
            "bytesize": 8,
            "unit_id": args.unit_id,
        },
        "result": "responsive" if passed else "no_confirmed_response",
        "observations": observations,
    }


def default_output() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("runtime/evidence") / f"akcc25-probe-{timestamp}" / "probe.json"


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
        report = run_probe(args)
    except (RuntimeError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    output = args.output or default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"AK-CC25 Pro read-only evidence: {output}")
    print(f"Result: {report['result']}; Modbus writes: none; production activation: false")
    return 0 if report["result"] == "responsive" else 3


if __name__ == "__main__":
    raise SystemExit(main())
