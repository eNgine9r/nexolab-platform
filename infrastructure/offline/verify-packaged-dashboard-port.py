#!/usr/bin/env python3
"""Fail-closed, read-only packaged LAN Dashboard network/port publication gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any


class DashboardNetworkError(Exception):
    """Docker reports a packaged dashboard that is not reachable from the host."""


def inspect_dashboard(project: str) -> dict[str, Any]:
    try:
        raw = subprocess.run(
            ["docker", "inspect", "--type", "container", f"{project}-dashboard-1"],
            check=True, text=True, capture_output=True, timeout=6,
        )
        records = json.loads(raw.stdout)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("unexpected inspect output")
        if not isinstance(records[0], dict):
            raise ValueError("malformed inspect object")
        return records[0]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise DashboardNetworkError("packaged dashboard Docker metadata is unavailable") from exc


def verify_dashboard(
    project: str, central_network: str, bind: str, port: int,
    *, inspector: Callable[[str], dict[str, Any]] = inspect_dashboard,
) -> dict[str, Any]:
    if not project or not central_network or not bind or not 1 <= port <= 65535:
        raise DashboardNetworkError("invalid expected Dashboard binding")
    item = inspector(project)
    labels = (item.get("Config") or {}).get("Labels") or {}
    if labels.get("com.docker.compose.project") != project or labels.get(
        "com.docker.compose.service"
    ) != "dashboard":
        raise DashboardNetworkError("dashboard Docker Compose identity differs")
    state = item.get("State") or {}
    if state.get("Running") is not True:
        raise DashboardNetworkError("packaged dashboard is not running")
    if (item.get("HostConfig") or {}).get("NetworkMode") not in (
        central_network, "default"
    ):
        # For composed multi-network services, the Engine may retain the first
        # Compose network as the main network mode.
        raise DashboardNetworkError("dashboard host network mode differs")

    settings = item.get("NetworkSettings") or {}
    active_networks = settings.get("Networks") or {}
    if central_network not in active_networks:
        raise DashboardNetworkError("dashboard missing required central Docker network")

    key = "3000/tcp"
    expected = {"HostIp": bind, "HostPort": str(port)}
    configured = ((item.get("HostConfig") or {}).get("PortBindings") or {}).get(key)
    published = (settings.get("Ports") or {}).get(key)
    if not isinstance(configured, list) or expected not in configured:
        raise DashboardNetworkError("dashboard configured port binding differs")
    if not isinstance(published, list) or expected not in published:
        raise DashboardNetworkError("dashboard published host port missing or mismatched")

    return {"status": "verified", "service": "dashboard", "project": project,
            "network": central_network, "bind": bind, "port": port}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--central-network", required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    try:
        result = verify_dashboard(args.project, args.central_network, args.bind, args.port)
    except DashboardNetworkError as exc:
        print(json.dumps({"status": "not_ready", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
