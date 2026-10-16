#!/usr/bin/env python3
"""Read-only effective Docker + API visibility gate for packaged local object storage.

Used by offline acceptance, not a Docker repair tool. Never logs credentials,
executes asset writes, or changes Docker resources.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any


class StorageNetworkError(RuntimeError):
    """The accepted, packaged local object-storage endpoint is not usable."""


def inspect_container(name: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--type", "container", name],
            capture_output=True, text=True, check=True, timeout=8,
        )
        data = json.loads(result.stdout)
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise ValueError("invalid Docker inspect response")
        return data[0]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise StorageNetworkError("Docker object-storage metadata unavailable") from exc


def api_health_probe(api_container: str, storage_alias: str) -> None:
    # Check the real Docker service resolution from inside the central API.
    # The /health GET has no credentials or site asset mutations.
    code = (
        "import socket,urllib.request;"
        f"socket.getaddrinfo({storage_alias!r},9000,type=socket.SOCK_STREAM);"
        f"r=urllib.request.urlopen('http://{storage_alias}:9000/health',timeout=3);"
        "assert r.status==200"
    )
    try:
        subprocess.run(
            ["docker", "exec", api_container, "python3", "-c", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=True, timeout=9,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StorageNetworkError(
            "central API cannot resolve or reach private object-storage health endpoint"
        ) from exc


def verify(
    project: str = "nexolab-central",
    *,
    central_network: str = "nexolab-central",
    expected_bind: str = "127.0.0.1",
    expected_port: int = 9000,
    inspect: Callable[[str], dict[str, Any]] = inspect_container,
    probe: Callable[[str, str], None] = api_health_probe,
) -> dict[str, Any]:
    if (not project or not central_network or not expected_bind
            or not (1 <= expected_port <= 65535)):
        raise StorageNetworkError("invalid expected storage LAN contract")
    storage = inspect(f"{project}-minio-1")
    api = inspect(f"{project}-telemetry-service-1")
    for role, service, item in (
        ("object-storage", "minio", storage),
        ("telemetry-service", "telemetry-service", api),
    ):
        labels = (item.get("Config") or {}).get("Labels") or {}
        if (labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.service") != service):
            raise StorageNetworkError(f"{role}: unexpected Compose ownership")
        if (item.get("State") or {}).get("Running") is not True:
            raise StorageNetworkError(f"{role}: container is not running")
        networks = (item.get("NetworkSettings") or {}).get("Networks") or {}
        if central_network not in networks:
            raise StorageNetworkError(f"{role}: central Docker network is absent")

    aliases = (storage["NetworkSettings"]["Networks"][central_network].get("Aliases")
               or [])
    if "minio" not in aliases:
        raise StorageNetworkError("object-storage: private minio DNS alias missing")

    expected = {"HostIp": expected_bind, "HostPort": str(expected_port)}
    key = "9000/tcp"
    configured = (storage.get("HostConfig") or {}).get("PortBindings") or {}
    published = (storage.get("NetworkSettings") or {}).get("Ports") or {}
    if expected not in (configured.get(key) or []):
        raise StorageNetworkError("object-storage: expected published port not configured")
    if expected not in (published.get(key) or []):
        raise StorageNetworkError("object-storage: Docker published port missing")

    probe(f"{project}-telemetry-service-1", "minio")
    return {
        "status": "verified", "service": "minio",
        "project": project, "central_network": central_network,
        "api_dns_health": "reachable", "published_port": expected_port,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="nexolab-central")
    parser.add_argument("--central-network", default="nexolab-central")
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    try:
        outcome = verify(
            project=args.project, central_network=args.central_network,
            expected_bind=args.bind, expected_port=args.port,
        )
    except StorageNetworkError as exc:
        print(json.dumps({"status": "not_ready", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
