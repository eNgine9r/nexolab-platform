"""Tests for the WP2c Stage 3 backend loopback / Docker DNS tool (#1734).

Docker is replaced by a fake executable on PATH that records every argv, serves
canned ``docker inspect`` JSON, renders ``docker compose config`` from the
generated files and recreates containers on ``compose up``. The telemetry
readiness endpoint, the dashboard and the other publishes are local servers
bound on 127.0.0.1 and on a second loopback address that stands in for the
compatibility address; they answer only on the address the fake container
currently publishes. Telemetry ``last_persisted_at`` advances only while the
Edge bridge reaches the central broker.
"""

from __future__ import annotations

import contextlib
import copy
import http.server
import importlib.util
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs" / "operations" / "network" / "wp2c-stage3-backend.py"
SPEC = importlib.util.spec_from_file_location("wp2c_stage3_backend", TOOL)
assert SPEC and SPEC.loader
S3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = S3
SPEC.loader.exec_module(S3)

SITE_IP = "172.18.48.66"
FAKE_COMPAT = "127.0.0.2"  # stands in for the compatibility address in the fake site
NODE = os.uname().nodename.split(".")[0]
SHARED = "nexolab-standalone-runtime"
CMQTT, TELEM, MINIO, DASH, EMQTT = ("nexolab-central-mqtt-1", "nexolab-central-telemetry-service-1",
                                    "nexolab-central-minio-1", "nexolab-central-dashboard-1", "nexolab-edge-mqtt-1")
AGENT, PG = "nexolab-edge-device-agent-1", "nexolab-central-postgres-1"
CLIENT_ID = "nexolab-edge-01-bridge"
OBJ_URL = "http://127.0.0.1:9000"
MOSQ_ID = "sha256:" + "1" * 64
EDGE_SCRIPT = ': "${CENTRAL_MQTT_HOST:?required}"\ncat > /tmp/m.conf <<EOF\naddress ${CENTRAL_MQTT_HOST}:${CENTRAL_MQTT_PORT}\n' \
              'remote_clientid ${CENTRAL_BRIDGE_CLIENT_ID}\ncleansession false\nEOF\nexec mosquitto -c /tmp/m.conf'
MQTT_HC = {"Test": ["CMD-SHELL", "mosquitto_sub -h 127.0.0.1 -t '$SYS/broker/version' -C 1 -W 5"],
           "Interval": 10_000_000_000, "Timeout": 5_000_000_000, "Retries": 5}

FAKE_DOCKER = r'''
import copy, json, os, re, sys, uuid
state_path = os.environ["FAKE_DOCKER_STATE"]
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)
C = state["containers"]

def save():
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, state_path)

def out(value):
    sys.stdout.write(json.dumps(value))
    sys.exit(0)

def fail(message, code=1):
    sys.stderr.write(message)
    sys.exit(code)

def find(ref):
    for name, item in C.items():
        if ref in (name, item["Id"]):
            return name
    return None

KEY = re.compile(r'^("(?:[^"\\]|\\.)*"):(.*)$')

def parse_yaml(text):
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    def ind(line):
        return len(line) - len(line.lstrip())
    def block(i, indent):
        if lines[i][indent:].startswith("- "):
            items = []
            while i < len(lines) and ind(lines[i]) == indent and lines[i][indent:].startswith("- "):
                rest = lines[i][indent + 2:]
                if KEY.match(rest):
                    lines[i] = " " * (indent + 2) + rest
                    value, i = block(i, indent + 2)
                    items.append(value)
                else:
                    items.append(json.loads(rest))
                    i += 1
            return items, i
        obj = {}
        while i < len(lines) and ind(lines[i]) == indent and not lines[i][indent:].startswith("- "):
            m = KEY.match(lines[i][indent:])
            key, rest = json.loads(m.group(1)), m.group(2).strip()
            i += 1
            if rest == "":
                value, i = block(i, indent + 2)
            elif rest == "{}":
                value = {}
            elif rest == "[]":
                value = []
            else:
                value = json.loads(rest)
            obj[key] = value
        return obj, i
    return block(0, 0)[0]

def unesc(v):
    if isinstance(v, str):
        return v.replace("$$", "$")
    if isinstance(v, list):
        return [unesc(x) for x in v]
    if isinstance(v, dict):
        return {k: unesc(x) for k, x in v.items()}
    return v

def port_parts(text):
    hip, hport, rest = text.split(":")
    target, _, proto = rest.partition("/")
    return hip, hport, target, proto or "tcp"

if args[:2] == ["inspect", "--type"]:
    name = find(args[3])
    if name is None:
        fail("Error: No such container: " + args[3])
    out([C[name]])
if args[:2] == ["image", "inspect"]:
    for key, image in state["images"].items():
        if args[2] in (key, image["Id"]):
            out([image])
    fail("Error: No such image: " + args[2])
if args[:2] == ["network", "inspect"]:
    net = args[2]
    members = {item["Id"]: {"Name": name, "IPv4Address": item["NetworkSettings"]["Networks"][net]["IPAddress"] + "/16"}
               for name, item in C.items() if net in item["NetworkSettings"]["Networks"] and item["State"]["Running"]}
    out([{"Name": net, "Containers": members}])
if args[0] == "exec":
    if args[2:4] != ["getent", "hosts"] or state.get("dns_fail"):
        fail("exec failed", 2)
    source = C[find(args[1])]
    for name, item in C.items():
        for net, endpoint in item["NetworkSettings"]["Networks"].items():
            if net in source["NetworkSettings"]["Networks"] and args[4] in (endpoint.get("Aliases") or []):
                sys.stdout.write(endpoint["IPAddress"] + "      " + args[4] + "\n")
                sys.exit(0)
    fail("", 2)
if args[0] == "compose":
    path = args[args.index("--file") + 1]
    base = os.path.basename(path)
    project = args[args.index("--project-name") + 1]
    doc = parse_yaml(open(path, encoding="utf-8").read())
    service_name, svc = next(iter(doc["services"].items()))
    if "config" in args:
        rendered = copy.deepcopy(svc)
        rendered["environment"] = {e.partition("=")[0]: unesc(e.partition("=")[2]) for e in svc["environment"]}
        rendered["ports"] = []
        for p in svc.get("ports", []):
            hip, hport, target, proto = port_parts(p)
            rendered["ports"].append({"mode": "ingress", "host_ip": hip, "target": int(target), "published": hport,
                                      "protocol": proto})
        rendered["networks"] = {n: (v or None) for n, v in svc["networks"].items()}
        for key in ("command", "entrypoint", "labels", "healthcheck"):
            if key in rendered:
                rendered[key] = unesc(rendered[key])
        tamper = state.get("config_tamper", {}).get(base)
        if tamper:
            rendered["environment"][tamper] = "tampered"
        out({"name": project, "services": {service_name: rendered}, "networks": doc.get("networks", {}),
             "volumes": doc.get("volumes", {})})
    if "up" in args:
        effect = state.get("on_up", {}).get(base, {})
        if effect.get("fail"):
            fail("compose failed", 1)
        name = f"{project}-{service_name}-1"
        item = copy.deepcopy(C[name])
        item["Id"] = uuid.uuid4().hex + uuid.uuid4().hex
        item["Config"]["Image"] = svc["image"]
        item["Config"]["Env"] = [unesc(e) for e in svc["environment"]]
        bindings = {}
        for p in svc.get("ports", []):
            hip, hport, target, proto = port_parts(p)
            bindings.setdefault(f"{target}/{proto}", []).append({"HostIp": hip, "HostPort": hport})
        item["HostConfig"]["PortBindings"] = bindings
        nets = {}
        for net, value in svc["networks"].items():
            old = C[name]["NetworkSettings"]["Networks"].get(net) or {"IPAddress": "172.30.0.99"}
            nets[net] = {"Aliases": [name, service_name] + list((value or {}).get("aliases", [])), "IPAMConfig": None,
                         "IPAddress": old["IPAddress"]}
        item["NetworkSettings"]["Networks"] = nets
        mounts = []
        for v in svc.get("volumes", []):
            mounts.append({"Type": v["type"], "Name": v["source"] if v["type"] == "volume" else "",
                           "Source": v["source"], "Destination": v["target"], "RW": not v.get("read_only", False)})
        item["Mounts"] = mounts
        item["Config"]["Labels"]["com.docker.compose.project.config_files"] = path
        item["State"] = {"Running": True, "StartedAt": uuid.uuid4().hex,
                         "Health": {"Status": effect.get("health", "healthy")} if item["Config"].get("Healthcheck") else None}
        if effect.get("drop_env"):
            item["Config"]["Env"] = [e for e in item["Config"]["Env"] if not e.startswith(effect["drop_env"] + "=")]
        for key, value in effect.get("set_state", {}).items():
            state[key] = value
        C[name] = item
        save()
        sys.exit(1 if effect.get("partial_fail") else 0)
fail("fake docker: unsupported " + " ".join(args), 99)
'''


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def container(name: str, project: str, service: str, image: str, image_id: str, *, env: list[str], ports: dict,
              networks: dict, mounts: list | None = None, healthcheck: dict | None = None, cmd=None, entrypoint=None) -> dict:
    return {
        "Id": (name.encode().hex() * 4)[:64], "Name": "/" + name, "Image": image_id, "RestartCount": 0,
        "Config": {"Image": image, "Env": env, "Labels": {"com.docker.compose.project": project,
                                                         "com.docker.compose.service": service,
                                                         "com.docker.compose.project.config_files": "/var/lib/x.yaml"},
                   "Healthcheck": healthcheck, "Cmd": cmd, "Entrypoint": entrypoint, "ExposedPorts": {}},
        "HostConfig": {"PortBindings": ports, "NetworkMode": sorted(networks)[0],
                       "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                       "LogConfig": {"Type": "json-file", "Config": {}}, "ShmSize": 67108864},
        "NetworkSettings": {"Networks": {n: {"Aliases": [name, service] + extra, "IPAMConfig": None, "IPAddress": ip}
                                         for n, (ip, extra) in networks.items()}},
        "Mounts": mounts or [],
        "State": {"Running": True, "StartedAt": "t0", "Health": {"Status": "healthy"} if healthcheck else None},
    }


class Handler(http.server.BaseHTTPRequestHandler):
    role = ""
    state_path = ""

    def log_message(self, *args) -> None:  # noqa: D401 - quiet
        return

    def reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def published_here(self, item: dict) -> bool:
        address, port = self.server.server_address[:2]
        return any(b["HostIp"] == address and int(b["HostPort"]) == port
                   for items in item["HostConfig"]["PortBindings"].values() for b in items)

    def do_GET(self) -> None:  # noqa: N802
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        containers = state["containers"]
        if self.role == "api":
            item = containers[TELEM]
            if not (item["State"]["Running"] and self.published_here(item)):
                return self.reply(502, b"not published here")
            if self.path != "/health/ready":
                return self.reply(404, b"")
            body = {"status": "ready", "last_persisted_at": persisted(state)}
            return self.reply(200, json.dumps(body).encode())
        if self.role == "dashboard":
            item = containers[DASH]
            if not (item["State"]["Running"] and self.published_here(item)):
                return self.reply(502, b"down")
            body = {"source_commit": "a" * 40, "build_id": state.get("dashboard_build", "Build1")}
            return self.reply(200, json.dumps(body).encode())
        return self.reply(200, b"ok")


def persisted(state: dict) -> str:
    """Advancing timestamp while the Edge bridge reaches the central broker, else a frozen one."""
    C = state["containers"]
    edge = dict(e.partition("=")[::2] for e in C[EMQTT]["Config"]["Env"])
    central = C[CMQTT]
    host, port = edge["CENTRAL_MQTT_HOST"], edge["CENTRAL_MQTT_PORT"]
    published = [(b["HostIp"], b["HostPort"]) for items in central["HostConfig"]["PortBindings"].values() for b in items]
    via_compat = (host, port) in published
    via_dns = (host == "central-mqtt" and port == "1883"
               and "central-mqtt" in central["NetworkSettings"]["Networks"].get(SHARED, {}).get("Aliases", [])
               and not state.get("flow_blocked"))
    if central["State"]["Running"] and (via_compat or via_dns):
        return datetime.now(timezone.utc).isoformat()
    return "2000-01-01T00:00:00+00:00"


class Site:
    """Fake docker + endpoints of the production host."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.ws = tmp / "ws"
        self.state_path = tmp / "state.json"
        self.log_path = tmp / "docker.log"
        self.bin = tmp / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}", encoding="utf-8")
        docker.chmod(0o755)
        self.servers = []
        self.ports = {}
        for role in ("cmqtt", "api", "minio", "dashboard", "emqtt"):
            port = free_port()
            self.ports[role] = port
            handler = type(f"H_{role}", (Handler,), {"role": role, "state_path": str(self.state_path)})
            for address in ("127.0.0.1", FAKE_COMPAT):
                server = http.server.ThreadingHTTPServer((address, port), handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.servers.append(server)
        p = self.ports
        self.receipt = tmp / "backup.receipt.json"
        self.write_receipt(datetime.now(timezone.utc) - timedelta(hours=2))
        cmqtt = container(CMQTT, "nexolab-central", "mqtt", "eclipse-mosquitto:2.0.22", MOSQ_ID,
                          env=["PATH=/usr/bin", "VERSION=2.0.22"],
                          ports={"1883/tcp": [{"HostIp": FAKE_COMPAT, "HostPort": str(p["cmqtt"])}]},
                          networks={"nexolab-central": ("172.19.0.6", []), SHARED: ("172.21.0.2", ["central-mqtt"])},
                          mounts=[{"Type": "volume", "Name": "nexolab-central-mqtt-data", "Destination": "/mosquitto/data",
                                   "RW": True, "Driver": "local"},
                                  {"Type": "volume", "Name": "e" * 64, "Destination": "/mosquitto/log", "RW": True,
                                   "Driver": "local"},
                                  {"Type": "bind", "Source": "/etc/nexolab/mosquitto.central.conf",
                                   "Destination": "/mosquitto/config/mosquitto.conf", "RW": False, "Propagation": "rprivate"}],
                          healthcheck=MQTT_HC)
        telem = container(TELEM, "nexolab-central", "telemetry-service", "nexolab/telemetry-service:r1", "sha256:" + "2" * 64,
                          env=["MQTT_HOST=mqtt", "MQTT_PORT=1883", "DATABASE_URL=postgresql+psycopg://u:p$ss@postgres:5432/n",
                               f"OBJECT_STORAGE_PUBLIC_ENDPOINT_URL=http://{FAKE_COMPAT}:9000",
                               "OBJECT_STORAGE_ENDPOINT_URL=http://minio:9000"],
                          ports={"8082/tcp": [{"HostIp": FAKE_COMPAT, "HostPort": str(p["api"])}]},
                          networks={"nexolab-central": ("172.19.0.7", []), SHARED: ("172.21.0.5", [])},
                          healthcheck={"Test": ["CMD", "python", "-c", "ready()"], "Interval": 10_000_000_000, "Retries": 3})
        minio = container(MINIO, "nexolab-central", "minio", "nexolab/object-storage:v1", "sha256:" + "3" * 64,
                          env=["ROOT_SECRET_ACCESS_KEY=not-a-real-secret", "VGW_PORT=:9000"],
                          ports={"9000/tcp": [{"HostIp": FAKE_COMPAT, "HostPort": str(p["minio"])}]},
                          networks={"nexolab-central": ("172.19.0.4", [])},
                          mounts=[{"Type": "volume", "Name": "nexolab-central-object-storage-data", "Destination": "/data",
                                   "RW": True, "Driver": "local"}])
        dash = container(DASH, "nexolab-central", "dashboard", "nexolab/dashboard:issue-1643-7db6e1a8-arm64",
                         "sha256:" + "4" * 64, env=["NODE_ENV=production"],
                         ports={"3000/tcp": [{"HostIp": FAKE_COMPAT, "HostPort": str(p["dashboard"])}]},
                         networks={"nexolab-central": ("172.19.0.5", [])},
                         healthcheck={"Test": ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:3000/')\""], "Retries": 3})
        emqtt = container(EMQTT, "nexolab-edge", "mqtt", "eclipse-mosquitto:2.0.22", MOSQ_ID,
                          env=[f"CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}", f"CENTRAL_MQTT_HOST={FAKE_COMPAT}",
                               f"CENTRAL_MQTT_PORT={p['cmqtt']}", "CENTRAL_MQTT_TOPIC=nexolab/telemetry", "PATH=/usr/bin"],
                          ports={"1883/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(p["emqtt"])}]},
                          networks={"nexolab-edge_default": ("172.18.0.2", []), SHARED: ("172.21.0.3", [])},
                          mounts=[{"Type": "volume", "Name": "nexolab-edge_mqtt-data", "Destination": "/mosquitto/data",
                                   "RW": True, "Driver": "local"},
                                  {"Type": "volume", "Name": "f" * 64, "Destination": "/mosquitto/log", "RW": True,
                                   "Driver": "local"}],
                          healthcheck=MQTT_HC, entrypoint=["/bin/sh", "-ec"], cmd=[EDGE_SCRIPT])
        agent = container(AGENT, "nexolab-edge", "device-agent", "nexolab/quick-agent:1490", "sha256:" + "5" * 64,
                          env=["MQTT_HOST=mqtt", "DEVICE_MODE=modbus"], ports={},
                          networks={"nexolab-edge_default": ("172.18.0.3", []), SHARED: ("172.21.0.4", ["edge-device-agent"])},
                          healthcheck={"Test": ["CMD", "python3", "-c", "health()"]})
        pg = container(PG, "nexolab-central", "postgres", "postgres:16", "sha256:" + "6" * 64, env=["PGDATA=/var/lib/pg"],
                       ports={}, networks={"nexolab-central": ("172.19.0.2", [])},
                       healthcheck={"Test": ["CMD", "pg_isready"]})
        containers = {c["Name"][1:]: c for c in (cmqtt, telem, minio, dash, emqtt, agent, pg)}

        def image(image_id: str, tag: str, volumes: list[str] | None = None) -> dict:
            return {"Id": image_id, "RepoTags": [tag], "Config": {"Volumes": {v: {} for v in volumes or []}, "Labels": {}}}

        images = {}
        for item in containers.values():
            vols = ["/mosquitto/data", "/mosquitto/log"] if "mosquitto" in item["Config"]["Image"] else []
            img = image(item["Image"], item["Config"]["Image"], vols)
            images[item["Config"]["Image"]] = img
            images[item["Image"]] = img
        self.state = {"containers": containers, "images": images}
        self.save()
        self.log_path.write_text("")

    def write_receipt(self, when: datetime, **extra) -> None:
        body = {"kind": "nexolab-dr-backup-receipt", "status": "CAPTURED_RESTORE_UNVERIFIED",
                "completed_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), **extra}
        self.receipt.write_text(json.dumps(body), encoding="utf-8")

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")

    def load(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def update(self, **changes) -> None:
        state = self.load()
        state.update(changes)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

    def compose_ups(self) -> list[str]:
        return [Path(c[c.index("--file") + 1]).name for c in self.calls() if c[0] == "compose" and "up" in c]

    def close(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def argv(self, mode: str, *extra: str) -> list[str]:
        base = [mode, "--workspace", str(self.ws), "--compat-ip", FAKE_COMPAT, "--expect-node", NODE,
                "--lock-path", str(self.tmp / "launch.lock"), "--reserve-gib", "0", "--docker-root", "",
                "--wait-seconds", "3", "--continuity-seconds", "2"]
        if mode in ("plan", "check", "execute", "drop-compat"):
            base += ["--dashboard-host-port", str(self.ports["dashboard"])]
        if mode == "drop-compat":
            base += ["--object-storage-public-url", OBJ_URL]
        if mode in ("check", "execute", "drop-compat"):
            base += ["--backup-receipt", str(self.receipt)]
        return base + list(extra)

    def main(self, mode: str, *extra: str, raw: list[str] | None = None) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_DOCKER_STATE": str(self.state_path),
               "FAKE_DOCKER_LOG": str(self.log_path)}
        with mock.patch.dict(os.environ, env), mock.patch.object(S3, "POLL_SECONDS", 0.05), \
                mock.patch.object(S3, "loopback_port_free", return_value=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S3.main(raw if raw is not None else self.argv(mode, *extra))
        return rc, out.getvalue() + err.getvalue()


FORBIDDEN = {"down", "prune", "--remove-orphans", "-v", "--volumes", "rm", "kill", "stop", "restart", "rmi", "system",
             "volume", "create", "--renew-anon-volumes", "connect", "disconnect", "run", "build", "pull", "cp"}


class SiteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        try:
            self.site = Site(Path(self._tmp.name))
        except OSError as error:  # a second loopback address is a Linux property
            self._tmp.cleanup()
            self.skipTest(f"cannot bind {FAKE_COMPAT}: {error}")

    def tearDown(self) -> None:
        self.site.close()
        self._tmp.cleanup()

    def assert_safe_calls(self) -> None:
        calls = self.site.calls()
        for call in calls:
            self.assertFalse(FORBIDDEN & set(call), call)
            if call[0] == "network":
                self.assertEqual(call[1], "inspect", call)
            if call[0] == "exec":
                self.assertEqual(call[2:4], ["getent", "hosts"], call)
            if call[0] == "compose":
                self.assertTrue("config" in call or "up" in call, call)
            if call[0] == "compose" and "up" in call:
                for flag in ("--no-deps", "--no-build", "--force-recreate", "--detach"):
                    self.assertIn(flag, call)
                self.assertEqual(call[call.index("--pull") + 1], "never")
                self.assertTrue(any(tok.startswith("nexolab-") for tok in call))
            self.assertFalse(any("/dev/" in tok or "serial" in tok.lower() or "modbus" in tok.lower() for tok in call), call)

    def reports(self) -> list[dict]:
        paths = sorted((self.site.ws / "runs").glob("*/*-report-*.json"))
        for path in paths:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        return [json.loads(p.read_text()) for p in paths]


def model_fixture(switched: bool = False) -> dict:
    """Broker docker.service-model shape (secrets redacted) of the live topology (or after the switch)."""
    def item(name, project, service, env, ports, networks, image="img", image_id="sha256:" + "9" * 64):
        return {"name": name, "image": image, "image_id": image_id, "env": env, "port_bindings": ports,
                "labels": {"com.docker.compose.project": project, "com.docker.compose.service": service},
                "networks": {n: {"aliases": a, "ip": "172.21.0.9"} for n, a in networks.items()},
                "mounts": [], "restart_policy": "unless-stopped"}
    model = {"ok": True, "op": "docker.service-model", "result": {"containers": [
        item(CMQTT, "nexolab-central", "mqtt", ["PATH=<set>"], {"1883/tcp": [{"HostIp": SITE_IP, "HostPort": "1884"}]},
             {"nexolab-central": ["mqtt"], SHARED: ["mqtt", "central-mqtt"]}),
        item(TELEM, "nexolab-central", "telemetry-service",
             ["MQTT_HOST=mqtt", f"OBJECT_STORAGE_PUBLIC_ENDPOINT_URL=http://{SITE_IP}:9000", "DATABASE_URL=[REDACTED]",
              "CORS_ALLOWED_ORIGINS=<set>"], {"8082/tcp": [{"HostIp": SITE_IP, "HostPort": "8082"}]},
             {"nexolab-central": ["telemetry-service"], SHARED: ["telemetry-service"]}),
        item(MINIO, "nexolab-central", "minio", ["ROOT_SECRET_ACCESS_KEY=[REDACTED]"],
             {"9000/tcp": [{"HostIp": SITE_IP, "HostPort": "9000"}]}, {"nexolab-central": ["minio"]}),
        item(DASH, "nexolab-central", "dashboard", ["NODE_ENV=production"],
             {"3000/tcp": [{"HostIp": SITE_IP, "HostPort": "3000"}]}, {"nexolab-central": ["dashboard"]}),
        item(EMQTT, "nexolab-edge", "mqtt", [f"CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}", f"CENTRAL_MQTT_HOST={SITE_IP}",
                                             "CENTRAL_MQTT_PORT=1884", "CENTRAL_MQTT_PASSWORD_FILE=[REDACTED]"],
             {"1883/tcp": [{"HostIp": "127.0.0.1", "HostPort": "1883"}]},
             {"nexolab-edge_default": [EMQTT, "mqtt"], SHARED: [EMQTT, "mqtt"]}),
        item(AGENT, "nexolab-edge", "device-agent", ["MQTT_HOST=mqtt"], {"8081/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8081"}]},
             {"nexolab-edge_default": ["device-agent"], SHARED: ["device-agent", "edge-device-agent"]}),
        item(AGENT + "-pre-1490", "nexolab-edge", "device-agent", ["MQTT_HOST=mqtt"], {},
             {SHARED: ["device-agent", "edge-device-agent"]}),
    ]}}
    if switched:
        for entry in model["result"]["containers"]:
            for items in entry["port_bindings"].values():
                if items[0]["HostIp"] == SITE_IP:
                    items.append({"HostIp": "127.0.0.1", "HostPort": items[0]["HostPort"]})
            if entry["name"] == EMQTT:
                entry["env"] = [e.replace(f"HOST={SITE_IP}", "HOST=central-mqtt").replace("PORT=1884", "PORT=1883")
                                for e in entry["env"]]
    return model


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.model = Path(self._tmp.name) / "model.json"
        self.model.write_text(json.dumps(model_fixture()), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def plan(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S3.main(["plan", "--from-model", str(self.model), *extra])
        return rc, out.getvalue()

    def plan_json(self, *extra: str) -> dict:
        rc, output = self.plan("--json", *extra)
        self.assertEqual(rc, 0, output)
        return json.loads(output[: output.rindex("STAGE3_PLAN_OK")])

    def test_plan_deltas_exactly_as_specified(self) -> None:
        plan = self.plan_json()
        self.assertEqual(plan["order"], ["central-mqtt", "telemetry-service", "minio", "dashboard", "edge-mqtt"])
        got = {s["key"]: (s["ports"], s["env"]) for s in plan["services"]}

        def port(cport, host_port, new_port=None):  # ADD loopback, KEEP the compatibility publish
            return [{"container_port": cport, "action": "add", "binding": ["127.0.0.1", new_port or host_port],
                     "keep": [SITE_IP, host_port]}]

        self.assertEqual(got, {
            "central-mqtt": (port("1883/tcp", "1884"), {}),
            "telemetry-service": (port("8082/tcp", "8082"), {}),  # object-storage URL changes only in drop-compat
            "minio": (port("9000/tcp", "9000"), {}),
            "dashboard": (port("3000/tcp", "3000"), {}),
            "edge-mqtt": ([], {"CENTRAL_MQTT_HOST": [SITE_IP, "central-mqtt"], "CENTRAL_MQTT_PORT": ["1884", "1883"]}),
        })
        edge = plan["services"][-1]
        self.assertEqual(edge["preserved"], {"CENTRAL_BRIDGE_CLIENT_ID": CLIENT_ID})
        self.assertEqual(plan["aliases"]["bridge_host_carriers"], [CMQTT])
        self.assertEqual(plan["aliases"]["ambiguous_aliases"]["mqtt"], [CMQTT, EMQTT])
        self.assertIn(f"{AGENT} MQTT_HOST=mqtt", plan["aliases"]["ambiguous_consumers"])
        consumers = "\n".join(plan["external_consumers"])
        for needle in (":8443 /api", ":8444", "nexolab-lan-gateway", "nexolab-compat-address.service"):
            self.assertIn(needle, consumers)
        self.assertEqual(plan["blockers"], [])
        self.assertTrue(plan["env_values_redacted"])
        self.assertEqual(plan["phase"], "switch")
        self.assertEqual(plan["aliases"]["exclusive_alias_unproven"], [f"edge-device-agent:{AGENT}-pre-1490"])

    def test_drop_compat_plan_removes_only_compat_bindings(self) -> None:
        self.model.write_text(json.dumps(model_fixture(switched=True)), encoding="utf-8")
        plan = self.plan_json("--phase", "drop-compat", "--object-storage-public-url", OBJ_URL)
        self.assertEqual(plan["order"], ["central-mqtt", "telemetry-service", "minio", "dashboard"])
        got = {s["key"]: (s["ports"], s["env"]) for s in plan["services"]}

        def port(cport, host_port):
            return [{"container_port": cport, "action": "remove", "binding": [SITE_IP, host_port],
                     "keep": ["127.0.0.1", host_port]}]

        self.assertEqual(got, {
            "central-mqtt": (port("1883/tcp", "1884"), {}),
            "telemetry-service": (port("8082/tcp", "8082"),
                                  {"OBJECT_STORAGE_PUBLIC_ENDPOINT_URL": [f"http://{SITE_IP}:9000", OBJ_URL]}),
            "minio": (port("9000/tcp", "9000"), {}),
            "dashboard": (port("3000/tcp", "3000"), {}),
        })
        self.assertEqual(plan["blockers"], [])

    def test_drop_compat_refuses_before_the_switch(self) -> None:
        rc, output = self.plan("--phase", "drop-compat", "--object-storage-public-url", OBJ_URL)
        self.assertEqual(rc, 2)
        self.assertIn("LOOPBACK_BINDING_MISSING", output)

    def test_object_storage_url_belongs_to_drop_compat(self) -> None:
        rc, output = self.plan("--object-storage-public-url", OBJ_URL)
        self.assertEqual(rc, 2)
        self.assertIn("OBJECT_STORAGE_PUBLIC_URL_IS_DROP_COMPAT_ONLY", output)

    def test_dashboard_host_port_is_configurable(self) -> None:
        plan = self.plan_json("--dashboard-host-port", "3010")
        dash = next(s for s in plan["services"] if s["key"] == "dashboard")
        self.assertEqual(dash["ports"][0]["binding"], ["127.0.0.1", "3010"])
        self.assertEqual(dash["ports"][0]["keep"], [SITE_IP, "3000"])

    def test_text_plan_hides_unchanged_env_values(self) -> None:
        rc, output = self.plan()
        self.assertEqual(rc, 0, output)
        self.assertIn("publish 1883/tcp: add 127.0.0.1:1884 (keep 172.18.48.66:1884)", output)
        self.assertIn("env CENTRAL_MQTT_HOST: 172.18.48.66 -> central-mqtt", output)
        self.assertIn(f"preserved CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}", output)
        self.assertIn("HAZARD alias 'mqtt'", output)
        self.assertNotIn("DATABASE_URL", output)
        self.assertNotIn("[REDACTED]", output)

    def test_bridge_host_mqtt_and_ip_literals_are_refused(self) -> None:
        for host in ("mqtt", "MQTT", SITE_IP, "10.0.0.5", "::1", "[::1]", "localhost", "central_mqtt", "a.b"):
            rc, output = self.plan("--bridge-host", host)
            self.assertEqual(rc, 2, host)
            self.assertIn("BRIDGE_HOST_", output, host)

    def test_bridge_host_must_be_unique_to_central_mqtt(self) -> None:
        rc, output = self.plan("--bridge-host", "edge-device-agent")
        self.assertEqual(rc, 2)
        self.assertIn("BRIDGE_HOST_NOT_ON_CENTRAL_MQTT", output)

    def test_object_storage_url_is_required_and_never_an_ip(self) -> None:
        for value, reason in ((None, "OBJECT_STORAGE_PUBLIC_URL_REQUIRED"), ("/objects", "NOT_ABSOLUTE"),
                              (f"http://{SITE_IP}:9000", "USES_COMPAT_ADDRESS"), ("http://10.1.2.3:9000", "IP_LITERAL")):
            extra = ["--object-storage-public-url", value] if value is not None else []
            rc, output = self.plan("--phase", "drop-compat", *extra)
            self.assertEqual(rc, 2, value)
            self.assertIn(reason, output)

    def test_model_is_never_an_execution_input(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S3.main(["execute", "--from-model", str(self.model)])
        self.assertEqual(rc, 2)
        self.assertIn("FROM_MODEL_IS_PLAN_ONLY", out.getvalue())


class ComposeModelTests(SiteTestCase):
    def test_candidate_differs_from_rollback_only_in_deltas(self) -> None:
        state = self.site.state
        args = S3.parser().parse_args(self.site.argv("plan"))
        args.untouched = list(S3.DEFAULT_UNTOUCHED)
        views = {name: S3.view_from_inspect(c) for name, c in state["containers"].items()}
        plan = S3.build_plan(views, args)
        self.assertEqual(plan["blockers"], [])
        for spec, delta in zip(S3.SERVICES, plan["services"]):
            item = state["containers"][spec.container]
            rollback = S3.service_model(item, state["images"][item["Image"]], FAKE_COMPAT)
            candidate = S3.candidate_document(rollback, spec, delta)
            rb = S3.to_yaml(rollback).splitlines()
            cd = S3.to_yaml(candidate).splitlines()
            removed = sorted(line.strip() for line in rb if line not in cd)
            added = sorted(line.strip() for line in cd if line not in rb)
            self.assertTrue(all(p["action"] == "add" for p in delta["ports"]))
            want_removed = [f'- "{k}={old}"' for k, (old, _) in delta["env"].items()]  # no publish is removed
            want_added = [f'- "{p["binding"][0]}:{p["binding"][1]}:{p["container_port"]}"' for p in delta["ports"]]
            want_added += [f'- "{k}={new}"' for k, (_, new) in delta["env"].items()]
            self.assertEqual(removed, sorted(want_removed), spec.key)
            self.assertEqual(added, sorted(want_added), spec.key)
            text = "\n".join(rb)
            self.assertNotIn("com.docker.compose", text)
            self.assertIn('"external": true', text)
            self.assertIn('"pull_policy": "never"', text)
            if spec.key == "edge-mqtt":
                self.assertIn(f'"CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}"', "\n".join(cd))
                self.assertIn("$${CENTRAL_MQTT_HOST", text)  # Compose interpolation escaped
            if spec.key == "central-mqtt":
                self.assertIn('"source": "' + "e" * 64 + '"', text)  # anonymous log volume pinned, never recreated
                self.assertIn('"create_host_path": false', text)

    def test_plan_from_docker_inspect_array_derives_compose_models(self) -> None:
        model = self.site.tmp / "inspect.json"
        model.write_text(json.dumps(list(self.site.state["containers"].values())), encoding="utf-8")
        rc, output = self.site.main("plan", "--from-model", str(model))
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_PLAN_OK", output)
        self.assertIn(f"env CENTRAL_MQTT_HOST: {FAKE_COMPAT} -> central-mqtt", output)
        self.assertNotIn("not-a-real-secret", output)
        self.assertEqual(self.site.calls(), [])  # offline review: no docker call at all

    def test_live_plan_is_read_only(self) -> None:
        rc, output = self.site.main("plan")
        self.assertEqual(rc, 0, output)
        for call in self.site.calls():
            self.assertIn(call[:2], (["inspect", "--type"], ["image", "inspect"], ["network", "inspect"]), call)
        self.assertFalse(self.site.ws.exists())

    def test_empty_and_absent_image_fields_are_equal(self) -> None:
        # Site prove 2026-11-26: container Config.User "" while the containerd image store omits an empty image
        # User -> v1 rendered `user: ""`, which Compose drops -> COMPOSE_FIDELITY_FAILED ['user'].
        base = copy.deepcopy(self.site.state["containers"][CMQTT])
        image = copy.deepcopy(self.site.state["images"][base["Image"]])
        image["Config"].pop("User", None)
        base["Config"].update(User="", WorkingDir="", Entrypoint=None, Cmd=None)
        model = S3.service_model(base, image, FAKE_COMPAT)["services"]["mqtt"]
        for key in ("user", "working_dir", "entrypoint", "command"):
            self.assertNotIn(key, model, key)
        base["Config"]["User"] = "1883:1883"
        self.assertEqual(S3.service_model(base, image, FAKE_COMPAT)["services"]["mqtt"]["user"], "1883:1883")
        image["Config"]["User"] = "mosquitto"
        base["Config"]["User"] = ""
        with self.assertRaises(S3.Stop):  # Compose cannot express "reset the image user to empty"
            S3.service_model(base, image, FAKE_COMPAT)

    def test_prove_passes_with_empty_container_user(self) -> None:
        state = self.site.load()
        for item in state["containers"].values():
            item["Config"]["User"] = ""
            item["Config"]["WorkingDir"] = ""
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("prove")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_PROVE_GREEN", output)

    def test_unsupported_settings_fail_closed(self) -> None:
        base = self.site.state["containers"][CMQTT]
        image = self.site.state["images"][base["Image"]]
        for mutate in (lambda c: c["HostConfig"].update(Privileged=True),
                       lambda c: c["HostConfig"].update(Devices=[{"PathOnHost": "/dev/ttyUSB0"}]),
                       lambda c: c["Mounts"].pop(1),  # image VOLUME without a mount -> anonymous volume creation
                       lambda c: c["NetworkSettings"]["Networks"][SHARED].update(IPAMConfig={"IPv4Address": "172.21.0.2"}),
                       lambda c: c["Config"].update(Cmd=["mosquitto", "-h", FAKE_COMPAT])):
            item = copy.deepcopy(base)
            mutate(item)
            with self.assertRaises(S3.Stop):
                S3.service_model(item, image, FAKE_COMPAT)


class CheckTests(SiteTestCase):
    def test_check_passes_read_only(self) -> None:
        rc, output = self.site.main("check")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_CHECK_PASS NO_WRITES", output)
        self.assertIn("BRIDGE_DNS_OK central-mqtt -> 172.21.0.2", output)
        for call in self.site.calls():
            readonly = (call[:2] in (["inspect", "--type"], ["image", "inspect"], ["network", "inspect"])
                        or call[0] == "exec" and call[2:4] == ["getent", "hosts"])
            self.assertTrue(readonly, call)
        self.assertFalse((self.site.ws / "runs").exists())
        self.assert_safe_calls()

    def test_check_refuses_without_backup_receipt(self) -> None:
        argv = [a for a in self.site.argv("check")]
        index = argv.index("--backup-receipt")
        del argv[index:index + 2]
        rc, output = self.site.main("check", raw=argv)
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_REQUIRED", output)
        self.assertEqual(self.site.calls(), [])

    def test_check_refuses_stale_missing_or_invalid_receipt(self) -> None:
        self.site.write_receipt(datetime.now(timezone.utc) - timedelta(hours=30))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_STALE", output)
        rc, output = self.site.main("check", "--max-backup-age-hours", "48")
        self.assertEqual(rc, 0, output)
        self.site.receipt.write_text(json.dumps({"completed_at": datetime.now(timezone.utc).isoformat()}))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_STATUS_MISSING", output)
        self.site.write_receipt(datetime.now(timezone.utc), status="FAILED")
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_STATUS_FAILED", output)
        self.site.receipt.write_text("not json")
        rc, output = self.site.main("check")
        self.assertIn("BACKUP_RECEIPT_NOT_JSON", output)
        self.site.receipt.unlink()
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_MISSING", output)

    def test_check_refuses_unhealthy_container(self) -> None:
        state = self.site.load()
        state["containers"][AGENT]["State"]["Health"]["Status"] = "unhealthy"
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn(f"CONTAINER_UNHEALTHY {AGENT}", output)

    def test_check_refuses_duplicate_bridge_alias(self) -> None:
        state = self.site.load()
        state["containers"][EMQTT]["NetworkSettings"]["Networks"][SHARED]["Aliases"].append("central-mqtt")
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn(f"EXCLUSIVE_ALIAS_CARRIED_BY_OTHER_RUNNING_CONTAINER central-mqtt:{EMQTT}", output)

    def test_check_refuses_while_pre_stage2_dashboard_runs(self) -> None:
        self.site.update(dashboard_build="CWBsCWWebOZGHa5YyWp18")
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("STAGE2_NOT_ACTIVE", output)
        rc, output = self.site.main("check", "--pre-stage2-build", "OtherBuild")
        self.assertEqual(rc, 0, output)

    def test_check_refuses_other_running_carrier_of_exclusive_alias(self) -> None:
        state = self.site.load()
        stale = copy.deepcopy(state["containers"][AGENT])
        stale["Id"], stale["Name"] = "b" * 64, f"/{AGENT}-pre-1490"
        stale["NetworkSettings"]["Networks"] = {SHARED: {"Aliases": ["device-agent", "edge-device-agent"],
                                                         "IPAMConfig": None, "IPAddress": "172.21.0.9"}}
        state["containers"][f"{AGENT}-pre-1490"] = stale
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn(f"EXCLUSIVE_ALIAS_CARRIED_BY_OTHER_RUNNING_CONTAINER edge-device-agent:{AGENT}-pre-1490", output)
        stale["State"]["Running"] = False  # a stopped container never answers Docker DNS
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 0, output)

    def test_check_refuses_bridge_host_mqtt(self) -> None:
        rc, output = self.site.main("check", "--bridge-host", "mqtt")
        self.assertEqual(rc, 2)
        self.assertIn("BRIDGE_HOST_AMBIGUOUS_REFUSED", output)
        rc, output = self.site.main("check", "--bridge-host", SITE_IP)
        self.assertIn("BRIDGE_HOST_IP_LITERAL_REFUSED", output)

    def test_retained_compat_reference_needs_acknowledgement(self) -> None:
        state = self.site.load()
        state["containers"][TELEM]["Config"]["Env"].append(f"CORS_ALLOWED_ORIGINS=http://{FAKE_COMPAT}:3000")
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn(f"UNACKNOWLEDGED_COMPAT_IP_REFERENCE {TELEM} CORS_ALLOWED_ORIGINS", output)
        rc, output = self.site.main("check", "--retain-env", "CORS_ALLOWED_ORIGINS")
        self.assertEqual(rc, 0, output)

    def test_dns_failure_and_port_in_use_stop(self) -> None:
        self.site.update(dns_fail=True)
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("DOCKER_DNS_FAILED central-mqtt", output)
        self.site.update(dns_fail=False)
        with mock.patch.object(S3, "loopback_port_free", return_value=False):
            out = io.StringIO()
            env = {"PATH": f"{self.site.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                   "FAKE_DOCKER_STATE": str(self.site.state_path), "FAKE_DOCKER_LOG": str(self.site.log_path)}
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = S3.main(self.site.argv("check"))
        self.assertEqual(rc, 2)
        self.assertIn("LOOPBACK_PORT_IN_USE", out.getvalue())

    def test_root_is_refused(self) -> None:
        for mode in ("plan", "check", "execute", "drop-compat", "rollback"):
            with mock.patch.object(S3.os, "geteuid", return_value=0):
                rc, output = self.site.main(mode)
            self.assertEqual(rc, 2)
            self.assertIn("RUN_AS_OPERATOR_NONROOT", output)
        self.assertEqual(self.site.calls(), [])

    def test_wrong_node_and_disk_reserve(self) -> None:
        rc, output = self.site.main("check", "--expect-node", "not-this-host")
        self.assertIn("WRONG_NODE", output)
        with mock.patch.object(S3, "free_bytes", return_value=S3.GIB - 1):
            rc, output = self.site.main("check", "--reserve-gib", "1")
        self.assertEqual(rc, 2)
        self.assertIn("DISK_RESERVE_1GIB_FAILED", output)
        self.assertEqual(S3.parser().parse_args(["check"]).reserve_gib, 20)
        self.assertEqual(self.site.calls(), [])

    def test_held_lock_blocks(self) -> None:
        fd = S3.hold_lock(self.site.tmp / "launch.lock")
        try:
            rc, output = self.site.main("check")
        finally:
            os.close(fd)
        self.assertEqual(rc, 2)
        self.assertIn("ACTIVE_DEPLOYMENT_LOCK", output)


ORDER = ["central-mqtt", "telemetry-service", "minio", "dashboard", "edge-mqtt"]


class ProveTests(SiteTestCase):
    def test_prove_renders_and_proves_without_switching(self) -> None:
        argv = list(self.site.argv("prove"))
        self.assertNotIn("--backup-receipt", argv)  # prove never needs a backup receipt
        rc, output = self.site.main("prove", raw=argv)
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_PROVE_GREEN phase=switch services=5", output)
        self.assertEqual(output.count("COMPOSE_FIDELITY_PROVEN"), 5)
        for call in self.site.calls():
            readonly = (call[:2] in (["inspect", "--type"], ["image", "inspect"], ["network", "inspect"])
                        or (call[0] == "compose" and "config" in call))
            self.assertTrue(readonly, call)
        self.assertFalse([c for c in self.site.calls() if c[0] == "exec" or "up" in c])
        proofs = list((self.site.ws / "proofs").iterdir())
        self.assertEqual(len(proofs), 1)
        self.assertEqual(oct(proofs[0].stat().st_mode & 0o777), "0o700")
        self.assertFalse((self.site.ws / "LATEST").exists())  # never the rollback source
        self.assertFalse((self.site.ws / "runs").exists())
        self.assert_safe_calls()

    def test_prove_stops_on_plan_blockers(self) -> None:
        state = self.site.load()
        state["containers"][EMQTT]["Config"]["Env"] = [e for e in state["containers"][EMQTT]["Config"]["Env"]
                                                       if not e.startswith("CENTRAL_BRIDGE_CLIENT_ID=")]
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("prove")
        self.assertEqual(rc, 2)
        self.assertFalse((self.site.ws / "proofs").exists() and any((self.site.ws / "proofs").iterdir()))


class ExecuteTests(SiteTestCase):
    def test_green_switch_in_order_then_explicit_rollback(self) -> None:
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_BACKEND_GREEN", output)
        self.assertIn("TELEMETRY_CONTINUITY_OK", output)
        self.assertEqual(self.site.compose_ups(), [f"{k}.candidate.compose.yaml" for k in ORDER])
        self.assertLess(output.index("COMPOSE_FIDELITY_PROVEN edge-mqtt"), output.index("STAGE3_SERVICE_SWITCHED central-mqtt"))
        state = self.site.load()["containers"]
        for name in (CMQTT, TELEM, MINIO, DASH):  # dual publish: loopback ADDED, compatibility KEPT
            for cport, items in state[name]["HostConfig"]["PortBindings"].items():
                original = self.site.state["containers"][name]["HostConfig"]["PortBindings"][cport]
                self.assertEqual(sorted((b["HostIp"], b["HostPort"]) for b in items),
                                 sorted([(FAKE_COMPAT, original[0]["HostPort"]), ("127.0.0.1", original[0]["HostPort"])]))
        edge_env = state[EMQTT]["Config"]["Env"]
        self.assertIn(f"CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}", edge_env)  # client ID preserved
        self.assertIn("CENTRAL_MQTT_HOST=central-mqtt", edge_env)
        self.assertIn("CENTRAL_MQTT_PORT=1883", edge_env)
        self.assertEqual(state[TELEM]["Config"]["Env"], self.site.state["containers"][TELEM]["Config"]["Env"])
        self.assertIn("DATABASE_URL=postgresql+psycopg://u:p$ss@postgres:5432/n", state[TELEM]["Config"]["Env"])
        self.assertEqual(state[EMQTT]["Config"]["Cmd"], [EDGE_SCRIPT])
        self.assertEqual(state[CMQTT]["Image"], MOSQ_ID)
        self.assertEqual(state[AGENT]["Id"], self.site.state["containers"][AGENT]["Id"])  # Device Agent untouched
        self.assertEqual(state[PG]["Id"], self.site.state["containers"][PG]["Id"])
        run_dir = next((self.site.ws / "runs").iterdir())
        self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.site.ws.stat().st_mode), 0o700)
        for path in run_dir.glob("*.compose.yaml"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        reports = self.reports()
        self.assertEqual([r["outcome"] for r in reports], ["STAGE3_BACKEND_GREEN"])
        self.assertNotIn("not-a-real-secret", json.dumps(reports))  # no env values in the report
        self.assertNotIn("not-a-real-secret", output)
        self.assert_safe_calls()

        self.site.log_path.write_text("")
        rc, output = self.site.main("rollback")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_ROLLED_BACK_VERIFIED", output)
        self.assertEqual(self.site.compose_ups(), [f"{k}.rollback.compose.yaml" for k in reversed(ORDER)])
        state = self.site.load()["containers"]
        for name in (CMQTT, TELEM, MINIO, DASH, EMQTT):
            self.assertEqual(sorted(state[name]["Config"]["Env"]), sorted(self.site.state["containers"][name]["Config"]["Env"]))
            self.assertEqual(state[name]["HostConfig"]["PortBindings"], self.site.state["containers"][name]["HostConfig"]["PortBindings"])
        self.assert_safe_calls()

        self.site.log_path.write_text("")
        rc, output = self.site.main("rollback")  # idempotent: nothing left to roll back
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.site.compose_ups(), [])
        self.assertEqual(output.count("ALREADY_AT_BASELINE"), 5)

    def test_rerun_after_green_is_refused(self) -> None:
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 0, output)
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2)
        self.assertIn("SERVICE_ALREADY_SWITCHED_OR_UNEXPECTED", output)

    def test_telemetry_failure_rolls_back_telemetry_and_mqtt_in_reverse(self) -> None:
        self.site.update(on_up={"telemetry-service.candidate.compose.yaml": {"health": "unhealthy"}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertIn("ACTIVATION_CHECK_FAILED", output)
        self.assertIn("STAGE3_ROLLED_BACK_VERIFIED", output)
        self.assertNotIn("STAGE3_BACKEND_GREEN", output)
        self.assertEqual(self.site.compose_ups(), ["central-mqtt.candidate.compose.yaml", "telemetry-service.candidate.compose.yaml",
                                                   "telemetry-service.rollback.compose.yaml", "central-mqtt.rollback.compose.yaml"])
        self.assertLess(output.index("STAGE3_SERVICE_ROLLED_BACK telemetry-service"),
                        output.index("STAGE3_SERVICE_ROLLED_BACK central-mqtt"))
        state = self.site.load()["containers"]
        original = self.site.state["containers"]
        self.assertEqual(state[CMQTT]["HostConfig"]["PortBindings"], original[CMQTT]["HostConfig"]["PortBindings"])
        self.assertEqual(state[TELEM]["Config"]["Env"], original[TELEM]["Config"]["Env"])
        for name in (MINIO, DASH, EMQTT, AGENT, PG):
            self.assertEqual(state[name]["Id"], original[name]["Id"], name)  # never touched
        report = self.reports()[-1]
        self.assertEqual(report["outcome"], "ROLLED_BACK_VERIFIED")
        self.assertEqual(report["rolled_back"], ["telemetry-service", "central-mqtt"])
        self.assertIn("SERVICE_NOT_HEALTHY telemetry-service", report["error"])
        self.assert_safe_calls()

    def test_compose_failure_mid_switch_still_rolls_back(self) -> None:
        self.site.update(on_up={"minio.candidate.compose.yaml": {"partial_fail": True}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertEqual(self.site.compose_ups()[3:], ["minio.rollback.compose.yaml", "telemetry-service.rollback.compose.yaml",
                                                       "central-mqtt.rollback.compose.yaml"])

    def test_settings_drift_after_switch_rolls_back(self) -> None:
        self.site.update(on_up={"dashboard.candidate.compose.yaml": {"drop_env": "NODE_ENV"}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertIn("RECREATED_SETTINGS_DIFFER dashboard ['env.NODE_ENV']", output)
        self.assertEqual(self.site.compose_ups()[-4:], [f"{k}.rollback.compose.yaml" for k in reversed(ORDER[:4])])

    def test_continuity_failure_rolls_back_everything(self) -> None:
        self.site.update(on_up={"edge-mqtt.candidate.compose.yaml": {"set_state": {"flow_blocked": True}}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertIn("TELEMETRY_CONTINUITY_NOT_PROVEN", output)
        self.assertEqual(self.site.compose_ups()[5:], [f"{k}.rollback.compose.yaml" for k in reversed(ORDER)])
        self.assertIn("STAGE3_ROLLED_BACK_VERIFIED", output)
        edge_env = self.site.load()["containers"][EMQTT]["Config"]["Env"]
        self.assertIn(f"CENTRAL_MQTT_HOST={FAKE_COMPAT}", edge_env)
        self.assertIn(f"CENTRAL_BRIDGE_CLIENT_ID={CLIENT_ID}", edge_env)

    def test_failed_rollback_is_a_hard_blocker(self) -> None:
        self.site.update(on_up={"telemetry-service.candidate.compose.yaml": {"health": "unhealthy"},
                                "central-mqtt.rollback.compose.yaml": {"fail": True}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 4, output)
        self.assertIn("HARD_BLOCKER_ROLLBACK_UNVERIFIED", output)
        self.assertNotIn("STAGE3_ROLLED_BACK_VERIFIED", output)
        self.assertEqual(self.reports()[-1]["outcome"], "HARD_BLOCKER_ROLLBACK_UNVERIFIED")
        self.assert_safe_calls()

    def test_config_fidelity_failure_stops_before_any_switch(self) -> None:
        self.site.update(config_tamper={"minio.candidate.compose.yaml": "VGW_PORT"})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2, output)
        self.assertIn("COMPOSE_FIDELITY_FAILED minio candidate", output)
        self.assertEqual(self.site.compose_ups(), [])
        self.site.update(config_tamper={"edge-mqtt.rollback.compose.yaml": "CENTRAL_BRIDGE_CLIENT_ID"})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2, output)
        self.assertIn("COMPOSE_FIDELITY_FAILED edge-mqtt rollback", output)
        self.assertEqual(self.site.compose_ups(), [])

    def test_execute_refuses_stale_receipt_before_any_docker_call(self) -> None:
        self.site.write_receipt(datetime.now(timezone.utc) - timedelta(hours=25))
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2)
        self.assertIn("BACKUP_RECEIPT_STALE", output)
        self.assertEqual(self.site.calls(), [])

    def test_tampered_rollback_file_blocks_explicit_rollback(self) -> None:
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 0, output)
        run_dir = next((self.site.ws / "runs").iterdir())
        path = run_dir / "minio.rollback.compose.yaml"
        path.write_text(path.read_text() + "# tamper\n")
        rc, output = self.site.main("rollback")
        self.assertEqual(rc, 2)
        self.assertIn("ROLLBACK_COMPOSE_CHANGED minio.rollback.compose.yaml", output)


class DropCompatTests(SiteTestCase):
    def switch(self) -> None:
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 0, output)
        self.after_switch = self.site.load()["containers"]
        self.site.log_path.write_text("")

    def test_refuses_without_consumers_retargeted(self) -> None:
        self.switch()
        rc, output = self.site.main("drop-compat")
        self.assertEqual(rc, 2)
        self.assertIn("CONSUMERS_NOT_RETARGETED", output)
        self.assertEqual(self.site.calls(), [])

    def test_refuses_before_the_switch(self) -> None:
        rc, output = self.site.main("drop-compat", "--consumers-retargeted")
        self.assertEqual(rc, 2)
        self.assertIn("LOOPBACK_BINDING_MISSING", output)
        self.assertEqual(self.site.compose_ups(), [])

    def test_drop_compat_removes_only_compat_bindings_then_rollback_restores_them(self) -> None:
        self.switch()
        rc, output = self.site.main("drop-compat", "--consumers-retargeted")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE3_DROP_COMPAT_GREEN", output)
        self.assertNotIn("STAGE3_BACKEND_GREEN", output)
        self.assertEqual(self.site.compose_ups(), [f"{k}.candidate.compose.yaml" for k in ORDER[:4]])
        state = self.site.load()["containers"]
        for name in (CMQTT, TELEM, MINIO, DASH):
            before, after = self.after_switch[name], state[name]
            for cport, items in after["HostConfig"]["PortBindings"].items():
                self.assertEqual(items, [b for b in before["HostConfig"]["PortBindings"][cport] if b["HostIp"] != FAKE_COMPAT])
            env_before = [e for e in before["Config"]["Env"] if not e.startswith("OBJECT_STORAGE_PUBLIC_ENDPOINT_URL=")]
            env_after = [e for e in after["Config"]["Env"] if not e.startswith("OBJECT_STORAGE_PUBLIC_ENDPOINT_URL=")]
            self.assertEqual(env_after, env_before, name)
            self.assertEqual(after["Mounts"], before["Mounts"], name)
        self.assertIn(f"OBJECT_STORAGE_PUBLIC_ENDPOINT_URL={OBJ_URL}", state[TELEM]["Config"]["Env"])
        self.assertEqual(state[EMQTT]["Id"], self.after_switch[EMQTT]["Id"])  # bridge untouched in this phase
        self.assert_safe_calls()

        self.site.log_path.write_text("")
        rc, output = self.site.main("rollback")
        self.assertEqual(rc, 0, output)
        self.assertIn("ROLLBACK_RUN", output)
        self.assertIn("phase=drop-compat", output)
        self.assertEqual(self.site.compose_ups(), [f"{k}.rollback.compose.yaml" for k in reversed(ORDER[:4])])
        state = self.site.load()["containers"]
        for name in (CMQTT, TELEM, MINIO, DASH):
            self.assertEqual(S3.sorted_bindings(state[name]["HostConfig"]["PortBindings"]), S3.sorted_bindings(self.after_switch[name]["HostConfig"]["PortBindings"]))
            self.assertEqual(state[name]["Config"]["Env"], self.after_switch[name]["Config"]["Env"])
        self.assert_safe_calls()

    def test_drop_compat_failure_rolls_back_in_reverse(self) -> None:
        self.switch()
        self.site.update(on_up={"minio.candidate.compose.yaml": {"drop_env": "VGW_PORT"}})
        state = self.site.load()
        rc, output = self.site.main("drop-compat", "--consumers-retargeted")
        self.assertEqual(rc, 3, output)
        self.assertEqual(self.site.compose_ups(), ["central-mqtt.candidate.compose.yaml", "telemetry-service.candidate.compose.yaml",
                                                   "minio.candidate.compose.yaml", "minio.rollback.compose.yaml",
                                                   "telemetry-service.rollback.compose.yaml", "central-mqtt.rollback.compose.yaml"])
        after = self.site.load()["containers"]
        for name in (CMQTT, TELEM, MINIO):
            self.assertEqual(S3.sorted_bindings(after[name]["HostConfig"]["PortBindings"]), S3.sorted_bindings(state["containers"][name]["HostConfig"]["PortBindings"]))
        self.assertEqual(after[DASH]["Id"], state["containers"][DASH]["Id"])


class StaticSafetyTests(unittest.TestCase):
    def test_tool_source_has_no_forbidden_operations(self) -> None:
        code = TOOL.read_text(encoding="utf-8").split('"""', 2)[2]  # skip the docstring that names what is forbidden
        for token in ('"--remove-orphans"', '"down"', '"prune"', '"docker", "volume"', '"docker", "rm"', '"docker", "run"',
                      '"docker", "system"', '"-v"', '"--volumes"', '"rm"', '"create"', '"--renew-anon-volumes"',
                      "shell=True", "os.system", "pymodbus", "/dev/tty", "/dev/serial"):
            self.assertNotIn(token, code)
        self.assertIn('"--pull", "never"', code)
        self.assertIn('"network", "inspect"', code)
        self.assertEqual(code.count('"network"'), 1)


if __name__ == "__main__":
    unittest.main()
