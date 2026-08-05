#!/usr/bin/env python3
"""Capture sanitized, read-only Raspberry Pi acquisition acceptance evidence.

The collector performs HTTP GET requests only. It never opens a serial port and
contains no Modbus write path. Each invocation captures one bounded phase and
appends it to a machine-readable evidence file for Issue #289.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
CLASSIFICATION = "hardware"
COMPLETION_PENDING = "software verified; hardware performance acceptance pending"
DEFAULT_PHASES = (
    "no-browser",
    "overview",
    "live-dashboard",
    "route-transitions",
    "multiple-browsers",
    "websocket-reconnect",
    "unavailable-endpoint",
    "mqtt-outbox-drain",
)
_NODE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class EvidenceError(RuntimeError):
    """Raised when evidence cannot be captured or validated truthfully."""


@dataclass(frozen=True)
class CpuSample:
    idle: int
    total: int


def _get_path(payload: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, float(default)))


def sanitize_node_id(value: str) -> str:
    normalized = _NODE_ID_PATTERN.sub("-", value.strip()).strip("-._")
    if not normalized:
        raise EvidenceError("node_id must contain a safe non-empty identifier")
    return normalized[:64]


def fetch_json(url: str, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "nexolab-hardware-acceptance/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise EvidenceError(f"GET {url} returned HTTP {response.status}")
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise EvidenceError(f"GET {url} failed: {error}") from error
    if not isinstance(payload, dict):
        raise EvidenceError(f"GET {url} did not return a JSON object")
    return payload


def read_cpu_sample(path: Path = Path("/proc/stat")) -> CpuSample:
    first = path.read_text(encoding="utf-8").splitlines()[0].split()
    if not first or first[0] != "cpu" or len(first) < 5:
        raise EvidenceError("Unable to parse /proc/stat CPU counters")
    values = [int(value) for value in first[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuSample(idle=idle, total=sum(values))


def cpu_percent(before: CpuSample, after: CpuSample) -> float:
    total_delta = after.total - before.total
    idle_delta = after.idle - before.idle
    if total_delta <= 0 or idle_delta < 0:
        raise EvidenceError("CPU counters did not advance monotonically")
    return round(
        max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)),
        3,
    )


def memory_rss_bytes(pid: int | None) -> int:
    if pid is None:
        return 0
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        raise EvidenceError(f"PID {pid} does not exist")
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            return int(fields[1]) * 1024
    raise EvidenceError(f"PID {pid} does not expose VmRSS")


def _scheduler_bus(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
    buses = _get_path(metrics, "acquisition", "scheduler", "buses", default={})
    if not isinstance(buses, Mapping) or not buses:
        return {}
    first_key = sorted(str(key) for key in buses)[0]
    value = buses.get(first_key, {})
    return value if isinstance(value, Mapping) else {}


def _outcomes(metrics: Mapping[str, Any]) -> dict[str, int]:
    value = _get_path(metrics, "acquisition", "normal", "outcomes", default={})
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _integer(item) for key, item in sorted(value.items())}


def _delta(after: Any, before: Any) -> int:
    value = _integer(after) - _integer(before)
    if value < 0:
        raise EvidenceError("Monotonic counter decreased during phase capture")
    return value


def _float_delta(after: Any, before: Any) -> float:
    value = _number(after) - _number(before)
    if value < -1e-9:
        raise EvidenceError("Monotonic duration counter decreased during phase capture")
    return round(max(0.0, value), 6)


def _outcome_delta(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, int]:
    before_outcomes = _outcomes(before)
    after_outcomes = _outcomes(after)
    return {
        key: _delta(after_outcomes.get(key, 0), before_outcomes.get(key, 0))
        for key in sorted(set(before_outcomes) | set(after_outcomes))
    }


def _service_counter(metrics: Mapping[str, Any], operation: str, field: str) -> int:
    return _integer(
        _get_path(
            metrics,
            "acquisition",
            "service_operations",
            operation,
            field,
            default=0,
        )
    )


def _outbox_depth(*payloads: Mapping[str, Any]) -> int:
    candidate_paths = (
        ("outbox", "depth"),
        ("queue", "depth"),
        ("health", "outbox_depth"),
        ("acquisition", "outbox_depth"),
    )
    for payload in payloads:
        for path in candidate_paths:
            value = _get_path(payload, *path, default=None)
            if value is not None:
                return _integer(value)
    return 0


def _ingestion_p95(*payloads: Mapping[str, Any]) -> float:
    candidate_paths = (
        ("delivery", "ingestion_to_websocket_latency_ms", "p95"),
        ("telemetry", "ingestion_to_websocket_p95_ms"),
        ("ingestion", "websocket_latency_p95_ms"),
    )
    for payload in payloads:
        for path in candidate_paths:
            value = _get_path(payload, *path, default=None)
            if value is not None:
                return round(_number(value), 3)
    return 0.0


def build_phase_evidence(
    *,
    name: str,
    window_seconds: float,
    before_metrics: Mapping[str, Any],
    after_metrics: Mapping[str, Any],
    health: Mapping[str, Any],
    ready: Mapping[str, Any],
    cpu_usage_percent: float,
    rss_bytes: int,
    disk_free_bytes: int,
) -> dict[str, Any]:
    before_bus = _scheduler_bus(before_metrics)
    after_bus = _scheduler_bus(after_metrics)
    busy_delta = _float_delta(
        _get_path(
            after_metrics,
            "acquisition",
            "normal",
            "bus_busy_seconds_total",
            default=0,
        ),
        _get_path(
            before_metrics,
            "acquisition",
            "normal",
            "bus_busy_seconds_total",
            default=0,
        ),
    )
    utilization = round(min(100.0, busy_delta / window_seconds * 100.0), 3)
    return {
        "name": name,
        "window_seconds": round(window_seconds, 3),
        "normal_physical_requests_delta": _delta(
            _get_path(
                after_metrics,
                "acquisition",
                "normal",
                "physical_requests_total",
                default=0,
            ),
            _get_path(
                before_metrics,
                "acquisition",
                "normal",
                "physical_requests_total",
                default=0,
            ),
        ),
        "retry_attempts_delta": _delta(
            _get_path(
                after_metrics,
                "acquisition",
                "normal",
                "retry_attempts_total",
                default=0,
            ),
            _get_path(
                before_metrics,
                "acquisition",
                "normal",
                "retry_attempts_total",
                default=0,
            ),
        ),
        "outcomes_delta": _outcome_delta(before_metrics, after_metrics),
        "bus_busy_seconds_delta": busy_delta,
        "bus_utilization_percent": utilization,
        "scheduler_lag_max_seconds": round(
            _number(
                _get_path(
                    after_bus,
                    "scheduler_lag_seconds",
                    "maximum",
                    default=0,
                )
            ),
            6,
        ),
        "missed_deadlines_delta": _delta(
            after_bus.get("missed_deadline_total", 0),
            before_bus.get("missed_deadline_total", 0),
        ),
        "overruns_delta": _delta(
            after_bus.get("overrun_total", 0),
            before_bus.get("overrun_total", 0),
        ),
        "deferred_delta": _delta(
            after_bus.get("deferred_total", 0),
            before_bus.get("deferred_total", 0),
        ),
        "cpu_percent": round(cpu_usage_percent, 3),
        "memory_rss_bytes": int(rss_bytes),
        "disk_free_bytes": int(disk_free_bytes),
        "outbox_depth": _outbox_depth(after_metrics, health, ready),
        "ingestion_to_websocket_p95_ms": _ingestion_p95(
            after_metrics, health, ready
        ),
        "health_status": str(health.get("status", "unknown")),
        "ready_status": str(ready.get("status", "unknown")),
    }


def _base_evidence(source_commit: str, node_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "classification": CLASSIFICATION,
        "completion_classification": COMPLETION_PENDING,
        "source_commit": source_commit,
        "node_id": sanitize_node_id(node_id),
        "phases": [],
        "discovery_delta": 0,
        "configuration_mutation_delta": 0,
        "modbus_write_attempts": 0,
        "safety": {
            "http_methods": ["GET"],
            "serial_port_opened": False,
            "modbus_write_attempts": 0,
            "production_cutover": False,
        },
    }


def load_evidence(
    path: Path, *, source_commit: str, node_id: str
) -> dict[str, Any]:
    if not path.exists():
        return _base_evidence(source_commit, node_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceError("Evidence file must contain a JSON object")
    if payload.get("source_commit") != source_commit:
        raise EvidenceError("Evidence source_commit does not match this capture")
    if payload.get("node_id") != sanitize_node_id(node_id):
        raise EvidenceError("Evidence node_id does not match this capture")
    return payload


def append_phase(
    evidence: dict[str, Any],
    phase: dict[str, Any],
    *,
    discovery_delta: int,
    configuration_delta: int,
) -> dict[str, Any]:
    phases = evidence.setdefault("phases", [])
    if not isinstance(phases, list):
        raise EvidenceError("Evidence phases must be a list")
    if any(
        isinstance(item, Mapping) and item.get("name") == phase["name"]
        for item in phases
    ):
        raise EvidenceError(f"Phase {phase['name']!r} already exists")
    phases.append(phase)
    evidence["discovery_delta"] = (
        _integer(evidence.get("discovery_delta")) + discovery_delta
    )
    evidence["configuration_mutation_delta"] = _integer(
        evidence.get("configuration_mutation_delta")
    ) + configuration_delta
    evidence["modbus_write_attempts"] = 0
    return evidence


def validate_evidence(
    evidence: Mapping[str, Any], *, require_complete: bool
) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if evidence.get("classification") != CLASSIFICATION:
        errors.append("classification must be hardware")
    if _integer(evidence.get("modbus_write_attempts")) != 0:
        errors.append("modbus_write_attempts must be zero")
    if _integer(evidence.get("configuration_mutation_delta")) != 0:
        errors.append("configuration_mutation_delta must be zero")
    phases = evidence.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("at least one phase is required")
        phases = []
    names: list[str] = []
    for phase in phases:
        if not isinstance(phase, Mapping):
            errors.append("every phase must be an object")
            continue
        name = str(phase.get("name", ""))
        names.append(name)
        if _number(phase.get("window_seconds")) <= 0:
            errors.append(f"phase {name}: window_seconds must be positive")
        if _integer(phase.get("normal_physical_requests_delta")) < 0:
            errors.append(f"phase {name}: request delta must be non-negative")
        if _integer(phase.get("memory_rss_bytes")) < 0:
            errors.append(f"phase {name}: memory_rss_bytes must be non-negative")
        if _integer(phase.get("disk_free_bytes")) <= 0:
            errors.append(f"phase {name}: disk_free_bytes must be positive")
    if len(names) != len(set(names)):
        errors.append("phase names must be unique")
    if require_complete:
        missing = [name for name in DEFAULT_PHASES if name not in names]
        if missing:
            errors.append(f"missing required phases: {', '.join(missing)}")
    return errors


def capture(args: argparse.Namespace) -> int:
    if args.window_seconds <= 0:
        raise EvidenceError("window_seconds must be positive")
    output = Path(args.output)
    evidence = load_evidence(
        output,
        source_commit=args.source_commit,
        node_id=args.node_id,
    )

    before_metrics = fetch_json(
        args.metrics_url,
        timeout_seconds=args.timeout_seconds,
    )
    before_discovery = _service_counter(
        before_metrics,
        "discovery",
        "physical_requests_total",
    )
    before_configuration = _service_counter(
        before_metrics,
        "configuration_mutation",
        "requests_total",
    )
    cpu_before = read_cpu_sample()
    time.sleep(args.window_seconds)
    cpu_after = read_cpu_sample()
    after_metrics = fetch_json(
        args.metrics_url,
        timeout_seconds=args.timeout_seconds,
    )
    health = fetch_json(args.health_url, timeout_seconds=args.timeout_seconds)
    ready = fetch_json(args.ready_url, timeout_seconds=args.timeout_seconds)

    phase = build_phase_evidence(
        name=args.phase,
        window_seconds=args.window_seconds,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        health=health,
        ready=ready,
        cpu_usage_percent=cpu_percent(cpu_before, cpu_after),
        rss_bytes=memory_rss_bytes(args.pid),
        disk_free_bytes=shutil.disk_usage(args.disk_path).free,
    )
    discovery_delta = _delta(
        _service_counter(
            after_metrics,
            "discovery",
            "physical_requests_total",
        ),
        before_discovery,
    )
    configuration_delta = _delta(
        _service_counter(
            after_metrics,
            "configuration_mutation",
            "requests_total",
        ),
        before_configuration,
    )
    append_phase(
        evidence,
        phase,
        discovery_delta=discovery_delta,
        configuration_delta=configuration_delta,
    )
    errors = validate_evidence(evidence, require_complete=False)
    if errors:
        raise EvidenceError("; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(phase, sort_keys=True))
    return 0


def validate(args: argparse.Namespace) -> int:
    path = Path(args.input)
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise EvidenceError("Evidence file must contain a JSON object")
    errors = validate_evidence(
        evidence,
        require_complete=args.require_complete,
    )
    if errors:
        raise EvidenceError("; ".join(errors))
    print(
        json.dumps(
            {
                "classification": evidence["classification"],
                "phases": [item["name"] for item in evidence["phases"]],
                "completion_classification": evidence[
                    "completion_classification"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser(
        "capture",
        help="capture one bounded hardware phase",
    )
    capture_parser.add_argument("--phase", required=True)
    capture_parser.add_argument(
        "--metrics-url",
        default="http://127.0.0.1:8081/metrics",
    )
    capture_parser.add_argument(
        "--health-url",
        default="http://127.0.0.1:8081/health",
    )
    capture_parser.add_argument(
        "--ready-url",
        default="http://127.0.0.1:8081/ready",
    )
    capture_parser.add_argument("--window-seconds", type=float, default=60.0)
    capture_parser.add_argument("--timeout-seconds", type=float, default=10.0)
    capture_parser.add_argument("--source-commit", required=True)
    capture_parser.add_argument("--node-id", required=True)
    capture_parser.add_argument("--pid", type=int)
    capture_parser.add_argument("--disk-path", default="/")
    capture_parser.add_argument(
        "--output",
        default="acquisition-hardware-matrix.json",
    )
    capture_parser.set_defaults(func=capture)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate captured evidence",
    )
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--require-complete", action="store_true")
    validate_parser.set_defaults(func=validate)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"hardware acceptance failed: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
