"""Non-mutating CIDR overlap contract tests; no Docker/host calls."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "verify-lan-docker-network-isolation.py"
SPEC = importlib.util.spec_from_file_location("nexolab_cidr_preflight", SRC)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def address(name, ip, prefix=21):
    return {
        "ifname": name,
        "addr_info": [{"family": "inet", "local": ip, "prefixlen": prefix}],
    }


def docker_bridge(name, subnet, gateway=""):
    config = {"Subnet": subnet}
    if gateway:
        config["Gateway"] = gateway
    return {"Name": name, "Driver": "bridge", "IPAM": {"Config": [config]}}


LAN = address("eth0", "172.18.48.66")
BRIDGE = docker_bridge("nexolab-edge_default", "172.18.0.0/16", "172.18.0.1")
SAFE_BRIDGE = docker_bridge("nexolab-edge_default", "172.26.0.0/16", "172.26.0.1")


class DockerPhysicalLanIsolationTests(unittest.TestCase):
    def test_actual_raspberry_pi_conflict_detected(self):
        result = checker.analyze([LAN], [BRIDGE])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["conflicts"], [{
            "lan_interface": "eth0", "lan_cidr": "172.18.48.0/21",
            "docker_network": "nexolab-edge_default", "docker_cidr": "172.18.0.0/16",
        }])
        self.assertTrue(result["read_only"])

    def test_disjoint_docker_subnet_verified(self):
        result = checker.analyze([LAN], [SAFE_BRIDGE])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["conflicts"], [])

    def test_physical_wlan_and_usb_networks_are_covered(self):
        interfaces = [LAN, address("wlan0", "10.5.2.14", 24),
                      address("usb0", "192.168.8.5", 24)]
        docker = [SAFE_BRIDGE, docker_bridge("another_bridge", "10.5.2.0/24")]
        result = checker.analyze(interfaces, docker)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["lan_interface"], "wlan0")

    def test_virtual_docker_and_tailscale_bridges_excluded_as_physical(self):
        virtuals = [address("br-ef123", "172.18.0.1", 16),
                    address("docker0", "172.17.0.1", 16),
                    address("tailscale0", "100.113.204.81", 32),
                    address("vethab", "172.18.0.10", 16),
                    address("lo", "127.0.0.1", 8)]
        result = checker.analyze([LAN, *virtuals], [SAFE_BRIDGE, BRIDGE])
        self.assertEqual([x["interface"] for x in result["physical_ipv4"]], ["eth0"])
        self.assertEqual(len(result["conflicts"]), 1)

    def test_host_has_no_physical_lan_is_blocked_by_default(self):
        with self.assertRaisesRegex(checker.NetworkPreflightError, "no physical IPv4 LAN"):
            checker.analyze([address("lo", "127.0.0.1", 8)], [SAFE_BRIDGE])

    def test_disconnected_offline_fixture_requires_explicit_allowance(self):
        result = checker.analyze(
            [address("lo", "127.0.0.1", 8)], [SAFE_BRIDGE], allow_no_lan=True,
        )
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["lan_absent_explicitly_allowed"])

    def test_no_docker_bridge_is_not_trusted(self):
        with self.assertRaisesRegex(checker.NetworkPreflightError, "no IPv4 Docker bridge"):
            checker.analyze([LAN], [{"Name": "none", "Driver": "null",
                                     "IPAM": {"Config": []}}])

    def test_missing_or_malformed_lan_cidr_fails_closed(self):
        for invalid in (None, "banana", "172.18.48.66/53", "2001:db8::1/64"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(checker.NetworkPreflightError):
                    checker.cidr(invalid, "host")

    def test_invalid_host_address_lists_fail_closed(self):
        bad = copy.deepcopy(LAN)
        bad["addr_info"] = "not a list"
        with self.assertRaises(checker.NetworkPreflightError):
            checker.analyze([bad], [SAFE_BRIDGE])

    def test_missing_bridge_ipam_is_not_silent_success(self):
        bridge = {"Name": "orphan", "Driver": "bridge", "IPAM": {"Config": []}}
        with self.assertRaisesRegex(checker.NetworkPreflightError, "no IPAM"):
            checker.analyze([LAN], [bridge, SAFE_BRIDGE])

    def test_malformed_docker_subnet_fails_closed(self):
        with self.assertRaisesRegex(checker.NetworkPreflightError, "invalid IPv4 CIDR"):
            checker.analyze([LAN], [docker_bridge("bad", "172.18.0.0/99")])

    def test_two_overlapping_docker_bridges_both_reported(self):
        networks = [BRIDGE, docker_bridge("other", "172.18.48.0/24")]
        result = checker.analyze([LAN], networks)
        self.assertEqual(len(result["conflicts"]), 2)

    def test_private_docker_overlap_is_not_excused_for_lan(self):
        lan = address("eth0", "192.168.10.12", 24)
        docker = docker_bridge("nexolab-edge_default", "192.168.0.0/16")
        self.assertEqual(checker.analyze([lan], [docker])["status"], "conflict")

    def test_ipv6_only_and_non_ipv4_address_ignored(self):
        iface = copy.deepcopy(LAN)
        iface["addr_info"].append({
            "family": "inet6", "local": "2001:db8::1", "prefixlen": 64,
        })
        bridge = docker_bridge("local", "2001:db8:1::/64")
        self.assertEqual(
            checker.analyze([iface], [bridge, SAFE_BRIDGE])["status"], "verified",
        )

    def test_real_lan_interface_equal_to_docker_gateway_still_conflicts(self):
        # Never skip a physical uplink because it happens to share a
        # numerically equal IP with a Docker bridge gateway.
        result = checker.analyze([address("eth0", "172.18.0.1", 21)], [BRIDGE])
        self.assertEqual(result["status"], "conflict")

    def test_unknown_custom_interface_is_not_silently_excluded(self):
        interfaces = [address("plantlab0", "10.10.20.5", 24)]
        docker = [docker_bridge("bridge", "10.10.0.0/16")]
        self.assertEqual(checker.analyze(interfaces, docker)["status"], "conflict")


if __name__ == "__main__":
    unittest.main()
