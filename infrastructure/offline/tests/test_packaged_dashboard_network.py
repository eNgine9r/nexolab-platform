"""Fail-closed packaged Dashboard boot networking acceptance without Docker writes."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "verify-packaged-dashboard-port.py"
spec = importlib.util.spec_from_file_location("dashboard_network_gate", path)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PROJECT = "nexolab-central"
BIND = "192.0.2.50"


def healthy_container():
    expected = [{"HostIp": BIND, "HostPort": "3000"}]
    return {
        "Config": {"Labels": {"com.docker.compose.project": PROJECT,
                              "com.docker.compose.service": "dashboard"}},
        "HostConfig": {"NetworkMode": PROJECT, "PortBindings": {"3000/tcp": expected}},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {PROJECT: {}}, "Ports": {"3000/tcp": expected}},
    }


class DashboardPortContractTests(unittest.TestCase):
    def check(self, container):
        return mod.verify_dashboard(
            PROJECT, PROJECT, BIND, 3000, inspector=lambda _p: copy.deepcopy(container)
        )

    def test_active_packaged_dashboard_has_published_lan_port(self):
        self.assertEqual(self.check(healthy_container())["status"], "verified")

    def test_internal_health_green_with_zero_networks_rejected(self):
        actual = healthy_container()
        actual["NetworkSettings"]["Networks"] = {}
        actual["NetworkSettings"]["Ports"] = {}
        with self.assertRaisesRegex(mod.DashboardNetworkError, "missing required central"):
            self.check(actual)

    def test_network_present_but_host_port_absent_rejected(self):
        actual = healthy_container()
        actual["NetworkSettings"]["Ports"] = {}
        with self.assertRaisesRegex(mod.DashboardNetworkError, "published host port"):
            self.check(actual)

    def test_configured_port_not_a_live_port(self):
        actual = healthy_container()
        actual["HostConfig"]["PortBindings"] = {"3000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3000"}]}
        with self.assertRaisesRegex(mod.DashboardNetworkError, "configured port"):
            self.check(actual)

    def test_wider_public_bind_not_allowed_as_lan_approval(self):
        actual = healthy_container()
        actual["NetworkSettings"]["Ports"]["3000/tcp"] = [
            {"HostIp": "0.0.0.0", "HostPort": "3000"}
        ]
        with self.assertRaisesRegex(mod.DashboardNetworkError, "published host port"):
            self.check(actual)

    def test_stopped_container_never_passes(self):
        actual = healthy_container()
        actual["State"]["Running"] = False
        with self.assertRaisesRegex(mod.DashboardNetworkError, "not running"):
            self.check(actual)

    def test_wrong_compose_service_never_passes(self):
        actual = healthy_container()
        actual["Config"]["Labels"]["com.docker.compose.service"] = "frontend-dev"
        with self.assertRaisesRegex(mod.DashboardNetworkError, "identity"):
            self.check(actual)

    def test_wrong_network_mode_is_rejected(self):
        actual = healthy_container()
        actual["HostConfig"]["NetworkMode"] = "host"
        with self.assertRaisesRegex(mod.DashboardNetworkError, "network mode"):
            self.check(actual)

    def test_invalid_bind_port_is_rejected(self):
        with self.assertRaisesRegex(mod.DashboardNetworkError, "invalid"):
            mod.verify_dashboard(PROJECT, PROJECT, BIND, 0)


if __name__ == "__main__":
    unittest.main()
