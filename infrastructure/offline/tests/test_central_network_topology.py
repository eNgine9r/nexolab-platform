"""No-dependency regression suite for deployed Docker network readiness."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "verify-central-network-topology.py"
SPEC = importlib.util.spec_from_file_location("central_network_topology", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def fixture(mode="lan"):
    central, standalone = "nexolab-central", "nexolab-standalone-runtime"
    networks = {
        "mqtt": {central: {"Aliases": ["mqtt", "nexolab-central-mqtt-1"]}},
        "telemetry-service": {central: {"Aliases": ["telemetry-service"]}},
        "postgres": {central: {"Aliases": ["postgres"]}},
    }
    if mode != "central":
        networks["mqtt"][standalone] = {"Aliases": ["central-mqtt", "mqtt"]}
        networks["telemetry-service"][standalone] = {"Aliases": ["telemetry-service"]}
    return {
        service: {
            "State": {"Running": True},
            "Config": {"Labels": {"com.docker.compose.project": central,
                                  "com.docker.compose.service": service}},
            "NetworkSettings": {"Networks": nets},
        }
        for service, nets in networks.items()
    }


class TopologyContracts(unittest.TestCase):
    def check(self, items, mode="lan", probe=None):
        calls = []
        result = checker.verify_topology(
            mode=mode, inspector=lambda _project, service: copy.deepcopy(items[service]),
            probe=probe or (lambda project: calls.append(project)),
        )
        return result, calls

    def test_full_approved_topology_in_all_modes(self):
        for mode in ("lan", "standalone", "central"):
            with self.subTest(mode=mode):
                result, calls = self.check(fixture(mode), mode)
                self.assertEqual(result["status"], "verified")
                self.assertEqual(calls, ["nexolab-central"])

    def test_missing_any_required_network_fails_closed(self):
        for service, network in (
            ("mqtt", "nexolab-central"),
            ("mqtt", "nexolab-standalone-runtime"),
            ("telemetry-service", "nexolab-central"),
            ("telemetry-service", "nexolab-standalone-runtime"),
            ("postgres", "nexolab-central"),
        ):
            with self.subTest(service=service, network=network):
                actual = fixture()
                actual[service]["NetworkSettings"]["Networks"].pop(network)
                with self.assertRaisesRegex(checker.NetworkTopologyError, "missing required"):
                    self.check(actual)

    def test_stopped_container_fails_closed(self):
        for service in checker.SERVICES:
            with self.subTest(service=service):
                actual = fixture()
                actual[service]["State"]["Running"] = False
                with self.assertRaisesRegex(checker.NetworkTopologyError, "not running"):
                    self.check(actual)

    def test_wrong_compose_owner_fails_closed(self):
        for service in checker.SERVICES:
            with self.subTest(service=service):
                actual = fixture()
                actual[service]["Config"]["Labels"]["com.docker.compose.project"] = "foreign"
                with self.assertRaisesRegex(checker.NetworkTopologyError, "wrong Compose ownership"):
                    self.check(actual)

    def test_broker_alias_must_exist_on_both_networks(self):
        for network, alias in (
            ("nexolab-central", "mqtt"),
            ("nexolab-standalone-runtime", "central-mqtt"),
        ):
            with self.subTest(network=network):
                actual = fixture()
                actual["mqtt"]["NetworkSettings"]["Networks"][network]["Aliases"].remove(alias)
                with self.assertRaisesRegex(checker.NetworkTopologyError, "broker alias"):
                    self.check(actual)

    def test_dns_tcp_probe_cannot_be_skipped(self):
        with self.assertRaisesRegex(checker.NetworkTopologyError, "dns unreachable"):
            self.check(fixture(), probe=lambda _: (_ for _ in ()).throw(
                checker.NetworkTopologyError("dns unreachable")
            ))

    def test_central_only_mode_has_no_extra_requirement(self):
        result, _ = self.check(fixture("central"), "central")
        self.assertEqual(result["networks"]["mqtt"], ["nexolab-central"])

    def test_invalid_parameters_fail_before_inspection(self):
        with self.assertRaisesRegex(checker.NetworkTopologyError, "overlapping"):
            checker.verify_topology(standalone_network="nexolab-central")
        with self.assertRaisesRegex(checker.NetworkTopologyError, "unsupported"):
            checker.verify_topology(mode="internet")


if __name__ == "__main__":
    unittest.main()
