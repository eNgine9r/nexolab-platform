#!/usr/bin/env python3
"""#1468: emit numeric-only offline LAN access gauges after read-only probe.

Use only from a separately validated, opt-in local systemd instance. No
network/hardware writes; the output file is local observability data only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from typing import Any

PROBE_SOURCE = Path(__file__).with_name("inspect-site-lan-access.py")
FIXED_NAME = "lan-access.prom"
METRICS = {
    "dashboard": "nexolab_lan_access_dashboard_ok",
    "login_form": "nexolab_lan_access_login_form_ok",
    "api_readiness": "nexolab_lan_access_api_ready",
    "unauthenticated_session_protected": "nexolab_lan_access_session_401_protected",
    "exact_lan_cors": "nexolab_lan_access_session_cors_exact",
}


class CollectorBlocked(ValueError):
    pass


def render(result: dict[str, Any], now: int) -> bytes:
    checks = result.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(METRICS):
        raise CollectorBlocked("invalid_readonly_probe_contract")
    if (result.get("read_only") is not True
        or result.get("site_mutation") is not False
        or result.get("browser_login_verified") is not False
        or result.get("hardware_verified") is not False):
        raise CollectorBlocked("unexpected_unsafe_probe_contract")
    if result.get("status") not in ("BLOCKED", "LOCAL_LAN_AUTH_PATH_REACHABLE"):
        raise CollectorBlocked("unknown_probe_status")
    if not all(type(value) is bool for value in checks.values()):
        raise CollectorBlocked("unexpected_non_boolean_probe_values")
    success = result["status"] == "LOCAL_LAN_AUTH_PATH_REACHABLE"
    if success != all(checks.values()):
        raise CollectorBlocked("positive_probe_status_contradicts_checks")
    if not 1_700_000_000 <= now <= 4_102_444_800:
        raise CollectorBlocked("invalid_current_timestamp")
    rows = [
        "# HELP nexolab_lan_access_probe_last_run_timestamp_seconds Last completed local access probe in Unix seconds.",
        "# TYPE nexolab_lan_access_probe_last_run_timestamp_seconds gauge",
        f"nexolab_lan_access_probe_last_run_timestamp_seconds {now}",
        "# HELP nexolab_lan_access_all_checks_ok Unauthenticated original LAN access chain passed.",
        "# TYPE nexolab_lan_access_all_checks_ok gauge",
        f"nexolab_lan_access_all_checks_ok {int(success)}",
    ]
    for key, metric in METRICS.items():
        rows.extend([
            f"# HELP {metric} {key.replace('_', ' ')} access check.",
            f"# TYPE {metric} gauge",
            f"{metric} {int(checks[key])}",
        ])
    return ("\n".join(rows) + "\n").encode("ascii")


def atomic_publish(destination: Path, payload: bytes) -> None:
    if destination.name != FIXED_NAME or len(payload) > 4096 or not payload.endswith(b"\n"):
        raise CollectorBlocked("unsafe_observability_output")
    parent = destination.parent
    mode = parent.lstat().st_mode
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        raise CollectorBlocked("unsafe_observability_directory")
    if destination.exists() or destination.is_symlink():
        target_mode = destination.lstat().st_mode
        if not stat.S_ISREG(target_mode):
            raise CollectorBlocked("unsafe_existing_metrics_target")
    fd, tempname = tempfile.mkstemp(prefix=".lan-access-", suffix=".tmp", dir=parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tempname, destination)
        dirfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.lexists(tempname):
            os.unlink(tempname)


def run(host: str, output: Path, *, now: int | None = None) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("nexolab_lan_access_probe", PROBE_SOURCE)
    if spec is None or spec.loader is None:
        raise CollectorBlocked("missing_readonly_probe_source")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Reuse exactly the fixed paths and existing private literal IPv4 check.
    result = mod.evaluate(host)
    data = render(result, int(time.time()) if now is None else now)
    atomic_publish(output, data)
    return {"status": "RECORDED", "probe_status": result["status"],
            "mutated_site": False, "read_only_network": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = run(args.host, args.output)
    except (CollectorBlocked, OSError, ValueError):
        print(json.dumps({"status": "BLOCKED", "mutated_site": False,
                          "read_only_network": True}, sort_keys=True))
        return 78
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
