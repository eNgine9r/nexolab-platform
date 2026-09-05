from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SERIAL_ROOT = Path("/dev/serial/by-id")
DEFAULT_DEVICE_AGENT_CONTAINER = "nexolab-edge-device-agent-1"
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


def _host_serial_path(value: str) -> str:
    if value.startswith("/host/dev/"):
        return value.removeprefix("/host")
    return value


def parse_runtime_protected_ports(payload: dict[str, Any]) -> tuple[str, ...]:
    acquisition = payload.get("acquisition")
    if not isinstance(acquisition, dict):
        raise ValueError("Device Agent health is missing acquisition diagnostics")
    buses = acquisition.get("rs485_buses")
    if not isinstance(buses, list) or not buses:
        raise ValueError("Device Agent health reported no RS-485 bus diagnostics")

    ports: list[str] = []
    for index, bus in enumerate(buses):
        if not isinstance(bus, dict):
            raise ValueError(f"RS-485 bus diagnostic {index} is not an object")
        value = bus.get("serial_device")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"RS-485 bus diagnostic {index} is missing serial_device")
        ports.append(_host_serial_path(value.strip()))

    if len(set(ports)) != len(ports):
        raise ValueError("Device Agent health reports duplicate production RS-485 paths")
    return tuple(sorted(ports))


def runtime_protected_ports(
    container: str = DEFAULT_DEVICE_AGENT_CONTAINER,
) -> tuple[str, ...]:
    if shutil.which("docker") is None:
        raise RuntimeError(
            "docker is required to prove current production RS-485 ownership before a scan"
        )
    health_reader = (
        "import urllib.request;"
        "print(urllib.request.urlopen("
        "'http://127.0.0.1:8081/health',timeout=2).read().decode())"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", container, "python3", "-c", health_reader],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out reading current Device Agent bus ownership") from exc
    if result.returncode != 0:
        raise RuntimeError("Unable to read current Device Agent bus ownership")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Device Agent health returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Device Agent health must be a JSON object")
    if payload.get("status") != "ok":
        raise RuntimeError("Current Device Agent health is not ok; refusing active scan")
    try:
        return parse_runtime_protected_ports(payload)
    except ValueError as exc:
        raise RuntimeError(
            "Current Device Agent RS-485 ownership is incomplete; refusing active scan"
        ) from exc


def select_new_adapter(
    adapters: Sequence[AdapterEvidence],
    *,
    protected_ports: Sequence[str],
    requested_port: str | None,
) -> AdapterEvidence:
    protected = {value for value in protected_ports if value}
    if not protected:
        raise ValueError("At least one current production adapter must be protected")
    by_path = {item.stable_path: item for item in adapters}
    missing = sorted(protected - set(by_path))
    if missing:
        raise ValueError(
            "Protected production adapter is not currently enumerated: " + ", ".join(missing)
        )
    if requested_port:
        if requested_port not in by_path:
            raise ValueError("Requested adapter is not an enumerated stable by-id path")
        selected = by_path[requested_port]
    else:
        candidates = [item for item in adapters if item.stable_path not in protected]
        if len(candidates) != 1:
            raise ValueError(
                "Cannot select one unprotected adapter unambiguously; pass --adapter explicitly"
            )
        selected = candidates[0]
    if selected.stable_path in protected:
        raise ValueError("Refusing to scan a current production RS-485 adapter")
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
            "Inventory RS-485 adapters and optionally scan only an adapter that "
            "is proven outside current production ownership."
        )
    )
    result.add_argument(
        "--existing-port",
        action="append",
        default=[],
        help="Legacy/additional production stable path to protect; repeatable",
    )
    result.add_argument(
        "--protected-port",
        action="append",
        default=[],
        help="Additional production stable path to protect; repeatable",
    )
    result.add_argument("--adapter", help="Stable by-id path to commission")
    result.add_argument("--scan", action="store_true", help="Run read-only discovery")
    result.add_argument("--full", action="store_true", help="Use full serial profile scan")
    result.add_argument("--unit-ids", default="1-247")
    result.add_argument(
        "--device-agent-container",
        default=DEFAULT_DEVICE_AGENT_CONTAINER,
        help="Running Device Agent used as production bus-ownership authority",
    )
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
    evidence_dir = args.output_root / f"rs485-commissioning-{timestamp}"
    _write_json(evidence_dir / "adapters.json", [asdict(item) for item in adapters])

    print("Enumerated stable RS-485/serial adapters:")
    if not adapters:
        print("  none")
    for item in adapters:
        print(f"  {item.stable_path} -> {item.real_path}")
    print(f"Inventory evidence: {evidence_dir / 'adapters.json'}")

    if not args.scan:
        print("No scan requested. Physical hardware remains unverified.")
        return 0

    try:
        runtime_ports = runtime_protected_ports(args.device_agent_container)
        protected_ports = tuple(
            sorted(set(runtime_ports) | set(args.existing_port) | set(args.protected_port))
        )
        adapter = select_new_adapter(
            adapters,
            protected_ports=protected_ports,
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
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "protected_production_ports": list(protected_ports),
        "candidate_adapter": asdict(adapter),
        "discovery_report": str(discovery_path),
        "scanner_exit_code": completed.returncode,
        "production_activation_performed": False,
    }
    _write_json(evidence_dir / "commissioning-summary.json", summary)
    print(f"Commissioning evidence: {evidence_dir}")
    print("Production adapters were protected; no controller write or activation occurred.")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
