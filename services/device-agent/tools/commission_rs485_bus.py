from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

SERIAL_ROOT = Path("/dev/serial/by-id")
SAFE_UDEV_KEYS = (
    "ID_VENDOR_ID",
    "ID_MODEL_ID",
    "ID_SERIAL_SHORT",
    "ID_VENDOR_FROM_DATABASE",
    "ID_MODEL_FROM_DATABASE",
)


@dataclass(frozen=True)
class AdapterEvidence:
    stable_path: str
    real_path: str
    symlink_target: str
    udev: dict[str, str]


def _read_udev(real_path: Path) -> dict[str, str]:
    if shutil.which("udevadm") is None:
        return {}
    result = subprocess.run(
        ["udevadm", "info", "--query=property", "--name", str(real_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in SAFE_UDEV_KEYS:
            properties[key] = value
    return properties


def inventory_adapters(root: Path = SERIAL_ROOT) -> tuple[AdapterEvidence, ...]:
    if not root.is_dir():
        return ()
    evidence: list[AdapterEvidence] = []
    for path in sorted(root.iterdir()):
        if not path.is_symlink():
            continue
        try:
            target = path.readlink()
            real_path = path.resolve(strict=True)
        except OSError:
            continue
        evidence.append(
            AdapterEvidence(
                stable_path=str(path),
                real_path=str(real_path),
                symlink_target=str(target),
                udev=_read_udev(real_path),
            )
        )
    return tuple(evidence)


def select_new_adapter(
    adapters: Sequence[AdapterEvidence],
    *,
    existing_port: str | None,
    requested_port: str | None,
) -> AdapterEvidence:
    by_path = {item.stable_path: item for item in adapters}
    if requested_port:
        if requested_port not in by_path:
            raise ValueError("Requested adapter is not an enumerated stable by-id path")
        selected = by_path[requested_port]
    else:
        candidates = [item for item in adapters if item.stable_path != existing_port]
        if len(candidates) != 1:
            raise ValueError(
                "Cannot select the new adapter unambiguously; pass --adapter explicitly"
            )
        selected = candidates[0]
    if existing_port and selected.stable_path == existing_port:
        raise ValueError("Refusing to scan the existing production RS-485 adapter")
    return selected


def busy_pids(stable_path: str) -> tuple[str, ...]:
    if shutil.which("fuser") is None:
        raise RuntimeError("fuser is required before an active RS-485 scan")
    result = subprocess.run(
        ["fuser", stable_path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"fuser failed for {stable_path}")
    tokens = (result.stdout + " " + result.stderr).replace(":", " ").split()
    return tuple(token for token in tokens if token.isdigit())


def scanner_path() -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    return repository_root / "tools" / "rs485_discovery" / "scan_rs485.py"


def build_scan_command(
    adapter: AdapterEvidence,
    *,
    output: Path,
    unit_ids: str,
    full: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(scanner_path()),
        "--port",
        adapter.stable_path,
        "--deep",
        "--progress",
        "--unit-ids",
        unit_ids,
        "--output",
        str(output),
    ]
    if not full:
        command.append("--quick")
    return command


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Inventory a candidate second RS-485 adapter and optionally run "
            "the repository read-only Modbus discovery scanner."
        )
    )
    result.add_argument("--existing-port", help="Stable by-id path used by Bus 1")
    result.add_argument("--adapter", help="Stable by-id path to commission as Bus 2")
    result.add_argument("--scan", action="store_true", help="Run read-only discovery")
    result.add_argument("--full", action="store_true", help="Use full serial profile scan")
    result.add_argument("--unit-ids", default="1-247")
    result.add_argument(
        "--output-root",
        type=Path,
        default=Path("runtime/evidence"),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    adapters = inventory_adapters()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = args.output_root / f"rs485-bus2-{timestamp}"
    _write_json(evidence_dir / "adapters.json", [asdict(item) for item in adapters])

    print("Enumerated stable RS-485/serial adapters:")
    if not adapters:
        print("  none")
    for item in adapters:
        marker = " (existing Bus 1)" if item.stable_path == args.existing_port else ""
        print(f"  {item.stable_path} -> {item.real_path}{marker}")
    print(f"Inventory evidence: {evidence_dir / 'adapters.json'}")

    if not args.scan:
        print("No scan requested. Physical hardware remains unverified.")
        return 0

    try:
        adapter = select_new_adapter(
            adapters,
            existing_port=args.existing_port,
            requested_port=args.adapter,
        )
        pids = busy_pids(adapter.stable_path)
        if pids:
            raise RuntimeError(
                "Refusing to scan an adapter owned by another process: "
                + ", ".join(pids)
            )
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    discovery_path = evidence_dir / "discovery.json"
    command = build_scan_command(
        adapter,
        output=discovery_path,
        unit_ids=args.unit_ids,
        full=args.full,
    )
    print(f"Running read-only discovery on {adapter.stable_path}")
    completed = subprocess.run(command, check=False)
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "existing_port": args.existing_port,
        "candidate_bus2": asdict(adapter),
        "discovery_report": str(discovery_path),
        "scanner_exit_code": completed.returncode,
        "production_activation_performed": False,
    }
    _write_json(evidence_dir / "commissioning-summary.json", summary)
    print(f"Commissioning evidence: {evidence_dir}")
    print("Production Bus 2 was NOT activated or written to any controller.")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
