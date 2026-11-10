"""NEXOLAB #1464 offline Compose-only Edge IPAM acceptance; no Docker mutations."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "infrastructure/compose/compose.edge.yaml"
STANDALONE = ROOT / "infrastructure/compose/compose.edge-standalone.yaml"
OVERLAY = ROOT / "infrastructure/compose/compose.edge-safe-ipam.yaml"
AUDIT_SOURCE = ROOT / "infrastructure/offline/inspect-edge-docker-ipam-readiness.py"
SPEC = importlib.util.spec_from_file_location("edge_ipam_audit", AUDIT_SOURCE)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def compose_config(subnet: str | None, standalone: bool = True):
    env = os.environ.copy()
    env.pop("NEXOLAB_EDGE_DOCKER_SUBNET", None)
    if subnet is not None:
        env["NEXOLAB_EDGE_DOCKER_SUBNET"] = subnet
    argv = ["docker", "compose", "-f", str(BASE)]
    if standalone:
        argv += ["-f", str(STANDALONE)]
    argv += ["-f", str(OVERLAY), "config", "--format", "json"]
    return subprocess.run(argv, cwd=ROOT, env=env,
                          text=True, capture_output=True, timeout=18, check=False)


def site_fixture():
    addresses = [
        {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
        {"ifname": "eth0", "addr_info": [{"family": "inet", "local": "172.18.48.66", "prefixlen": 21}]},
        {"ifname": "tailscale0", "addr_info": [{"family": "inet", "local": "100.113.204.81", "prefixlen": 32}]},
    ]
    routes = [
        {"dst": "default", "dev": "eth0"},
        {"dst": "172.18.48.0/21", "dev": "eth0"},
        {"dst": "172.18.0.0/16", "dev": "br-old-edge"},
        {"dst": "172.19.0.0/16", "dev": "br-central"},
        {"dst": "172.21.0.0/16", "dev": "br-standalone"},
        {"dst": "100.100.100.100/32", "dev": "tailscale0"},
    ]
    bridges = [
        {"Name": name, "Driver": "bridge", "IPAM": {"Config": [{"Subnet": subnet}]}}
        for name, subnet in [
            ("nexolab-edge_default", "172.18.0.0/16"),
            ("nexolab-central", "172.19.0.0/16"),
            ("nexolab-standalone-runtime", "172.21.0.0/16"),
        ]
    ]
    return addresses, routes, bridges


class EdgeSourceSafeIpamTests(unittest.TestCase):
    def test_no_site_ipam_default_and_no_destructive_commands(self):
        s = OVERLAY.read_text()
        self.assertIn("NEXOLAB_EDGE_DOCKER_SUBNET:?", s)
        self.assertNotIn("172.26.0.0/24", s)
        for forbidden in ("docker network rm", "compose down", "docker compose up",
                          "172.18.0.0/16", "127.0.0.1:1883"):
            self.assertNotIn(forbidden, s)

    def test_unset_site_subnet_fails_before_compose_model(self):
        run = compose_config(None)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.stdout, "")

    def test_optin_compose_model_preserves_project_and_volumes(self):
        run = compose_config("172.26.0.0/24")
        self.assertEqual(run.returncode, 0, run.stderr[:300])
        model = json.loads(run.stdout)
        self.assertEqual(model["name"], "nexolab-edge")
        self.assertEqual(model["networks"]["default"]["name"], "nexolab-edge_default")
        self.assertEqual(model["networks"]["default"]["driver"], "bridge")
        self.assertEqual(model["networks"]["default"]["ipam"]["config"],
                         [{"subnet": "172.26.0.0/24"}])
        self.assertEqual(model["networks"]["standalone-runtime"]["external"], True)
        self.assertEqual(
            sorted(model["volumes"]), ["edge-data", "mqtt-data"])
        self.assertEqual(sorted(model["services"]), ["device-agent", "mqtt"])
        for service in ("device-agent", "mqtt"):
            self.assertEqual(sorted(model["services"][service]["networks"]),
                             ["default", "standalone-runtime"])
        self.assertIn("/var/lib/nexolab", str(model["services"]["device-agent"]["volumes"]))
        self.assertEqual(model["services"]["device-agent"]["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(model["services"]["mqtt"]["ports"][0]["host_ip"], "127.0.0.1")

    def test_isolated_default_only_model_does_not_add_services(self):
        run = compose_config("172.26.0.0/24", standalone=False)
        self.assertEqual(run.returncode, 0, run.stderr[:300])
        model = json.loads(run.stdout)
        self.assertEqual(sorted(model["services"]), ["device-agent", "mqtt"])
        self.assertEqual(sorted(model["networks"]), ["default"])
        self.assertEqual(model["networks"]["default"]["ipam"]["config"][0]["subnet"],
                         "172.26.0.0/24")

    def test_candidate_locally_disjoint_is_still_unapproved(self):
        result = AUDIT.analyze(*site_fixture(), candidate="172.26.0.0/24")
        self.assertEqual(result["candidate_status"], "locally_disjoint_not_site_approved")
        self.assertEqual(result["status"], "candidate_unapproved")
        self.assertFalse(result["site_cutover_authorized"])
        self.assertFalse(result["site_reservations_verified"])
        self.assertFalse(result["mutation_performed"])
        self.assertTrue(result["existing_overlap"])

    def test_live_lan_cidr_is_not_acceptable(self):
        result = AUDIT.analyze(*site_fixture(), candidate="172.18.48.0/24")
        self.assertEqual(result["candidate_status"], "conflict")
        self.assertTrue(result["candidate_conflicts"])

    def test_active_bridge_cidr_is_not_acceptable(self):
        result = AUDIT.analyze(*site_fixture(), candidate="172.21.0.0/24")
        self.assertEqual(result["candidate_status"], "conflict")

    def test_external_reserved_cidr_blocks_even_locally_disjoint_candidate(self):
        result = AUDIT.analyze(*site_fixture(), candidate="172.26.0.0/24",
                               reserved=("172.26.0.0/20",))
        self.assertEqual(result["candidate_status"], "conflict")

    def test_vpn_route_overlap_blocks_candidate(self):
        addresses, routes, bridges = site_fixture()
        routes.append({"dst": "172.26.0.0/24", "dev": "tailscale0"})
        result = AUDIT.analyze(addresses, routes, bridges, candidate="172.26.0.0/24")
        self.assertEqual(result["candidate_status"], "conflict")

    def test_non_rfc1918_candidate_refused(self):
        with self.assertRaises(AUDIT.InventoryBlocked):
            AUDIT.analyze(*site_fixture(), candidate="8.8.8.0/24")

    def test_overbroad_candidate_refused(self):
        with self.assertRaises(AUDIT.InventoryBlocked):
            AUDIT.analyze(*site_fixture(), candidate="172.26.0.0/16")

    def test_invalid_candidate_refused(self):
        with self.assertRaises(AUDIT.InventoryBlocked):
            AUDIT.analyze(*site_fixture(), candidate="172.26.not-an-ip/24")

    def test_route_inventory_missing_fails_closed(self):
        addresses, _, bridges = site_fixture()
        with self.assertRaises(AUDIT.InventoryBlocked):
            AUDIT.analyze(addresses, [], bridges, candidate="172.26.0.0/24")

    def test_no_mutating_docker_operations_in_source(self):
        script = AUDIT_SOURCE.read_text()
        for forbidden in ("network create", "network rm", "network connect",
                          "docker compose down", "docker compose up"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
