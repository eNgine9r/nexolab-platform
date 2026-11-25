"""Tests for the P0 network-change compatibility recovery tool (#1733)."""

from __future__ import annotations

import importlib.util
import sys
import os
import re
import tempfile
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
        for verb in ('"docker", "rm"', '"docker", "volume"', '"docker", "system"', '"docker", "image"', '"prune"',
                     "down -v", '"compose", "down"', '"compose", "up"', "--force-recreate", '"network", "create"', '"network", "rm"'):
            self.assertNotIn(verb, text)
        # Docker network use is limited to inspect/connect and disconnect for rollback; Compose to `config` only.
        self.assertEqual(sorted(set(re.findall(r'"docker", "network", "(\w+)"', text))), ["connect", "disconnect", "inspect"])
        self.assertIn('"config", "--format", "json"', text)
        self.assertEqual(len(re.findall(r'\["docker", "compose"', text)), 1)

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


CENTRAL_MODEL = {
    "name": "nexolab-central",
    "services": {
        "postgres": {"networks": {"central": None}},
        "mqtt": {"networks": {"central": None, "standalone-runtime": {"aliases": ["central-mqtt"]}}},
        "telemetry-service": {"networks": {"central": None, "standalone-runtime": None}},
        "minio": {"networks": {"central": None}},
        "dashboard": {"networks": {"central": None}},
    },
    "networks": {"central": {"name": "nexolab-central"}, "standalone-runtime": {"name": "nexolab-standalone-runtime"}},
}
EDGE_MODEL = {
    "name": "nexolab-edge",
    "services": {"device-agent": {"networks": {"default": None, "standalone-runtime": {"aliases": ["edge-device-agent"]}}},
                 "mqtt": {"networks": {"default": None, "standalone-runtime": None}}},
    "networks": {"standalone-runtime": {"name": "nexolab-standalone-runtime"}},
}
COMPOSE = {"project.config_files": "/srv/c.yaml", "project.working_dir": "/srv", "project.environment_file": "/srv/.env"}


def _c(name: str, service: str, project: str, state: str, networks: list[str], ports=(), published=()) -> dict:
    item = _container(name, service, project, state, list(ports), list(published))
    item["networks"] = networks
    item["compose"] = dict(COMPOSE)
    return item


class V3RepairTests(unittest.TestCase):
    def incident(self) -> list[dict]:
        return [
            _c("pg", "postgres", "nexolab-central", "running", ["nexolab-central"]),
            _c("tel", "telemetry-service", "nexolab-central", "restarting", [], ["172.18.48.66:8082->8082/tcp"]),
            _c("mq", "mqtt", "nexolab-central", "running", [], ["172.18.48.66:1884->1883/tcp"]),
            _c("minio", "minio", "nexolab-central", "running", [], ["172.18.48.66:9000->9000/tcp"]),
            _c("dash", "dashboard", "nexolab-central", "running", [], ["0.0.0.0:3000->3000/tcp"]),
            _c("agent", "device-agent", "nexolab-edge", "running", ["nexolab-edge_default"]),
        ]

    def models(self) -> dict:
        key_c = ("nexolab-central", COMPOSE["project.config_files"], COMPOSE["project.environment_file"])
        key_e = ("nexolab-edge", COMPOSE["project.config_files"], COMPOSE["project.environment_file"])
        return {key_c: CENTRAL_MODEL, key_e: EDGE_MODEL}

    def test_desired_networks_use_compose_names_service_alias_and_extra_aliases(self) -> None:
        self.assertEqual(REC.desired_networks(CENTRAL_MODEL, "mqtt"), {
            "nexolab-central": {"aliases": ["mqtt"], "ipv4": None},
            "nexolab-standalone-runtime": {"aliases": ["mqtt", "central-mqtt"], "ipv4": None}})
        self.assertEqual(list(REC.desired_networks(EDGE_MODEL, "device-agent")),
                         ["nexolab-edge_default", "nexolab-standalone-runtime"])
        self.assertEqual(REC.desired_networks({"name": "p", "services": {"x": {"network_mode": "host"}}}, "x"), {})
        with self.assertRaises(REC.Blocked):
            REC.desired_networks(CENTRAL_MODEL, "unknown")

    def test_plan_matches_the_reported_incident_in_dependency_order(self) -> None:
        # Separate models per project: compose labels differ in reality; emulate with distinct keys.
        items = self.incident()
        for c in items:
            if c["project"] == "nexolab-edge":
                c["compose"]["project.config_files"] = "/srv/e.yaml"
        key_c = ("nexolab-central", "/srv/c.yaml", "/srv/.env")
        key_e = ("nexolab-edge", "/srv/e.yaml", "/srv/.env")
        plan = REC.endpoint_plan(items, {key_c: CENTRAL_MODEL, key_e: EDGE_MODEL})
        self.assertEqual([p["name"] for p in plan], ["minio", "mq", "tel", "dash", "agent"])
        tel = next(p for p in plan if p["name"] == "tel")
        self.assertEqual(list(tel["missing"]), ["nexolab-central", "nexolab-standalone-runtime"])
        self.assertNotIn("pg", [p["name"] for p in plan])

    def test_connect_command_carries_aliases_and_fixed_ip(self) -> None:
        self.assertEqual(REC.connect_cmd("net", {"aliases": ["mqtt", "central-mqtt"], "ipv4": "172.30.0.5"}, "cid"),
                         ["docker", "network", "connect", "--alias", "mqtt", "--alias", "central-mqtt",
                          "--ip", "172.30.0.5", "net", "cid"])

    def test_broken_container_is_stopped_connected_started_but_healthy_agent_is_never_stopped(self) -> None:
        calls = []
        with mock.patch.object(REC, "run", side_effect=lambda *a, **k: calls.append(a) or ""), \
                mock.patch.object(REC, "_ready", return_value=(True, "ok")):
            undo = {"id": "tel", "name": "tel", "pre_state": "restarting", "added": []}
            REC.repair_one({"id": "tel", "name": "tel", "state": "restarting", "had": [],
                            "missing": {"nexolab-central": {"aliases": ["telemetry-service"], "ipv4": None}}}, 5, undo)
            agent = {"id": "agent", "name": "agent", "pre_state": "running", "added": []}
            REC.repair_one({"id": "agent", "name": "agent", "state": "running", "had": ["nexolab-edge_default"],
                            "missing": {"nexolab-standalone-runtime": {"aliases": ["device-agent"], "ipv4": None}}}, 5, agent)
        verbs = [(a[1], a[-1]) for a in calls if a[0] == "docker" and a[1] in ("stop", "start", "network")]
        self.assertIn(("stop", "tel"), verbs)
        self.assertIn(("start", "tel"), verbs)
        self.assertNotIn(("stop", "agent"), verbs)
        self.assertNotIn(("start", "agent"), verbs)
        self.assertEqual(undo["added"], ["nexolab-central"])
        self.assertTrue(agent["live"])

    def test_failure_rolls_back_every_touched_container_and_added_alias(self) -> None:
        items = self.incident()[:3]
        diag = {"containers": items, "arp_ignore": {"eth0": "0"}}
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(args)
            return ""

        ready = iter([(True, "ok"), (False, "restarting")])
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=Path(tempfile.mkdtemp())), \
                mock.patch.object(REC, "provenance", return_value={}), \
                mock.patch.object(REC, "diagnose", return_value=diag), \
                mock.patch.object(REC, "compose_config", return_value=CENTRAL_MODEL), \
                mock.patch.object(REC, "compat_holders", return_value=[]), \
                mock.patch.object(REC, "physical_routes_covering", return_value=[]), \
                mock.patch.object(REC, "add_alias") as add_alias, \
                mock.patch.object(REC, "remove_alias") as remove_alias, \
                mock.patch.object(REC, "restore_arp"), \
                mock.patch.object(REC, "share"), \
                mock.patch.object(REC, "run", side_effect=fake_run), \
                mock.patch.object(REC.time, "sleep"), \
                mock.patch.object(REC.time, "monotonic", side_effect=(i * 10.0 for i in range(10_000))), \
                mock.patch.object(REC, "_ready", side_effect=lambda *a: next(ready, (False, "restarting"))):
            code = REC.repair_networks()
        self.assertEqual(code, 1)
        add_alias.assert_called_once()
        remove_alias.assert_called_once()
        disconnects = [a for a in calls if a[:3] == ("docker", "network", "disconnect")]
        self.assertEqual({a[-1] for a in disconnects}, {"mq", "tel"})
        self.assertNotIn("pg", {a[-1] for a in calls})

    def test_refuses_while_another_recovery_runs(self) -> None:
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "run", return_value="4242 python3 -I -B recover-v2.py apply"), \
                self.assertRaises(REC.Blocked):
            REC.repair_networks()


if __name__ == "__main__":
    unittest.main()
