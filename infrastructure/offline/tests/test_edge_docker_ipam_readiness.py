"""No-side-effect tests for #1409 physical/VPN/Docker route inventory and candidate audit."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "inspect-edge-docker-ipam-readiness.py"
SPEC = importlib.util.spec_from_file_location("nexolab_edge_ipam", SOURCE)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

ADDR = [
    {"ifname": "eth0", "addr_info": [
        {"family": "inet", "local": "172.18.48.66", "prefixlen": 21}]},
    {"ifname": "tailscale0", "addr_info": [
        {"family": "inet", "local": "100.113.204.81", "prefixlen": 32}]},
    {"ifname": "docker0", "addr_info": [
        {"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
]
ROUTES = [
    {"dst": "default", "gateway": "172.18.48.1", "dev": "eth0"},
    {"dst": "172.18.48.0/21", "dev": "eth0"},
    {"dst": "172.18.0.0/16", "dev": "br-edge"},
    {"dst": "100.100.0.0/16", "dev": "tailscale0", "table": "52"},
    {"dst": "10.55.0.0/16", "dev": "tailscale0", "table": "52"},
]
DOCKER = [
    {"Name": "nexolab-edge_default", "Driver": "bridge", "IPAM": {
        "Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]}},
    {"Name": "nexolab-central", "Driver": "bridge", "IPAM": {
        "Config": [{"Subnet": "172.20.0.0/16", "Gateway": "172.20.0.1"}]}},
]


def analyze(*, candidate=None, reserved=(), addresses=None, routes=None, docker=None):
    return module.analyze(
        copy.deepcopy(ADDR if addresses is None else addresses),
        copy.deepcopy(ROUTES if routes is None else routes),
        copy.deepcopy(DOCKER if docker is None else docker),
        candidate=candidate, reserved=reserved,
    )


class IpamReadOnlyTests(unittest.TestCase):
    def test_actual_conflict_detected_without_proposing_new_cidr(self):
        result = analyze()
        self.assertEqual(result["status"], "existing_cidr_conflict")
        self.assertEqual(result["existing_overlap"], [{
            "interface": "eth0", "lan": "172.18.48.0/21",
            "docker": "nexolab-edge_default", "docker_cidr": "172.18.0.0/16",
        }])
        self.assertFalse(result["mutation_performed"])
        self.assertFalse(result["site_cutover_authorized"])

    def test_host_and_vpn_routes_are_retained(self):
        result = analyze()
        self.assertTrue(any(item["source"] == "tailscale0" for item in result["routes"]))
        self.assertTrue(any(item["interface"] == "tailscale0" for item in result["host_ipv4"]))
        self.assertEqual(result["default_routes_present"], 1)

    def test_proposal_cannot_overlap_physical_route(self):
        result = analyze(candidate="172.18.50.0/24")
        self.assertEqual(result["candidate_status"], "conflict")
        self.assertEqual(result["status"], "candidate_conflict")

    def test_proposal_cannot_overlap_vpn_route(self):
        result = analyze(candidate="10.55.20.0/24")
        self.assertEqual(result["candidate_status"], "conflict")
        self.assertTrue(any(x["source"].startswith("route:tailscale")
                            for x in result["candidate_conflicts"]))

    def test_proposal_cannot_overlap_other_docker_bridge(self):
        result = analyze(candidate="172.20.40.0/24")
        self.assertTrue(any(x["source"] == "docker:nexolab-central"
                            for x in result["candidate_conflicts"]))

    def test_reserved_site_blocked(self):
        result = analyze(candidate="10.77.40.0/24", reserved=("10.77.0.0/16",))
        self.assertEqual(result["candidate_status"], "conflict")
        self.assertTrue(any(x["source"] == "reserved" for x in result["candidate_conflicts"]))

    def test_locally_disjoint_candidate_still_never_approved(self):
        result = analyze(candidate="10.77.40.0/24")
        self.assertEqual(result["status"], "candidate_unapproved")
        self.assertEqual(result["candidate_status"], "locally_disjoint_not_site_approved")
        self.assertFalse(result["site_reservations_verified"])
        self.assertFalse(result["site_cutover_authorized"])

    def test_missing_default_route_fails_closed(self):
        with self.assertRaisesRegex(module.InventoryBlocked, "default_route_missing"):
            analyze(routes=ROUTES[1:])

    def test_empty_routes_or_docker_fails_closed(self):
        for routes, docker in (([], DOCKER), (ROUTES, [])):
            with self.subTest(routes=routes, docker=docker):
                with self.assertRaises(module.InventoryBlocked):
                    analyze(routes=routes, docker=docker)

    def test_missing_edge_bridge_fails_closed(self):
        with self.assertRaisesRegex(module.InventoryBlocked, "edge_network_not_found"):
            analyze(docker=DOCKER[1:])

    def test_malformed_route_fails_closed(self):
        with self.assertRaisesRegex(module.InventoryBlocked, "invalid_route_destination"):
            analyze(routes=[*ROUTES, {"dst": "bad-route", "dev": "eth0"}])

    def test_physical_lan_missing_fails_closed(self):
        with self.assertRaisesRegex(module.InventoryBlocked, "physical_lan_missing"):
            analyze(addresses=ADDR[1:])

    def test_bad_candidate_rejected(self):
        for candidate in ("0.0.0.0/0", "172.18.0.0/12", "169.254.0.0/16", "bad"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(module.InventoryBlocked):
                    analyze(candidate=candidate)

    def test_invalid_reservation_rejected(self):
        with self.assertRaisesRegex(module.InventoryBlocked, "invalid_reserved_cidr"):
            analyze(candidate="10.77.40.0/24", reserved=("invalid",))

    def test_readonly_inventory_uses_only_ip_and_docker_inspect(self):
        seen = []
        values = {
            ("ip", "-j", "-4", "addr", "show"): json.dumps(ADDR),
            ("ip", "-j", "-4", "route", "show", "table", "all"): json.dumps(ROUTES),
            ("docker", "network", "ls", "--quiet"): "first\nsecond\n",
            ("docker", "network", "inspect", "first", "second"): json.dumps(DOCKER),
        }
        def fake(argv, timeout):
            seen.append(tuple(argv))
            return values[tuple(argv)]
        addrs, routes, docker = module.collect(fake)
        self.assertEqual(len(seen), 4)
        self.assertEqual(seen, list(values))
        self.assertEqual(analyze(addresses=addrs, routes=routes, docker=docker)["status"],
                         "existing_cidr_conflict")

    def test_partial_docker_network_inventory_fails_closed(self):
        def fake(argv, timeout):
            if argv[:3] == ["docker", "network", "ls"]:
                return "first\nsecond\n"
            if argv[:3] == ["docker", "network", "inspect"]:
                return json.dumps(DOCKER[:1])
            return json.dumps(ADDR if "addr" in argv else ROUTES)
        with self.assertRaisesRegex(module.InventoryBlocked, "partial_docker_network_inventory"):
            module.collect(fake)


if __name__ == "__main__":
    unittest.main()
