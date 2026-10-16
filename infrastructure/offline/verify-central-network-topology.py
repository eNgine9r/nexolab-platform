#!/usr/bin/env python3
"""Read-only LAN Docker topology and broker reachability gate.

Checks *deployed containers*, not merely a valid Compose YAML. Deliberately
never creates networks, restarts services, touches volumes, or publishes MQTT.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

PROJECT = "nexolab-central"
SERVICES = ("mqtt", "telemetry-service", "postgres")
BROKER_PROBE = (
    "import socket; "
    "answers=socket.getaddrinfo('mqtt',1883,type=socket.SOCK_STREAM); "
    "addr=answers[0][4]; "
    "s=socket.create_connection(addr,timeout=3); s.close()"
)


class NetworkTopologyError(Exception):
    """An unexpected or unverified active network topology."""


def inspect_container(project: str, service: str) -> dict[str, Any]:
    name = f"{project}-{service}-1"
    try:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", name],
            check=True, capture_output=True, text=True, timeout=6,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ValueError("unexpected Docker inspect response")
        return payload[0]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise NetworkTopologyError(f"{service}: Docker inspect unavailable or invalid") from exc


def probe_api_broker(project: str) -> None:
    try:
        subprocess.run(
            ["docker", "exec", f"{project}-telemetry-service-1",
             "python3", "-c", BROKER_PROBE],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkTopologyError(
            "telemetry-service: broker name mqtt cannot be resolved/reached over TCP"
        ) from exc


def verify_topology(
    project: str = PROJECT,
    *,
    central_network: str | None = None,
    standalone_network: str = "nexolab-standalone-runtime",
    mode: str = "lan",
    inspector: Callable[[str, str], dict[str, Any]] = inspect_container,
    probe: Callable[[str], None] = probe_api_broker,
) -> dict[str, Any]:
    if mode not in ("lan", "standalone", "central"):
        raise NetworkTopologyError("unsupported runtime mode")
    if not project or not all(c.isalnum() or c in "-_" for c in project):
        raise NetworkTopologyError("invalid Compose project name")
    central = central_network or project
    if not central or not standalone_network or central == standalone_network:
        raise NetworkTopologyError("invalid or overlapping runtime network names")

    expected = {
        "mqtt": {central},
        "telemetry-service": {central},
        "postgres": {central},
    }
    if mode in ("lan", "standalone"):
        expected["mqtt"].add(standalone_network)
        expected["telemetry-service"].add(standalone_network)

    checked = {}
    for service in SERVICES:
        item = inspector(project, service)
        labels = (item.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != project or labels.get(
            "com.docker.compose.service"
        ) != service:
            raise NetworkTopologyError(f"{service}: wrong Compose ownership")
        if (item.get("State") or {}).get("Running") is not True:
            raise NetworkTopologyError(f"{service}: not running")
        networks = (item.get("NetworkSettings") or {}).get("Networks") or {}
        if not isinstance(networks, dict):
            raise NetworkTopologyError(f"{service}: invalid Docker network map")
        missing = sorted(expected[service] - networks.keys())
        if missing:
            raise NetworkTopologyError(
                f"{service}: missing required private Docker networks: {', '.join(missing)}"
            )
        if service == "mqtt":
            required_aliases = {central: "mqtt"}
            if mode in ("lan", "standalone"):
                required_aliases[standalone_network] = "central-mqtt"
            for network, required in required_aliases.items():
                aliases = networks[network].get("Aliases") or []
                if required not in aliases:
                    raise NetworkTopologyError(
                        f"mqtt: expected broker alias {required} absent on {network}"
                    )
        checked[service] = sorted(networks)

    probe(project)
    return {"status": "verified", "mode": mode, "compose_project": project,
            "networks": checked, "broker_dns_tcp": "reachable"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--central-network", default=None)
    parser.add_argument("--standalone-network", default="nexolab-standalone-runtime")
    parser.add_argument("--mode", choices=("lan", "standalone", "central"), default="lan")
    args = parser.parse_args()
    try:
        output = verify_topology(
            project=args.project, central_network=args.central_network,
            standalone_network=args.standalone_network, mode=args.mode,
        )
    except NetworkTopologyError as exc:
        print(json.dumps({"status": "not_ready", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
