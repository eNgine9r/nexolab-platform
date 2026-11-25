"""Tests for the P0 network-change compatibility recovery tool (#1733)."""

from __future__ import annotations

import importlib.util
import sys
import io
import json
import subprocess
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
        # Compose is used only for `version` and, inside the privileged helper, `config --format json`.
        self.assertEqual(sorted(set(re.findall(r'\["docker", "compose", "([^"]+)"', text))), ["--project-name", "version"])
        self.assertIn('cmd + ["config", "--format", "json"]', text)

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


def _c(name: str, service: str, project: str, state: str, networks: list[str], ports=(), published=(),
       mode: str | None = None) -> dict:
    item = _container(name, service, project, state, list(ports), list(published))
    item["networks"] = networks
    item["compose"] = dict(COMPOSE)
    item["network_mode"] = mode or ("nexolab-central" if project == "nexolab-central" else "nexolab-edge_default")
    item["restart_policy"] = "unless-stopped"
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
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=Path(tempfile.mkdtemp())), \
                mock.patch.object(REC.subprocess, "run", return_value=ok), \
                mock.patch.multiple(REC, IP=sys.executable, SYSCTL=sys.executable, SUDO_PYTHON=sys.executable), \
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
                mock.patch.object(REC, "run", return_value="4242 python3 -I -B recover-v2.py apply"):
            self.assertEqual(REC.repair_networks(), 3)

    def test_only_production_containers_with_lost_endpoints_are_targets(self) -> None:
        items = self.incident() + [
            _c("cand", "dashboard", "nexolab-central", "exited", []),          # stopped candidate
            _c("migrate", "telemetry-migrate", "nexolab-central", "exited", []),  # finished one-shot
            _c("other", "x", "nexolab-1364", "running", []),                   # other project
        ]
        lost = sorted(c["name"] for c in items if REC.endpoint_lost(c))
        self.assertEqual(lost, ["dash", "minio", "mq", "tel"])


class V31PrivilegedComposeTests(unittest.TestCase):
    """v3.1: Compose files may live in root-only directories (/var/backups/nexolab is 0750 root)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.private = self.root / "live-1575" / "compose"
        self.private.mkdir(parents=True)
        (self.private / "compose.central.yaml").write_text("services: {}\n")
        (self.private / ".env.central").write_text("POSTGRES_PASSWORD=supersecret\n")
        self.compose = {"project.config_files": str(self.private / "compose.central.yaml"),
                        "project.working_dir": str(self.private), "project.environment_file": ""}

    def tearDown(self) -> None:
        os.chmod(self.private.parent, 0o755)
        self.tmp.cleanup()

    def test_unprivileged_process_never_opens_root_only_compose_files(self) -> None:
        os.chmod(self.private.parent, 0o000)  # emulate the root-only backup directory
        projection = {"model": {"name": "nexolab-central", "services": {"mqtt": {"network_mode": None, "networks": {
            "central": {"aliases": [], "ipv4_address": None}}}}, "networks": {"central": {"name": "nexolab-central"}}}}
        calls = []

        def fake(cmd, **kwargs):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout=json.dumps(projection) + "\n", stderr="")

        with mock.patch.object(REC.subprocess, "run", side_effect=fake):
            model = REC.compose_config("nexolab-central", self.compose, ["mqtt"])
        self.assertEqual(model["services"]["mqtt"]["networks"]["central"]["aliases"], [])
        self.assertEqual(calls[0][:5], ["sudo", "-n", REC.SUDO_PYTHON, "-I", "-c"])
        request = json.loads(calls[0][-1])
        self.assertEqual(request["services"], ["mqtt"])
        self.assertEqual(request["env_fallback"], ".env.central")

    def test_helper_refusal_is_blocked_and_repair_reports_blocked_with_evidence(self) -> None:
        evidence = Path(tempfile.mkdtemp())
        items = [_c("mq", "mqtt", "nexolab-central", "running", [])]
        items[0]["compose"] = self.compose
        refusal = mock.Mock(returncode=0, stdout=json.dumps({"error": ["PATH_NOT_ALLOWED x"]}), stderr="")
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "run", return_value=""), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=evidence), \
                mock.patch.object(REC, "provenance", return_value={}), \
                mock.patch.object(REC, "diagnose", return_value={"containers": items, "arp_ignore": {}}), \
                mock.patch.object(REC, "share") as share, \
                mock.patch.multiple(REC, IP=sys.executable, SYSCTL=sys.executable, SUDO_PYTHON=sys.executable), \
                mock.patch.object(REC.subprocess, "run", return_value=refusal), \
                mock.patch.object(REC, "add_alias") as add_alias:
            code = REC.repair_networks("/tmp/x")
        self.assertEqual(code, 3)
        add_alias.assert_not_called()
        share.assert_called_once()
        self.assertIn("PATH_NOT_ALLOWED", (evidence / "preflight_blocked.json").read_text())

    def test_permission_error_in_preflight_is_blocked_not_a_crash(self) -> None:
        evidence = Path(tempfile.mkdtemp())
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "run", return_value=""), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=evidence), \
                mock.patch.object(REC, "provenance", return_value={}), \
                mock.patch.object(REC, "diagnose", side_effect=PermissionError(13, "Permission denied", "/var/backups/x")), \
                mock.patch.object(REC, "share"):
            self.assertEqual(REC.repair_networks(), 3)
        self.assertIn("PermissionError", (evidence / "preflight_blocked.json").read_text())

    def test_helper_validates_paths_and_returns_only_the_network_projection(self) -> None:
        """Run the real helper (as this user) with a fake docker that prints secret-bearing config."""
        bindir = self.root / "bin"
        bindir.mkdir()
        model = {"name": "nexolab-central", "services": {
            "telemetry-service": {"environment": {"DATABASE_URL": "postgresql://u:supersecret@postgres/db"},
                                  "networks": {"central": None, "standalone-runtime": {"aliases": ["x"]}}},
            "postgres": {"environment": {"POSTGRES_PASSWORD": "supersecret"}, "networks": {"central": None}}},
            "networks": {"central": {"name": "nexolab-central", "driver": "bridge"}}}
        (bindir / "docker").write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(model) + "\nJ\n")
        os.chmod(bindir / "docker", 0o755)
        request = REC.compose_request("nexolab-central", self.compose, ["telemetry-service"])
        request["roots"] = [str(self.root) + "/"]
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        out = subprocess.run([sys.executable, "-I", "-c", REC.COMPOSE_HELPER, json.dumps(request)],
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("supersecret", out.stdout)
        answer = json.loads(out.stdout)
        self.assertEqual(list(answer["model"]["services"]), ["telemetry-service"])
        self.assertEqual(answer["envs"], [str(self.private / ".env.central")])
        request["roots"] = ["/nonexistent-root/"]
        out = subprocess.run([sys.executable, "-I", "-c", REC.COMPOSE_HELPER, json.dumps(request)],
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertIn("PATH_NOT_ALLOWED", out.stdout)


class V31EndToEndTests(unittest.TestCase):
    def test_success_path_repairs_in_order_and_reports_green_stable(self) -> None:
        items = [_c("pg", "postgres", "nexolab-central", "running", ["nexolab-central"]),
                 _c("tel", "telemetry-service", "nexolab-central", "restarting", [], ["172.18.48.66:8082->8082/tcp"]),
                 _c("mq", "mqtt", "nexolab-central", "running", [], ["172.18.48.66:1884->1883/tcp"]),
                 _c("dash", "dashboard", "nexolab-central", "running", [], ["172.18.48.66:3000->3000/tcp"])]
        connects = []

        def fake_run(*args, **kwargs):
            if args[:3] == ("docker", "network", "connect"):
                connects.append((args[-1], args[-2]))
            return ""

        ok = mock.Mock(returncode=0, stdout="", stderr="")
        out = io.StringIO()
        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=Path(tempfile.mkdtemp())), \
                mock.patch.object(REC, "provenance", return_value={}), \
                mock.patch.object(REC, "diagnose", return_value={"containers": items, "arp_ignore": {}}), \
                mock.patch.object(REC, "compose_config", return_value=CENTRAL_MODEL), \
                mock.patch.object(REC.subprocess, "run", return_value=ok), \
                mock.patch.multiple(REC, IP=sys.executable, SYSCTL=sys.executable, SUDO_PYTHON=sys.executable), \
                mock.patch.object(REC, "compat_holders", return_value=["nxcompat0"]), \
                mock.patch.object(REC, "physical_routes_covering", return_value=[]), \
                mock.patch.object(REC, "run", side_effect=fake_run), \
                mock.patch.object(REC, "_ready", return_value=(True, "ok")), \
                mock.patch.object(REC, "containers", return_value=[]), \
                mock.patch.object(REC, "dns_check", return_value={"postgres": "172.19.0.3", "mqtt": "172.19.0.4"}), \
                mock.patch.object(REC, "http", return_value=(200, "{}")), \
                mock.patch.object(REC, "stability", return_value=(True, {})), \
                mock.patch.object(REC, "share"), \
                mock.patch("sys.stdout", out):
            code = REC.repair_networks()
        self.assertEqual(code, 0, out.getvalue()[-800:])
        self.assertIn("NEXOLAB_NETWORK_REPAIR_GREEN_STABLE", out.getvalue())
        self.assertEqual([c for c, _ in connects], ["mq", "mq", "tel", "tel", "dash"])
        self.assertIn(("mq", "nexolab-standalone-runtime"), connects)


class V32VerifyTests(unittest.TestCase):
    """Regression for run 20261125T105125Z: stopped historical Device Agents with configured ports."""

    def scenario(self, after: list[dict], dashboard_status: int = 200) -> tuple[int, str]:
        items = [_c("tel", "telemetry-service", "nexolab-central", "restarting", [], ["172.18.48.66:8082->8082/tcp"])]
        ok = mock.Mock(returncode=0, stdout="", stderr="")
        out = io.StringIO()

        def http(url, timeout=6):
            return (dashboard_status, "{}") if ":3000/" in url else (200, "{}")

        with mock.patch.object(REC.os, "getuid", return_value=1000), \
                mock.patch.object(REC, "lock", return_value=open(os.devnull)), \
                mock.patch.object(REC, "evidence_dir", return_value=Path(tempfile.mkdtemp())), \
                mock.patch.object(REC, "provenance", return_value={}), \
                mock.patch.object(REC, "diagnose", return_value={"containers": items, "arp_ignore": {}}), \
                mock.patch.object(REC, "compose_config", return_value=CENTRAL_MODEL), \
                mock.patch.object(REC.subprocess, "run", return_value=ok), \
                mock.patch.multiple(REC, IP=sys.executable, SYSCTL=sys.executable, SUDO_PYTHON=sys.executable), \
                mock.patch.object(REC, "compat_holders", return_value=["nxcompat0"]), \
                mock.patch.object(REC, "physical_routes_covering", return_value=[]), \
                mock.patch.object(REC, "run", return_value=""), \
                mock.patch.object(REC, "_ready", return_value=(True, "ok")), \
                mock.patch.object(REC, "containers", return_value=after), \
                mock.patch.object(REC, "summary", side_effect=lambda c: c), \
                mock.patch.object(REC, "dns_check", return_value={"postgres": "172.19.0.3", "mqtt": "172.19.0.10"}), \
                mock.patch.object(REC, "http", side_effect=http), \
                mock.patch.object(REC, "stability", return_value=(True, {})), \
                mock.patch.object(REC, "share"), \
                mock.patch("sys.stdout", out):
            code = REC.repair_networks(allow_minimal=True)
        return code, out.getvalue()

    def production_after(self) -> list[dict]:
        tel = _c("tel", "telemetry-service", "nexolab-central", "running", ["nexolab-central", "nexolab-standalone-runtime"],
                 ["172.18.48.66:8082->8082/tcp"], ["172.18.48.66:8082->8082/tcp"])
        historical = []
        for name in ("nexolab-edge-device-agent-pre1496", "nexolab-edge-device-agent-1-pre-1490"):
            item = _c(name, "device-agent", "nexolab-edge", "exited", ["nexolab-edge_default", "nexolab-standalone-runtime"],
                      ["127.0.0.1:8081->8081/tcp"], [])
            item["error"] = ""  # stopped on purpose, no failed start
            historical.append(item)
        return [tel, *historical]

    def test_stopped_historical_containers_with_configured_ports_do_not_fail_verification(self) -> None:
        code, out = self.scenario(self.production_after())
        self.assertEqual(code, 0, out[-600:])
        self.assertIn("NEXOLAB_NETWORK_REPAIR_GREEN_STABLE", out)
        self.assertNotIn("ROLLBACK", out)

    def test_production_container_without_published_ports_still_rolls_back(self) -> None:
        after = self.production_after()
        after[0]["published_ports"] = []
        code, out = self.scenario(after)
        self.assertEqual(code, 1)
        self.assertIn("NEXOLAB_NETWORK_REPAIR_ROLLED_BACK", out)
        self.assertIn("missing_ports={'tel'", out)

    def test_dashboard_not_http_200_rolls_back(self) -> None:
        code, out = self.scenario(self.production_after(), dashboard_status=502)
        self.assertEqual(code, 1)
        self.assertIn("dashboard=502", out)

    def test_failed_start_with_restart_policy_still_counts_as_production(self) -> None:
        item = _c("tel", "telemetry-service", "nexolab-central", "exited", [], ["172.18.48.66:8082->8082/tcp"])
        item["error"] = "failed to set up container networking"
        self.assertTrue(REC.meant_to_run(item))


class V31MinimalModelTests(unittest.TestCase):
    def test_minimal_model_restores_primary_network_and_standalone_overlay(self) -> None:
        members = [_c("mq", "mqtt", "nexolab-central", "running", []), _c("dash", "dashboard", "nexolab-central", "running", [])]
        with mock.patch.object(REC.subprocess, "run", return_value=mock.Mock(returncode=0)):
            model = REC.minimal_model("nexolab-central", members)
        self.assertEqual(REC.desired_networks(model, "mqtt"), {
            "nexolab-central": {"aliases": ["mqtt"], "ipv4": None},
            "nexolab-standalone-runtime": {"aliases": ["mqtt", "central-mqtt"], "ipv4": None}})
        self.assertEqual(REC.desired_networks(model, "dashboard"), {"nexolab-central": {"aliases": ["dashboard"], "ipv4": None}})

    def test_minimal_model_is_never_used_without_the_explicit_flag(self) -> None:
        items = [_c("mq", "mqtt", "nexolab-central", "running", [])]
        blocked = REC.Blocked("COMPOSE_MODEL_BLOCKED nexolab-central: ['COMPOSE_CONFIG_FAILED exit=1']")
        with mock.patch.object(REC.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch.multiple(REC, IP=sys.executable, SYSCTL=sys.executable, SUDO_PYTHON=sys.executable), \
                mock.patch.object(REC, "compose_config", side_effect=blocked), \
                mock.patch.object(REC, "compat_holders", return_value=[]), \
                mock.patch.object(REC, "physical_routes_covering", return_value=[]):
            with self.assertRaises(REC.Blocked):
                REC.preflight(items)
            plan, models = REC.preflight(items, allow_minimal=True)
        self.assertEqual([p["name"] for p in plan], ["mq"])
        self.assertEqual(next(iter(models.values()))["source"], "minimal-fallback")


class V3SelectionTests(unittest.TestCase):
    def test_one_shot_and_candidate_containers_are_never_started(self) -> None:
        def c(state, error="", policy="unless-stopped"):
            return {"state": state, "error": error, "restart_policy": policy}
        self.assertTrue(REC.meant_to_run(c("running")))
        self.assertTrue(REC.meant_to_run(c("restarting")))
        self.assertTrue(REC.meant_to_run(c("exited", "failed to set up container networking")))
        self.assertFalse(REC.meant_to_run(c("exited")))  # init/migrate finished normally
        self.assertFalse(REC.meant_to_run(c("exited", "boom", "no")))  # candidate without restart policy

    def test_postgres_check_parses_multiline_output(self) -> None:
        self.assertIn("jsonb_build_object", REC.PG_READONLY_SQL)
        self.assertNotIn("json_build_object(", REC.PG_READONLY_SQL.replace("jsonb_build_object(", ""))


if __name__ == "__main__":
    unittest.main()
