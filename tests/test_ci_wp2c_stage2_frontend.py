"""Tests for the WP2c Stage 2 same-origin frontend activation tool (#1734).

Docker is replaced by a fake executable on PATH that records every argv and
serves canned ``docker inspect`` JSON; identity, routes, the LAN gateway and the
API readiness endpoint are local HTTP servers that read the same fake state.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import http.server
import importlib.util
import io
import json
import os
import socket
import stat
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs" / "operations" / "network" / "wp2c-stage2-frontend.py"
SPEC = importlib.util.spec_from_file_location("wp2c_stage2_frontend", TOOL)
assert SPEC and SPEC.loader
S2 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = S2
SPEC.loader.exec_module(S2)

OLD_SRC = "7db6e1a801aa6c1a142febd4e91c79eef62d5beb"
OLD_BUILD = "CWBsCWWebOZGHa5YyWp18"
NEW_SRC = "0123456789abcdef0123456789abcdef01234567"
NEW_BUILD = "NewBuildId_0123456789"
OLD_TAG = "nexolab/dashboard:issue-1643-7db6e1a8-arm64"
NEW_TAG = f"nexolab/dashboard:wp2c-stage2-{NEW_SRC[:12]}-arm64"
OLD_ID = "sha256:" + "a" * 64
NEW_ID = "sha256:" + "b" * 64
DASH = "nexolab-central-dashboard-1"
PREVIEW = "nexolab-wp2c-stage2-preview"
BACKENDS = ["nexolab-central-postgres-1", "nexolab-central-mqtt-1", "nexolab-central-telemetry-service-1",
            "nexolab-edge-device-agent-1", "nexolab-central-minio-1"]
GIB_MINUS_ONE = 1024**3 - 1
NODE = os.uname().nodename.split(".")[0]
HEALTH = {"Test": ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/')"], "Interval": 10_000_000_000,
          "Timeout": 5_000_000_000, "StartPeriod": 20_000_000_000, "Retries": 12}
IMAGE_ENV = ["PATH=/usr/local/bin:/usr/bin", "NODE_ENV=production", "HOSTNAME=0.0.0.0", "PORT=3000"]

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

def image_by(ref):
    for key, image in state["images"].items():
        if ref in (key, image["Id"]):
            return image
    fail("no such image " + ref)

def unq(token):
    return json.loads(token).replace("$$", "$")

def parse(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    image, env, labels, section, depth = None, [], {}, None, 0
    for line in lines:
        if line.lstrip().startswith("#") or not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if section and indent <= depth:
            section = None
        m = re.match(r'^(\s*)"(image|environment|labels)":\s*(.*)$', line)
        if m and section is None:
            if m.group(2) == "image":
                image = unq(m.group(3))
            else:
                section, depth = m.group(2), len(m.group(1))
            continue
        if section == "environment":
            env.append(unq(line.strip()[2:]))
        elif section == "labels":
            km = re.match(r'^\s*(".*?"): (".*")$', line)
            labels[unq(km.group(1))] = unq(km.group(2))
    return image, env, labels

def make(name, ref, env, extra_labels, running, project=None):
    image = image_by(ref)
    item = copy.deepcopy(state["template"])
    item["Id"] = uuid.uuid4().hex + uuid.uuid4().hex
    item["Name"] = "/" + name
    item["Image"] = image["Id"]
    item["Config"]["Image"] = ref
    item["Config"]["Env"] = env
    labels = dict(image["Config"].get("Labels") or {})
    labels.update(extra_labels)
    if project:
        labels.update({"com.docker.compose.project": project, "com.docker.compose.service": "dashboard"})
    item["Config"]["Labels"] = labels
    item["State"] = {"Running": running, "Health": {"Status": "healthy" if running else "starting"}, "StartedAt": uuid.uuid4().hex}
    item["_identity"] = copy.deepcopy(image["_identity"])
    return item

if args[:2] == ["inspect", "--type"]:
    name = find(args[3])
    if name is None:
        fail("Error: No such container: " + args[3])
    out([C[name]])
if args[:2] == ["image", "inspect"]:
    image = state["images"].get(args[2])
    if image is None:
        fail("Error: No such image: " + args[2])
    out([image])
if args[0] == "rm":
    name = find(args[-1])
    if name is None:
        fail("no such container")
    del C[name]
    save()
    sys.exit(0)
if args[0] == "exec":
    if state.get("exec_fail"):
        fail("getent failed", 2)
    sys.stdout.write("172.20.0.5      telemetry-service\n")
    sys.exit(0)
if args[0] == "run":
    name = args[args.index("--name") + 1]
    env = open(args[args.index("--env-file") + 1], encoding="utf-8").read().splitlines()
    C[name] = make(name, args[-1], env, {"nexolab.wp2c.stage2": "preview"}, True)
    save()
    out(C[name]["Id"])
if args[0] == "compose":
    project = args[args.index("--project-name") + 1]
    if "config" in args:
        sys.exit(0)
    ref, env, labels = parse(args[args.index("--file") + 1])
    if "create" in args:
        name = project + "-dashboard-1"
        item = make(name, ref, env, labels, False, project)
        if state.get("drop_init"):
            item["HostConfig"]["Init"] = False
        C[name] = item
        save()
        sys.exit(0)
    if "up" in args:
        name = project + "-dashboard-1"
        if ref in state.get("compose_fail", []):
            fail("compose failed", 1)
        item = make(name, ref, env, labels, True, project)
        effect = state.get("on_up", {}).get(ref, {})
        if "identity" in effect:
            item["_identity"] = effect["identity"]
        if "bump" in effect:
            C[effect["bump"]]["State"]["StartedAt"] = "restarted"
        C[name] = item
        save()
        sys.exit(0)
fail("fake docker: unsupported " + " ".join(args), 99)
'''


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def identity(source: str, build: str) -> dict:
    return {"schema_version": "nexolab-runtime-identity-v1", "service": "dashboard", "source_commit": source,
            "build_id": build, "deployed_at": None, "identity_source": "offline_image_manifest"}


class Handler(http.server.BaseHTTPRequestHandler):
    role = ""
    state_path = ""

    def log_message(self, *args) -> None:  # noqa: D401 - quiet test output
        return

    def do_GET(self) -> None:  # noqa: N802
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        containers = state["containers"]
        status, body = 200, b"ok"
        if self.role == "api":
            status = 200 if self.path == "/health/ready" else 404
        else:
            if self.role == "gateway" and self.path == "/__nexolab_lan_gateway/health":
                pass
            else:
                name = PREVIEW if self.role == "preview" else DASH
                item = containers.get(name)
                if not item or not item["State"]["Running"]:
                    status, body = 502, b"down"
                elif self.path == "/api/runtime-identity":
                    body = json.dumps(item["_identity"]).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Site:
    """Fake docker + HTTP endpoints of the production host."""

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
        for role in ("dashboard", "preview", "gateway", "api"):
            port = free_port()
            handler = type(f"H_{role}", (Handler,), {"role": role, "state_path": str(self.state_path)})
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers.append(server)
            self.ports[role] = port
        dashboard = {
            "Id": "d" * 64, "Name": "/" + DASH, "Image": OLD_ID, "RestartCount": 0, "Mounts": [],
            "Config": {"Image": OLD_TAG, "Env": IMAGE_ENV + ["NEXT_PUBLIC_NEXOLAB_DATA_MODE=live", "PRICE=$5"],
                       "Labels": {"com.docker.compose.project": "nexolab-central", "com.docker.compose.service": "dashboard",
                                  "org.opencontainers.image.revision": OLD_SRC, "release_work_package": "1643"},
                       "Healthcheck": HEALTH, "User": "node", "Cmd": ["npm", "run", "start"], "WorkingDir": "/app",
                       "ExposedPorts": {"3000/tcp": {}}},
            "HostConfig": {"PortBindings": {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.ports["dashboard"])}]},
                           "NetworkMode": "nexolab-central", "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
                           "Init": True, "LogConfig": {"Type": "json-file", "Config": {}}, "ShmSize": 67108864,
                           "Binds": None, "Privileged": False},
            "NetworkSettings": {"Networks": {"nexolab-central": {"Aliases": [DASH, "dashboard"], "IPAMConfig": None}}},
            "State": {"Running": True, "Health": {"Status": "healthy"}, "StartedAt": "t0"},
            "_identity": identity(OLD_SRC, OLD_BUILD),
        }
        containers = {DASH: dashboard}
        for index, name in enumerate(BACKENDS):
            item = {"Id": f"{index}" * 64, "Name": "/" + name, "Image": "sha256:" + f"{index}" * 64, "RestartCount": 0,
                    "State": {"Running": True, "Health": {"Status": "healthy"}, "StartedAt": "t0"},
                    "NetworkSettings": {"Networks": {"nexolab-central": {}}}, "HostConfig": {"PortBindings": {}}}
            if "telemetry" in name:
                item["HostConfig"]["PortBindings"] = {"8082/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.ports["api"])}]}
            containers[name] = item

        def image(image_id: str, tag: str, src: str, build: str) -> dict:
            return {"Id": image_id, "Architecture": "arm64", "RepoTags": [tag], "RootFS": {"Layers": []},
                    "Config": {"Env": IMAGE_ENV, "User": "node", "Cmd": ["npm", "run", "start"], "WorkingDir": "/app",
                               "ExposedPorts": {"3000/tcp": {}}, "Healthcheck": HEALTH,
                               "Labels": {"org.opencontainers.image.revision": src}},
                    "_identity": identity(src, build)}

        old, new = image(OLD_ID, OLD_TAG, OLD_SRC, OLD_BUILD), image(NEW_ID, NEW_TAG, NEW_SRC, NEW_BUILD)
        self.state = {"containers": containers, "template": copy.deepcopy(dashboard),
                      "images": {OLD_TAG: old, OLD_ID: old, NEW_TAG: new, NEW_ID: new}}
        self.save()
        self.ws.mkdir(mode=0o700)
        (self.ws / "stage.json").write_text(json.dumps({"source": NEW_SRC, "build_id": NEW_BUILD, "node_version": "24"}))
        (self.ws / "build.json").write_text(json.dumps({"tag": NEW_TAG, "image_id": NEW_ID, "source": NEW_SRC, "build_id": NEW_BUILD}))
        self.log_path.write_text("")

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

    def close(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def argv(self, mode: str, *extra: str) -> list[str]:
        return [mode, "--workspace", str(self.ws), "--rollback-source", OLD_SRC, "--rollback-build", OLD_BUILD,
                "--expect-node", NODE, "--lock-path", str(self.tmp / "launch.lock"), "--reserve-gib", "0",
                "--gateway-url", f"http://127.0.0.1:{self.ports['gateway']}", "--preview-port", str(self.ports["preview"]),
                "--wait-seconds", "2", *extra]

    def main(self, mode: str, *extra: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "FAKE_DOCKER_STATE": str(self.state_path),
               "FAKE_DOCKER_LOG": str(self.log_path)}
        with mock.patch.dict(os.environ, env), mock.patch.object(S2, "POLL_SECONDS", 0.05), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S2.main(self.argv(mode, *extra))
        return rc, out.getvalue() + err.getvalue()


class SiteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.site = Site(Path(self._tmp.name))

    def tearDown(self) -> None:
        self.site.close()
        self._tmp.cleanup()

    def preview(self) -> None:
        rc, output = self.site.main("preview")
        self.assertEqual(rc, 0, output)
        self.assertIn("PREVIEW_GREEN", output)
        self.site.log_path.write_text("")


FORBIDDEN_TOKENS = {"--remove-orphans", "-v", "--volumes", "down", "prune", "volume", "network", "rmi", "kill", "stop",
                    "restart", "--rmi", "system"}


class PreviewTests(SiteTestCase):
    def test_preview_proves_identity_dns_fidelity_and_removes_preview(self) -> None:
        rc, output = self.site.main("preview")
        self.assertEqual(rc, 0, output)
        for marker in ("COMPOSE_FIDELITY_PROVEN rollback", "COMPOSE_FIDELITY_PROVEN candidate",
                       "PREVIEW_IDENTITY_VERIFIED", "PREVIEW_DOCKER_DNS_AND_SERVER_API_VERIFIED", "PREVIEW_GREEN"):
            self.assertIn(marker, output)
        state = self.site.load()
        self.assertEqual(sorted(state["containers"]), sorted([DASH, *BACKENDS]))  # preview + scratch removed
        self.assertEqual(state["containers"][DASH]["Id"], "d" * 64)  # production untouched
        calls = self.site.calls()
        self.assertTrue(any(c[:2] == ["exec", PREVIEW] and "getent" in c for c in calls))
        self.assertTrue(any(c[:2] == ["exec", PREVIEW] and "node" in c and "http://telemetry-service:8082/health/ready" in c
                            for c in calls))
        run = next(c for c in calls if c[0] == "run")
        self.assertIn(f"127.0.0.1:{self.site.ports['preview']}:3000/tcp", run)
        self.assertIn("nexolab-central", run)
        self.assertFalse((self.site.ws / "preview.env").exists())
        mode = stat.S_IMODE((self.site.ws / "compose" / "candidate.compose.yaml").stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertIn('"image": "nexolab/dashboard:issue-1643-7db6e1a8-arm64"', output)  # printed for review

    def test_dns_failure_stops_and_removes_preview(self) -> None:
        self.site.update(exec_fail=True)
        rc, output = self.site.main("preview")
        self.assertEqual(rc, 2)
        self.assertIn("DOCKER_DNS_FAILED", output)
        self.assertNotIn(PREVIEW, self.site.load()["containers"])
        self.assertFalse((self.site.ws / "preview.json").exists())

    def test_fidelity_mismatch_stops_before_any_production_change(self) -> None:
        self.site.update(drop_init=True)
        rc, output = self.site.main("preview")
        self.assertEqual(rc, 2)
        self.assertIn("COMPOSE_FIDELITY_FAILED rollback", output)
        self.assertIn("HostConfig.Init", output)
        self.assertFalse(any(c[0] == "compose" and "up" in c for c in self.site.calls()))

    def test_current_identity_must_equal_rollback_identity(self) -> None:
        rc, output = self.site.main("preview", "--rollback-build", "SomethingElse")
        self.assertEqual(rc, 2)
        self.assertIn("IDENTITY_MISMATCH", output)


class ComposeGenerationTests(unittest.TestCase):
    def args(self):
        return S2.parser().parse_args(["preview"])

    def test_candidate_differs_only_in_image_and_server_api_env(self) -> None:
        site_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(site_tmp.cleanup)
        site = Site(Path(site_tmp.name))
        self.addCleanup(site.close)
        container = site.state["containers"][DASH]
        image = site.state["images"][OLD_TAG]
        args = self.args()
        rollback = S2.service_model(container, image, args)
        candidate = dict(rollback, image=NEW_TAG, environment=S2.candidate_env(rollback["environment"], args.server_api_base_url))
        rb = S2.to_yaml(S2.compose_document(rollback, args)).splitlines()
        cd = S2.to_yaml(S2.compose_document(candidate, args)).splitlines()
        removed = [line for line in rb if line not in cd]
        added = [line for line in cd if line not in rb]
        self.assertEqual([line.strip() for line in removed], [f'"image": "{OLD_TAG}"'])
        self.assertEqual(sorted(line.strip() for line in added),
                         sorted([f'"image": "{NEW_TAG}"', '- "NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082"']))
        text = "\n".join(rb)
        self.assertIn('"PRICE=$$5"', text)  # Compose interpolation escaped
        self.assertIn('"external": true', text)
        self.assertIn('"init": true', text)
        self.assertIn('"restart": "unless-stopped"', text)
        self.assertIn('"release_work_package": "1643"', text)
        self.assertNotIn("com.docker.compose", text)
        self.assertNotIn("org.opencontainers.image.revision", text)  # image label, not a service label

    def test_unsupported_settings_fail_closed(self) -> None:
        site_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(site_tmp.cleanup)
        site = Site(Path(site_tmp.name))
        self.addCleanup(site.close)
        for key, value in (("Binds", ["/data:/data"]), ("Privileged", True), ("NetworkMode", "host")):
            container = copy.deepcopy(site.state["containers"][DASH])
            container["HostConfig"][key] = value
            with self.assertRaises(S2.Stop):
                S2.service_model(container, site.state["images"][OLD_TAG], self.args())

    def test_existing_different_server_api_env_fails_closed(self) -> None:
        with self.assertRaises(S2.Stop):
            S2.candidate_env(["NEXOLAB_SERVER_API_BASE_URL=http://10.0.0.1:8082"], "http://telemetry-service:8082")


class CheckTests(SiteTestCase):
    def test_check_makes_no_state_changing_docker_calls(self) -> None:
        self.preview()
        rc, output = self.site.main("check")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE2_CHECK_PASS NO_WRITES", output)
        calls = self.site.calls()
        self.assertTrue(calls)
        for call in calls:
            readonly = (call[:2] == ["inspect", "--type"] or call[:2] == ["image", "inspect"]
                        or (call[0] == "compose" and call[-2:] == ["config", "--quiet"]))
            self.assertTrue(readonly, call)
        self.assertEqual(self.site.load()["containers"][DASH]["Id"], "d" * 64)

    def test_check_requires_preview(self) -> None:
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("PREVIEW_NOT_DONE", output)

    def test_check_detects_tampered_compose(self) -> None:
        self.preview()
        path = self.site.ws / "compose" / "candidate.compose.yaml"
        path.write_text(path.read_text() + "# tamper\n")
        rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("COMPOSE_FILE_CHANGED_SINCE_PREVIEW", output)

    def test_root_is_refused(self) -> None:
        with mock.patch.object(S2.os, "geteuid", return_value=0):
            rc, output = self.site.main("check")
        self.assertEqual(rc, 2)
        self.assertIn("RUN_AS_OPERATOR_NONROOT", output)
        self.assertEqual(self.site.calls(), [])

    def test_disk_reserve_is_enforced(self) -> None:
        self.preview()
        with mock.patch.object(S2, "free_bytes", return_value=GIB_MINUS_ONE):
            rc, output = self.site.main("check", "--reserve-gib", "1")
        self.assertEqual(rc, 2)
        self.assertIn("DISK_RESERVE_1GIB_PLUS_0GIB_FAILED", output)
        self.assertEqual(self.site.calls(), [])
        self.assertEqual(S2.parser().parse_args(["check"]).reserve_gib, 20)

    def test_wrong_node_is_refused(self) -> None:
        self.preview()
        rc, output = self.site.main("check", "--expect-node", "not-this-host")
        self.assertEqual(rc, 2)
        self.assertIn("WRONG_NODE", output)

    def test_held_lock_blocks(self) -> None:
        self.preview()
        lock = self.site.tmp / "launch.lock"
        fd = S2.hold_lock(lock)
        try:
            rc, output = self.site.main("check")
        finally:
            os.close(fd)
        self.assertEqual(rc, 2)
        self.assertIn("ACTIVE_DEPLOYMENT_LOCK", output)


class ExecuteTests(SiteTestCase):
    def reports(self) -> list[dict]:
        paths = sorted((self.site.ws / "reports").glob("*.json"))
        for path in paths:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        return [json.loads(p.read_text()) for p in paths]

    def compose_ups(self) -> list[str]:
        return [Path(c[c.index("--file") + 1]).name for c in self.site.calls() if c[0] == "compose" and "up" in c]

    def assert_safe_calls(self) -> None:
        for call in self.site.calls():
            self.assertFalse(FORBIDDEN_TOKENS & set(call), call)
            if call[0] == "compose" and "up" in call:
                self.assertEqual(call[call.index("--project-name") + 1], "nexolab-central")
                for flag in ("--no-deps", "--no-build", "--force-recreate", "--detach"):
                    self.assertIn(flag, call)
                self.assertEqual(call[call.index("--pull") + 1], "never")
                self.assertEqual(call[-1], "dashboard")

    def test_green_switch(self) -> None:
        self.preview()
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE2_FRONTEND_GREEN", output)
        dash = self.site.load()["containers"][DASH]
        self.assertEqual(dash["Image"], NEW_ID)
        self.assertIn("NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082", dash["Config"]["Env"])
        self.assertIn("PRICE=$5", dash["Config"]["Env"])
        self.assertEqual(self.compose_ups(), ["candidate.compose.yaml"])
        self.assertTrue(any(c[:2] == ["exec", DASH] for c in self.site.calls()))
        self.assertEqual([r["outcome"] for r in self.reports()], ["STAGE2_FRONTEND_GREEN"])
        self.assert_safe_calls()

        rc, output = self.site.main("rollback")
        self.assertEqual(rc, 0, output)
        self.assertIn("STAGE2_ROLLED_BACK_VERIFIED", output)
        dash = self.site.load()["containers"][DASH]
        self.assertEqual(dash["Image"], OLD_ID)
        self.assertEqual(sorted(dash["Config"]["Env"]), sorted(self.site.state["template"]["Config"]["Env"]))
        self.assert_safe_calls()

    def test_failed_identity_rolls_back_verified(self) -> None:
        self.preview()
        self.site.update(on_up={NEW_TAG: {"identity": identity(NEW_SRC, "WrongBuild")}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertIn("ACTIVATION_CHECK_FAILED", output)
        self.assertIn("STAGE2_ROLLED_BACK_VERIFIED", output)
        self.assertNotIn("STAGE2_FRONTEND_GREEN", output)
        self.assertEqual(self.compose_ups(), ["candidate.compose.yaml", "rollback.compose.yaml"])
        self.assertEqual(self.site.load()["containers"][DASH]["Image"], OLD_ID)
        report = self.reports()[-1]
        self.assertEqual(report["outcome"], "ROLLED_BACK_VERIFIED")
        self.assertIn("DASHBOARD_TARGET_NOT_VERIFIED", report["error"])
        self.assert_safe_calls()

    def test_partial_compose_failure_still_rolls_back(self) -> None:
        self.preview()
        self.site.update(compose_fail=[NEW_TAG])
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 3, output)
        self.assertIn("STAGE2_ROLLED_BACK_VERIFIED", output)

    def test_backend_change_triggers_rollback_and_hard_blocker(self) -> None:
        self.preview()
        self.site.update(on_up={NEW_TAG: {"bump": "nexolab-central-telemetry-service-1"}})
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 4, output)
        self.assertIn("BACKEND_CONTAINER_CHANGED", output)
        self.assertIn("HARD_BLOCKER_ROLLBACK_UNVERIFIED", output)
        self.assertNotIn("STAGE2_ROLLED_BACK_VERIFIED", output)
        self.assertEqual(self.compose_ups(), ["candidate.compose.yaml", "rollback.compose.yaml"])
        self.assertEqual(self.reports()[-1]["outcome"], "HARD_BLOCKER_ROLLBACK_UNVERIFIED")

    def test_dead_gateway_blocks_before_switch(self) -> None:
        self.preview()
        gateway = self.site.servers[2]
        gateway.shutdown()
        gateway.server_close()
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2, output)  # preflight already requires the gateway: nothing switched
        self.assertIn("HTTP_UNAVAILABLE", output)
        self.assertEqual(self.compose_ups(), [])

    def test_preflight_refuses_changed_dashboard(self) -> None:
        self.preview()
        state = self.site.load()
        state["containers"][DASH]["Id"] = "e" * 64
        self.site.state_path.write_text(json.dumps(state))
        rc, output = self.site.main("execute")
        self.assertEqual(rc, 2)
        self.assertIn("DASHBOARD_CHANGED_SINCE_PREVIEW", output)
        self.assertEqual(self.compose_ups(), [])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_artifact(root: Path, *, contract: dict | None = None, public: str | None = None, tamper_file: bool = False,
                  extra_entries: dict | None = None, tar_tamper: bool = False, symlink_entry: bool = False) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    runtime = {".next/BUILD_ID": NEW_BUILD.encode() + b"\n", "node_modules/next/index.js": b"module.exports=1\n",
               "public/logo.txt": b"logo\n"}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in runtime.items():
            info = tarfile.TarInfo(name)
            payload = data + (b"x" if tar_tamper and name.startswith("public") else b"")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    values = {"runtime_mode": "live", "api_base_url": "same-origin", "websocket_url": "same-origin", "auth_provider": "local",
              "organization_id": "00000000-0000-0000-0000-000000000001", "external_https_stage": "false"}
    values.update(contract or {})
    files = {
        "frontend-runtime.tar.gz": buf.getvalue(),
        "package.json": b"{}\n",
        "package-lock.json": b"{}\n",
        "frontend-source-sha.txt": f"{NEW_SRC}\n".encode(),
        "frontend-package-sha256.txt": b"",
        "frontend-runtime-contract.txt": "".join(f"{k}={v}\n" for k, v in values.items()).encode(),
        "frontend-platform.txt": b"linux/arm64\n",
        "frontend-node-version.txt": b"24.11.1\n",
        "frontend-build-id.txt": f"{NEW_BUILD}\n".encode(),
        "frontend-runtime-files-sha256.txt": "".join(f"{sha(d)}  {n}\n" for n, d in runtime.items()).encode(),
        "frontend-public-contract.txt": (public if public is not None else
                                         f"status=PASS\nbuild_id={NEW_BUILD}\nNEXT_PUBLIC_NEXOLAB_API_BASE_URL=same-origin\n"
                                         "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=same-origin\n"
                                         "same_origin_browser_bundle=no-absolute-host-origin\n").encode(),
        "frontend-native-files.txt": b"",
    }
    files["frontend-artifact-sha256.txt"] = "".join(f"{sha(d)}  {n}\n" for n, d in files.items()).encode()
    if tamper_file:
        files["package.json"] = b'{"tampered":true}\n'
    path = root / "artifact.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in {**files, **(extra_entries or {})}.items():
            archive.writestr(name, data)
        if symlink_entry:
            info = zipfile.ZipInfo("frontend-link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return path, sha(path.read_bytes())


class StageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def stage(self, zip_path: Path, digest: str) -> tuple[int, str]:
        out = io.StringIO()
        # Working-space headroom is a host property; the temporary test filesystem may be small.
        with mock.patch.object(S2, "free_bytes", return_value=1 << 50), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = S2.main(["stage", "--workspace", str(self.tmp / "ws"), "--artifact-zip", str(zip_path),
                          "--expect-zip-sha256", digest, "--expect-node", NODE, "--reserve-gib", "0"])
        return rc, out.getvalue()

    def assert_stop(self, reason: str, **kwargs) -> None:
        zip_path, digest = make_artifact(self.tmp / "a", **kwargs)
        rc, output = self.stage(zip_path, digest)
        self.assertEqual(rc, 2, output)
        self.assertIn(reason, output)
        self.assertFalse((self.tmp / "ws" / "artifact").exists())
        self.assertFalse((self.tmp / "ws" / "stage.json").exists())

    def test_valid_artifact_is_staged(self) -> None:
        zip_path, digest = make_artifact(self.tmp / "a")
        rc, output = self.stage(zip_path, digest)
        self.assertEqual(rc, 0, output)
        self.assertIn(f"STAGE_VERIFIED source={NEW_SRC} build={NEW_BUILD} runtime_files=3", output)
        facts = json.loads((self.tmp / "ws" / "stage.json").read_text())
        self.assertEqual((facts["source"], facts["build_id"], facts["zip_sha256"]), (NEW_SRC, NEW_BUILD, digest))
        self.assertEqual(stat.S_IMODE((self.tmp / "ws").stat().st_mode), 0o700)
        rc, output = self.stage(zip_path, digest)
        self.assertEqual(rc, 2)
        self.assertIn("ARTIFACT_ALREADY_STAGED", output)

    def test_zip_digest_mismatch(self) -> None:
        zip_path, _ = make_artifact(self.tmp / "a")
        rc, output = self.stage(zip_path, "0" * 64)
        self.assertEqual(rc, 2)
        self.assertIn("ARTIFACT_ZIP_SHA256_MISMATCH", output)

    def test_tampered_file_inside_zip(self) -> None:
        self.assert_stop("ARTIFACT_FILE_HASH_MISMATCH package.json", tamper_file=True)

    def test_tampered_runtime_file(self) -> None:
        self.assert_stop("RUNTIME_FILE_HASH_MISMATCH public/logo.txt", tar_tamper=True)

    def test_traversal_entry(self) -> None:
        self.assert_stop("UNSAFE_ZIP_ENTRY ../evil", extra_entries={"../evil": b"x"})

    def test_nested_entry(self) -> None:
        self.assert_stop("UNSAFE_ZIP_ENTRY sub/evil", extra_entries={"sub/evil": b"x"})

    def test_symlink_entry(self) -> None:
        self.assert_stop("UNSAFE_ZIP_ENTRY_TYPE frontend-link", symlink_entry=True)

    def test_unexpected_entry(self) -> None:
        self.assert_stop("UNEXPECTED_ZIP_ENTRY extra.txt", extra_entries={"extra.txt": b"x"})

    def test_absolute_api_contract_rejected(self) -> None:
        self.assert_stop("RUNTIME_CONTRACT_NOT_SAME_ORIGIN", contract={"api_base_url": "http://172.18.48.66:8082"})

    def test_external_https_stage_rejected(self) -> None:
        self.assert_stop("RUNTIME_CONTRACT_EXTERNAL_HTTPS_STAGE", contract={"external_https_stage": "true"})

    def test_non_local_auth_rejected(self) -> None:
        self.assert_stop("RUNTIME_CONTRACT_AUTH_NOT_LOCAL", contract={"auth_provider": "disabled"})

    def test_public_contract_without_same_origin_proof(self) -> None:
        self.assert_stop("PUBLIC_CONTRACT_NO_SAME_ORIGIN_PROOF", public=f"status=PASS\nbuild_id={NEW_BUILD}\n")

    def test_public_contract_fail(self) -> None:
        self.assert_stop("PUBLIC_CONTRACT_NOT_PASS", public="status=FAIL\ncompiled_absolute_origin=http://10.0.0.1\n")

    def test_unsafe_tar_member(self) -> None:
        member = tarfile.TarInfo("../escape")
        with self.assertRaises(S2.Stop):
            S2.check_tar_member(member)
        link = tarfile.TarInfo("node_modules/.bin/x")
        link.type, link.linkname = tarfile.SYMTYPE, "../../../../etc/passwd"
        with self.assertRaises(S2.Stop):
            S2.check_tar_member(link)
        ok = tarfile.TarInfo("node_modules/.bin/next")
        ok.type, ok.linkname = tarfile.SYMTYPE, "../next/dist/bin/next"
        S2.check_tar_member(ok)


class BuildHelperTests(unittest.TestCase):
    def test_dockerfile_mirrors_current_image_on_proven_base(self) -> None:
        old = {"Config": {"Env": IMAGE_ENV, "WorkingDir": "/app", "User": "node", "ExposedPorts": {"3000/tcp": {}},
                          "Healthcheck": HEALTH, "Cmd": ["npm", "run", "start"],
                          "Labels": {"org.opencontainers.image.revision": OLD_SRC, "org.opencontainers.image.version": OLD_SRC}}}
        text = S2.dockerfile_for(old, "node:22.23.1-bookworm-slim", "1000:1000", NEW_SRC)
        lines = text.splitlines()
        self.assertEqual(lines[0], "FROM node:22.23.1-bookworm-slim")
        with self.assertRaises(S2.Stop):  # BuildKit resolves a bare ID as docker.io/library/sha256 (#1782)
            S2.dockerfile_for(old, "sha256:" + "c" * 64, "1000:1000", NEW_SRC)
        self.assertFalse([line for line in lines if line.startswith("RUN")])
        self.assertIn(f'LABEL "org.opencontainers.image.revision"="{NEW_SRC}"', lines)
        self.assertIn(f'LABEL "org.opencontainers.image.version"="{NEW_SRC}"', lines)
        self.assertIn("COPY --chown=1000:1000 app/ /app/", lines)
        self.assertIn("USER node", lines)

    def test_base_reference_is_a_node_tag_that_resolves_to_the_proven_id(self) -> None:
        from unittest import mock
        base_id = "sha256:" + "b" * 64
        base = {"Id": base_id, "RepoTags": ["node:22.23.1-bookworm-slim", "other:tag"]}
        with mock.patch.object(S2, "image_inspect", return_value={"Id": base_id}):
            self.assertEqual(S2.base_reference(base), "node:22.23.1-bookworm-slim")
        with mock.patch.object(S2, "image_inspect", return_value={"Id": "sha256:" + "d" * 64}):
            with self.assertRaises(S2.Stop):  # the tag was moved to another image
                S2.base_reference(base)
        with self.assertRaises(S2.Stop):  # no node tag at all
            S2.base_reference({"Id": base_id, "RepoTags": ["busybox:1.37"]})

    def test_identity_manifest_keeps_template_shape(self) -> None:
        manifest = json.loads(S2.identity_manifest(identity(OLD_SRC, OLD_BUILD), NEW_SRC, NEW_BUILD))
        self.assertEqual(manifest, identity(NEW_SRC, NEW_BUILD))
        with self.assertRaises(S2.Stop):
            S2.identity_manifest({**identity(OLD_SRC, OLD_BUILD), "extra": 1}, NEW_SRC, NEW_BUILD)


class StaticSafetyTests(unittest.TestCase):
    def test_tool_source_has_no_forbidden_docker_operations(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]  # skip the module docstring that names what is forbidden
        for token in ('"--remove-orphans"', '"down"', '"prune"', '"volume"', '"-v"', '"--volumes"', "shell=True", "os.system"):
            self.assertNotIn(token, code)
        self.assertIn('"--pull", "never"', code)


if __name__ == "__main__":
    unittest.main()
