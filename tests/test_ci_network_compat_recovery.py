"""Tests for the P0 network-change compatibility recovery tool (#1733)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs" / "operations" / "network" / "nexolab-network-compat-recovery.py"
SPEC = importlib.util.spec_from_file_location("nexolab_network_compat_recovery", TOOL)
assert SPEC and SPEC.loader
REC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REC
SPEC.loader.exec_module(REC)


def _container(name: str, service: str, project: str, state: str, configured: list[str], published: list[str]) -> dict:
    return {
        "id": name, "name": name, "service": service, "project": project, "state": state, "health": "-",
        "error": "", "image": "sha256:x", "mounts": [], "networks": ["n"],
        "bound_ips": sorted({entry.split(":")[0] for entry in configured}),
        "configured_ports": configured, "published_ports": published,
    }


class SelectionTests(unittest.TestCase):
    def test_selects_compat_bound_and_portless_containers_in_dependency_order(self) -> None:
        items = [
            _container("dash", "dashboard", "nexolab-central", "running", ["172.18.48.66:3000->3000/tcp"], []),
            _container("tel", "telemetry-service", "nexolab-central", "exited", ["172.18.48.66:8082->8082/tcp"], []),
            _container("mq", "mqtt", "nexolab-central", "exited", ["172.18.48.66:1884->1883/tcp"], []),
            _container("edge", "mqtt", "nexolab-edge", "running", ["127.0.0.1:1883->1883/tcp"], ["127.0.0.1:1883->1883/tcp"]),
            _container("pg", "postgres", "nexolab-central", "running", [], []),
        ]
        self.assertEqual([c["name"] for c in REC.affected(items)], ["mq", "tel", "dash"])

    def test_foreign_project_on_compat_address_blocks(self) -> None:
        foreign = _container("x", "web", "other", "running", ["172.18.48.66:80->80/tcp"], [])
        with self.assertRaises(REC.Blocked):
            REC.affected([foreign])

    def test_ports_missing(self) -> None:
        ok = _container("a", "s", "nexolab-central", "running", ["0.0.0.0:3000->3000/tcp"], ["0.0.0.0:3000->3000/tcp"])
        bad = _container("b", "s", "nexolab-central", "running", ["0.0.0.0:3000->3000/tcp"], [])
        self.assertFalse(REC.ports_missing(ok))
        self.assertTrue(REC.ports_missing(bad))


class NetworkGuardTests(unittest.TestCase):
    def _routes(self, text: str) -> list[str]:
        with mock.patch.object(REC, "run", return_value=text):
            return REC.physical_routes_covering()

    def test_former_lab_lan_route_is_detected(self) -> None:
        self.assertTrue(self._routes("172.18.48.0/21 dev eth0 proto kernel scope link src 172.18.48.66"))

    def test_docker_bridge_and_new_lan_are_ignored(self) -> None:
        routes = "\n".join([
            "default via 192.168.1.1 dev eth0 proto dhcp",
            "172.18.0.0/16 dev br-f9c3e2a71ba5 proto kernel scope link src 172.18.0.1",
            "192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.220",
        ])
        self.assertEqual(self._routes(routes), [])

    def test_apply_refuses_when_physical_interface_holds_address(self) -> None:
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "compat_holders", return_value=["eth0"]), \
                mock.patch.object(REC, "run") as run:
            with self.assertRaises(REC.Blocked):
                REC.apply()
            run.assert_not_called()

    def test_apply_refuses_other_users(self) -> None:
        with mock.patch.object(REC.os, "getuid", return_value=0), self.assertRaises(REC.Blocked):
            REC.apply()


class SafetyContractTests(unittest.TestCase):
    def test_tool_never_recreates_prunes_or_removes(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        for verb in ('"docker", "rm"', '"docker", "volume"', '"docker", "network"', '"docker", "compose"', "down -v"):
            self.assertNotIn(verb, text)

    def test_boot_unit_runs_before_docker_and_only_adds_alias(self) -> None:
        unit = REC.UNIT_TEXT
        self.assertIn("Before=network-pre.target docker.service", unit)
        self.assertIn("link add nxcompat0 type dummy", unit)
        self.assertIn("addr add 172.18.48.66/32 dev nxcompat0", unit)
        self.assertNotIn("ExecStop", unit)


class V2Tests(unittest.TestCase):
    def test_postgres_check_is_read_only_and_bounded(self) -> None:
        sql = REC.PG_READONLY_SQL
        self.assertIn("statement_timeout", sql)
        self.assertIn("ORDER BY id DESC LIMIT 200000", sql)
        for verb in ("INSERT", "UPDATE", "DELETE", "VACUUM", "TRUNCATE", "ALTER", "DROP", "CREATE"):
            self.assertNotIn(verb, sql.upper().replace("CREATED", ""))
        self.assertIn("default_transaction_read_only=on", TOOL.read_text(encoding="utf-8"))

    def test_restarting_container_is_selected(self) -> None:
        item = _container("tel", "telemetry-service", "nexolab-central", "restarting", ["0.0.0.0:8082->8082/tcp"], [])
        self.assertEqual([c["name"] for c in REC.affected([item])], ["tel"])

    def test_stability_requires_delivery_and_ingestion(self) -> None:
        holders = mock.patch.object(REC, "compat_holders", return_value=["nxcompat0"])
        ready = mock.patch.object(REC, "http", return_value=(200, "{}"))
        with holders, ready, mock.patch.object(REC, "containers", return_value=[]), \
                mock.patch.object(REC, "STABILITY_SECONDS", 0), \
                mock.patch.object(REC, "_sent", side_effect=[10, 10]), \
                mock.patch.object(REC, "postgres_ingestion", side_effect=[{"latest": [{"id": 5}]}, {"latest": [{"id": 9}]}]):
            ok, result = REC.stability(None)
        self.assertFalse(ok)
        self.assertFalse(result["edge_delivering"])
        self.assertTrue(result["pg_ingesting"])
        with holders, ready, mock.patch.object(REC, "containers", return_value=[]), \
                mock.patch.object(REC, "STABILITY_SECONDS", 0), \
                mock.patch.object(REC, "_sent", side_effect=[10, 50]), \
                mock.patch.object(REC, "postgres_ingestion", side_effect=[{"latest": [{"id": 5}]}, {"latest": [{"id": 9}]}]):
            ok, _ = REC.stability(None)
        self.assertTrue(ok)

    def test_provenance_reports_own_checksum(self) -> None:
        import hashlib
        self.assertEqual(REC.provenance()["tool_sha256"], hashlib.sha256(TOOL.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
