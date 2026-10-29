#!/usr/bin/env python3
"""Read-only NEXOLAB #1409 Docker edge subnet-migration inventory.

No network, Docker, route, backup, hardware or filesystem mutation. A locally
non-overlapping candidate is never sufficient to authorize site cutover.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from typing import Any, Callable

EDGE_NETWORK = "nexolab-edge_default"
VIRTUAL_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "tailscale",
    "wg", "tun", "tap", "zt", "cni", "flannel", "vxlan", "dummy",
)


class InventoryBlocked(RuntimeError):
    """Incomplete, invalid or inaccessible networking evidence."""


def command(argv: list[str], timeout: int = 20) -> str:
    try:
        return subprocess.run(
            argv, check=True, capture_output=True, text=True, timeout=timeout
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryBlocked("required_host_inventory_unavailable") from exc


def parse_list(text: str, kind: str) -> list[dict[str, Any]]:
    try:
        result = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise InventoryBlocked("invalid_" + kind + "_json") from exc
    if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
        raise InventoryBlocked("invalid_" + kind + "_items")
    return result


def collect(
    run: Callable[[list[str], int], str] = command,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    addresses = parse_list(run(["ip", "-j", "-4", "addr", "show"], 15), "addresses")
    routes = parse_list(run(["ip", "-j", "-4", "route", "show", "table", "all"], 15), "routes")
    ids = run(["docker", "network", "ls", "--quiet"], 15).split()
    if not ids or len(ids) != len(set(ids)):
        raise InventoryBlocked("missing_or_duplicate_docker_network_ids")
    networks = parse_list(run(["docker", "network", "inspect", *ids], 25), "docker_networks")
    if len(networks) != len(ids):
        raise InventoryBlocked("partial_docker_network_inventory")
    return addresses, routes, networks


def ipv4(value: Any, context: str) -> ipaddress.IPv4Network:
    if not isinstance(value, str) or not value:
        raise InventoryBlocked("missing_" + context)
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise InventoryBlocked("invalid_" + context) from exc
    if not isinstance(network, ipaddress.IPv4Network):
        raise InventoryBlocked("non_ipv4_" + context)
    return network


def analyze(
    addresses: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    docker_networks: list[dict[str, Any]],
    *,
    candidate: str | None = None,
    reserved: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not addresses or not routes or not docker_networks:
        raise InventoryBlocked("incomplete_host_inventory")

    physical: list[tuple[str, ipaddress.IPv4Network]] = []
    host_addresses: list[tuple[str, ipaddress.IPv4Network]] = []
    for entry in addresses:
        if not isinstance(entry, dict) or not isinstance(entry.get("ifname"), str):
            raise InventoryBlocked("invalid_interface_inventory")
        name = entry["ifname"]
        values = entry.get("addr_info")
        if not isinstance(values, list):
            raise InventoryBlocked("invalid_interface_addresses")
        for item in values:
            if not isinstance(item, dict):
                raise InventoryBlocked("invalid_interface_address")
            if item.get("family") != "inet":
                continue
            ip = item.get("local")
            prefix = item.get("prefixlen")
            if not isinstance(prefix, int) or isinstance(prefix, bool):
                raise InventoryBlocked("invalid_interface_prefix")
            address = ipv4(f"{ip}/{prefix}", "interface_subnet")
            host_addresses.append((name, address))
            if not name.startswith(VIRTUAL_PREFIXES) and not address.is_loopback:
                physical.append((name, address))
    if not physical:
        raise InventoryBlocked("physical_lan_missing")
    if not host_addresses:
        raise InventoryBlocked("host_ipv4_addresses_missing")

    known_routes: list[tuple[str, ipaddress.IPv4Network]] = []
    default_count = 0
    for item in routes:
        if not isinstance(item, dict):
            raise InventoryBlocked("invalid_route_inventory")
        dst = item.get("dst")
        if dst == "default":
            default_count += 1
            continue
        route = ipv4(dst, "route_destination")
        known_routes.append((str(item.get("dev") or item.get("table") or "route"), route))
    if default_count == 0:
        raise InventoryBlocked("default_route_missing")
    bridges: list[tuple[str, ipaddress.IPv4Network]] = []
    target_found = False
    for item in docker_networks:
        if not isinstance(item, dict) or not isinstance(item.get("Name"), str):
            raise InventoryBlocked("invalid_docker_network_inventory")
        name = item["Name"]
        if name == EDGE_NETWORK:
            target_found = True
            if item.get("Driver") != "bridge":
                raise InventoryBlocked("edge_network_is_not_bridge")
        if item.get("Driver") != "bridge":
            continue
        ipam = item.get("IPAM")
        configs = ipam.get("Config") if isinstance(ipam, dict) else None
        if not isinstance(configs, list) or not configs:
            raise InventoryBlocked("missing_bridge_ipam")
        for config in configs:
            if not isinstance(config, dict):
                raise InventoryBlocked("invalid_bridge_ipam")
            subnet = config.get("Subnet")
            if isinstance(subnet, str) and ":" in subnet:
                continue
            bridges.append((name, ipv4(subnet, "bridge_subnet")))
    if not target_found or not any(name == EDGE_NETWORK for name, _ in bridges):
        raise InventoryBlocked("edge_network_not_found")
    if not bridges:
        raise InventoryBlocked("docker_ipv4_bridges_missing")

    known_overlaps = [
        {"interface": n, "lan": str(lan), "docker": d, "docker_cidr": str(bridge)}
        for n, lan in physical for d, bridge in bridges if lan.overlaps(bridge)
    ]
    result: dict[str, Any] = {
        "status": "existing_cidr_conflict" if known_overlaps else "inventory_collected",
        "read_only": True, "mutation_performed": False,
        "site_cutover_authorized": False,
        "site_reservations_verified": False,
        "physical_ipv4": [{"interface": n, "cidr": str(net)}
                          for n, net in sorted(set(physical), key=lambda x: (x[0], str(x[1])))],
        "host_ipv4": [{"interface": n, "cidr": str(net)}
                      for n, net in sorted(set(host_addresses), key=lambda x: (x[0], str(x[1])))],
        "routes": [{"source": n, "cidr": str(net)}
                   for n, net in sorted(set(known_routes), key=lambda x: (x[0], str(x[1])))],
        "default_routes_present": default_count,
        "docker_bridges": [{"network": n, "cidr": str(net)}
                           for n, net in sorted(set(bridges), key=lambda x: (x[0], str(x[1])))],
        "existing_overlap": known_overlaps,
    }
    if candidate is not None:
        proposal = ipv4(candidate, "candidate")
        if not proposal.is_private or proposal.is_loopback or proposal.is_link_local or proposal.prefixlen < 24:
            raise InventoryBlocked("unsafe_candidate_scope")
        explicit = [ipv4(value, "reserved_cidr") for value in reserved]
        constraints = [
            *[("interface:" + n, net) for n, net in host_addresses],
            *[("route:" + n, net) for n, net in known_routes],
            *[("docker:" + n, net) for n, net in bridges],
            *[("reserved", net) for net in explicit],
        ]
        conflicts = sorted(set(
            (source, str(net)) for source, net in constraints if proposal.overlaps(net)
        ))
        result["candidate"] = str(proposal)
        result["candidate_status"] = (
            "conflict" if conflicts else "locally_disjoint_not_site_approved"
        )
        result["candidate_conflicts"] = [
            {"source": source, "cidr": subnet} for source, subnet in conflicts
        ]
        result["status"] = "candidate_conflict" if conflicts else "candidate_unapproved"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="Only assess this explicitly supplied IPv4 subnet")
    parser.add_argument("--reserved-cidr", action="append", default=[],
                        help="Extra network reserved by the site administrator (repeatable)")
    args = parser.parse_args(argv)
    try:
        report = analyze(*collect(), candidate=args.candidate,
                         reserved=tuple(args.reserved_cidr))
    except InventoryBlocked as exc:
        report = {"status": "blocked", "reason": str(exc), "read_only": True,
                  "mutation_performed": False, "site_cutover_authorized": False}
    print(json.dumps(report, sort_keys=True))
    # No result, including locally disjoint, is approval to change a site network.
    return 1 if report["status"] in {"blocked", "candidate_conflict", "existing_cidr_conflict"} else 0


if __name__ == "__main__":
    sys.exit(main())
