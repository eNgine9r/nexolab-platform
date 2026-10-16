#!/usr/bin/env python3
"""Fail-closed READ-ONLY physical-LAN vs Docker bridge CIDR acceptance gate.

This never edits Docker, host networking, routing, firewall, secrets or devices.
Run before declaring an offline packaged NEXOLAB runtime network-safe.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from typing import Any

VIRTUAL_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "tailscale", "wg",
    "tun", "tap", "zt", "cni", "flannel", "vxlan", "dummy",
)


class NetworkPreflightError(RuntimeError):
    """Unsafe, incomplete or conflicting local IPv4 routing inventory."""


def command(args: list[str], *, timeout: int = 10) -> str:
    try:
        process = subprocess.run(
            args, capture_output=True, text=True, check=True, timeout=timeout,
        )
        return process.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise NetworkPreflightError("required local network inventory unavailable") from exc


def load_inventory() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        physical = json.loads(command(["ip", "-j", "-4", "addr", "show"]))
        network_ids = command(["docker", "network", "ls", "--quiet"]).split()
        if not network_ids:
            raise NetworkPreflightError("Docker network inventory is empty")
        docker = json.loads(command(["docker", "network", "inspect", *network_ids], timeout=20))
    except (ValueError, TypeError) as exc:
        raise NetworkPreflightError("invalid network inventory JSON") from exc
    if not isinstance(physical, list) or not isinstance(docker, list):
        raise NetworkPreflightError("unexpected network inventory structure")
    if len(docker) != len(network_ids):
        raise NetworkPreflightError("incomplete Docker network inspection")
    return physical, docker


def cidr(value: Any, description: str) -> ipaddress.IPv4Network:
    if not isinstance(value, str) or not value.strip():
        raise NetworkPreflightError(f"{description}: invalid IPv4 CIDR")
    try:
        result = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise NetworkPreflightError(f"{description}: invalid IPv4 CIDR") from exc
    if not isinstance(result, ipaddress.IPv4Network):
        raise NetworkPreflightError(f"{description}: unsupported IPv6 CIDR")
    return result


def inspect_lan_interfaces(
    interfaces: list[dict[str, Any]],
) -> list[tuple[str, ipaddress.IPv4Network]]:
    physical: list[tuple[str, ipaddress.IPv4Network]] = []
    for interface in interfaces:
        if not isinstance(interface, dict) or not isinstance(interface.get("ifname"), str):
            raise NetworkPreflightError("invalid host network interface")
        name = interface["ifname"]
        addresses = interface.get("addr_info") or []
        if not isinstance(addresses, list):
            raise NetworkPreflightError("invalid host IPv4 address list")
        if name.startswith(VIRTUAL_PREFIXES):
            continue
        for address in addresses:
            if not isinstance(address, dict):
                raise NetworkPreflightError("invalid host interface address")
            if address.get("family") != "inet":
                continue
            ip_text = address.get("local")
            length = address.get("prefixlen")
            if not isinstance(length, int) or isinstance(length, bool):
                raise NetworkPreflightError("invalid host IPv4 prefix length")
            network = cidr(f"{ip_text}/{length}", "host IPv4 interface")
            ip = ipaddress.IPv4Address(ip_text)
            if ip.is_loopback or ip.is_unspecified:
                continue
            physical.append((name, network))
    return sorted(set(physical), key=lambda x: (x[0], str(x[1])))


def analyze(
    interfaces: list[dict[str, Any]],
    docker_networks: list[dict[str, Any]],
    *,
    allow_no_lan: bool = False,
) -> dict[str, Any]:
    physical = inspect_lan_interfaces(interfaces)
    bridges: list[tuple[str, ipaddress.IPv4Network]] = []
    for network in docker_networks:
        if not isinstance(network, dict):
            raise NetworkPreflightError("invalid Docker network item")
        if network.get("Driver") != "bridge":
            continue
        name = network.get("Name")
        configs = (network.get("IPAM") or {}).get("Config") or []
        if not isinstance(name, str) or not name or not isinstance(configs, list):
            raise NetworkPreflightError("invalid bridge/IPAM inventory")
        if not configs:
            raise NetworkPreflightError("Docker bridge has no IPAM configuration")
        for config in configs:
            if not isinstance(config, dict):
                raise NetworkPreflightError("invalid bridge/IPAM entry")
            subnet = config.get("Subnet")
            if subnet is None:
                raise NetworkPreflightError("Docker bridge IPAM subnet missing")
            if ":" in str(subnet):
                continue
            bridges.append((name, cidr(subnet, "Docker bridge subnet")))
    if not bridges:
        raise NetworkPreflightError("no IPv4 Docker bridge IPAM found")
    if not physical and not allow_no_lan:
        raise NetworkPreflightError("no physical IPv4 LAN found; not verified")
    conflicts = [
        {"lan_interface": iface, "lan_cidr": str(lan),
         "docker_network": name, "docker_cidr": str(bridge)}
        for iface, lan in physical
        for name, bridge in bridges
        if lan.overlaps(bridge)
    ]
    return {
        "status": "conflict" if conflicts else "verified",
        "read_only": True,
        "physical_ipv4": [
            {"interface": name, "subnet": str(subnet)} for name, subnet in physical
        ],
        "docker_ipv4_bridges": [
            {"network": name, "subnet": str(subnet)}
            for name, subnet in sorted(set(bridges), key=lambda x: (x[0], str(x[1])))
        ],
        "conflicts": conflicts,
        "lan_absent_explicitly_allowed": bool(not physical and allow_no_lan),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-no-lan", action="store_true",
        help="Only for independently verified disconnected loopback-only acceptance",
    )
    args = parser.parse_args()
    try:
        payload = analyze(*load_inventory(), allow_no_lan=args.allow_no_lan)
    except NetworkPreflightError as exc:
        print(json.dumps({
            "status": "not_verified", "read_only": True, "reason": str(exc),
        }, sort_keys=True))
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
