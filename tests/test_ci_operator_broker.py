"""Operator Broker contract (#1758): real Unix socket, kernel peer credentials, fixed ops.

The broker runs unprivileged here in its test mode (refused as root), with test-only
operations loaded from docs/operations/operator-broker/broker-test-ops.py.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROKER_DIR = ROOT / "docs" / "operations" / "operator-broker"
BROKER = BROKER_DIR / "nexolab-operator-broker.py"
CLIENT = BROKER_DIR / "nexolab-operator.py"
TEST_OPS = BROKER_DIR / "broker-test-ops.py"
INSTALLER = BROKER_DIR / "install-operator-broker.sh"
SERVICE = BROKER_DIR / "nexolab-operator-broker.service"
SOCKET_UNIT = BROKER_DIR / "nexolab-operator-broker.socket"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.dont_write_bytecode = True
broker_module = load(BROKER, "nexolab_operator_broker")
client_module = load(CLIENT, "nexolab_operator_client")


class RunningBroker:
    def __init__(self, allowed_uid: int | None = None) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="nxbroker-"))
        os.chmod(self.tmp, 0o700)
        self.install = self.tmp / "install"
        self.install.mkdir(mode=0o755)
        shutil.copy2(BROKER, self.install / BROKER.name)
        os.chmod(self.install / BROKER.name, 0o755)
        self.state = self.tmp / "state"
        (self.state / "approvals").mkdir(parents=True, mode=0o700)
        self.socket = str(self.tmp / "broker.sock")
        uid = os.getuid() if allowed_uid is None else allowed_uid
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-B", str(self.install / BROKER.name), "serve", "--allowed-uids", str(uid),
             "--install-dir", str(self.install), "--state-root", str(self.state), "--test-socket", self.socket,
             "--test-ops", str(TEST_OPS)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 15
        while not os.path.exists(self.socket):
            if self.proc.poll() is not None or time.time() > deadline:
                raise AssertionError(f"broker did not start: {self.proc.stdout.read()}")
            time.sleep(0.05)

    def raw(self, request: dict | bytes) -> dict:
        payload = request if isinstance(request, bytes) else json.dumps(request).encode() + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(30)
            sock.connect(self.socket)
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        return json.loads(data)

    def call(self, op: str, args: dict | None = None, **extra) -> dict:
        return client_module.call(op, args or {}, path=self.socket, timeout=30, **extra)

    def approve(self, op: str, args: dict, *, ttl: float = 600, mode: int = 0o600) -> str:
        approval_id = uuid.uuid4().hex
        path = self.state / "approvals" / f"{approval_id}.json"
        path.write_text(json.dumps({"approval_id": approval_id, "op": op, "args": args,
                                    "expires_at": time.time() + ttl, "approved_by": "owner"}))
        os.chmod(path, mode)
        return approval_id

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.proc.stdout is not None:
            self.proc.stdout.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def request(op: str, args: dict | None = None, **fields) -> dict:
    body = {"v": 1, "op": op, "args": args or {}, "request_id": str(uuid.uuid4()), "ts": time.time()}
    body.update(fields)
    return body


class BrokerSocketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.broker = RunningBroker()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.broker.close()

    def test_authorized_peer_runs_fixed_operation_with_receipt(self) -> None:
        response = self.broker.call("test.echo", {"word": "hello"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["steps"][0]["output"].strip(), "hello")
        self.assertRegex(response["receipt"]["hash"], r"^[0-9a-f]{64}$")

    def test_list_describes_every_operation(self) -> None:
        listed = {o["op"]: o for o in self.broker.call("broker.list")["result"]["operations"]}
        self.assertIn("wifi.diagnose", listed)
        self.assertEqual(listed["service.recover"]["kind"], "recover")
        self.assertTrue(all(o["kind"] in ("read", "recover", "approved") for o in listed.values()))

    def test_unknown_operation_and_shell_like_names_are_rejected(self) -> None:
        for op in ("system.exec", "shell.run", "docker.exec"):
            self.assertEqual(self.broker.call(op)["error"], "unknown_operation")
        for op in ("../etc", "test.echo;id", "TEST.ECHO", "a", "x.y.z.w"):
            self.assertEqual(self.broker.call(op)["error"], "invalid_request")

    def test_extra_missing_and_mistyped_arguments_are_rejected(self) -> None:
        self.assertEqual(self.broker.call("test.echo", {"word": "a", "flag": "x"})["error"], "unexpected_argument")
        self.assertEqual(self.broker.call("test.echo", {})["error"], "missing_argument")
        self.assertEqual(self.broker.call("test.sleep", {"seconds": True})["error"], "invalid_argument")
        self.assertEqual(self.broker.call("test.sleep", {"seconds": "1"})["error"], "invalid_argument")
        self.assertEqual(self.broker.call("test.sleep", {"seconds": 99})["error"], "invalid_argument")

    def test_injection_and_traversal_values_never_reach_a_command(self) -> None:
        for word in ("../../etc/passwd", "a;id", "$(id)", "-rf", "a b", "`id`", "a\nb", "/etc/shadow", ""):
            self.assertEqual(self.broker.call("test.echo", {"word": word})["error"], "invalid_argument", word)
        for name in ("../x", "-v", "a;id", "$(id)", "a/b", "x" * 80):
            self.assertEqual(self.broker.call("docker.logs", {"name": name})["error"], "invalid_argument", name)
        self.assertEqual(self.broker.call("logs.unit", {"unit": "nexolab-gitlab-sync.service"})["error"],
                         "invalid_argument")
        self.assertEqual(self.broker.call("logs.unit", {"unit": "../../x.service"})["error"], "invalid_argument")

    def test_replay_and_stale_requests_are_rejected(self) -> None:
        body = request("test.echo", {"word": "once"})
        self.assertTrue(self.broker.raw(body)["ok"])
        self.assertEqual(self.broker.raw(body)["error"], "replay")
        self.assertEqual(self.broker.raw(request("test.echo", {"word": "old"}, ts=time.time() - 600))["error"],
                         "stale_request")
        self.assertEqual(self.broker.raw(request("test.echo", {"word": "x"}, request_id="1"))["error"],
                         "invalid_request")

    def test_malformed_and_oversized_requests(self) -> None:
        self.assertEqual(self.broker.raw(b"not json\n")["error"], "invalid_request")
        self.assertEqual(self.broker.raw(b"[1,2]\n")["error"], "invalid_request")
        self.assertEqual(self.broker.raw(request("test.echo", {"word": "x"}, v=2))["error"], "unsupported_protocol")
        self.assertEqual(self.broker.raw(request("test.echo", {"word": "x"}, cmd="id"))["error"], "invalid_request")
        big = json.dumps(request("test.echo", {"word": "x" * 5000})).encode() + b"\n"
        self.assertEqual(self.broker.raw(big)["error"], "request_too_large")

    def test_sensitive_output_is_redacted(self) -> None:
        response = self.broker.call("test.secret")
        text = json.dumps(response)
        for leaked in ("hunter2", "supersecretpsk", "abcdefghijklmnop123", "pg-pass-123", "MIIBVgIBADANBgkqh",
                       "c2lnbmF0dXJlMTIzNDU", "kAbCdEf123"):
            self.assertNotIn(leaked, text)
        self.assertIn("harmless line sha256=4f2a", text)

    def test_timeout_and_output_cap(self) -> None:
        slow = self.broker.call("test.sleep", {"seconds": 5})
        self.assertTrue(slow["result"]["steps"][0]["timed_out"])
        big = self.broker.call("test.big")["result"]["steps"][0]
        self.assertTrue(big["truncated"])
        self.assertLessEqual(len(big["output"]), broker_module.MAX_OUTPUT_BYTES)

    def test_concurrent_mutation_is_rejected(self) -> None:
        results: list[dict] = []
        first = threading.Thread(target=lambda: results.append(self.broker.call("test.mutate", {"hold": 2})))
        first.start()
        time.sleep(0.5)
        second = self.broker.call("test.mutate", {"hold": 0})
        first.join()
        self.assertEqual(second["error"], "busy")
        self.assertTrue(results[0]["ok"])

    def test_approval_is_required_exact_and_single_use(self) -> None:
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"})["error"], "approval_required")
        wrong = self.broker.approve("test.approved", {"target": "other"})
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"}, approval_id=wrong)["error"],
                         "approval_mismatch")
        expired = self.broker.approve("test.approved", {"target": "wifi"}, ttl=-1)
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"}, approval_id=expired)["error"],
                         "approval_expired")
        loose = self.broker.approve("test.approved", {"target": "wifi"}, mode=0o644)
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"}, approval_id=loose)["error"],
                         "approval_invalid")
        writable = self.broker.approve("test.approved", {"target": "wifi"}, mode=0o622)
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"}, approval_id=writable)["error"],
                         "approval_invalid")
        good = self.broker.approve("test.approved", {"target": "wifi"})
        first = self.broker.call("test.approved", {"target": "wifi"}, approval_id=good)
        self.assertTrue(first["ok"], first)
        self.assertEqual(self.broker.call("test.approved", {"target": "wifi"}, approval_id=good)["error"],
                         "approval_invalid")

    def test_symlinked_approval_is_rejected(self) -> None:
        target = self.broker.approve("test.approved", {"target": "link"})
        link_id = uuid.uuid4().hex
        os.symlink(self.broker.state / "approvals" / f"{target}.json",
                   self.broker.state / "approvals" / f"{link_id}.json")
        self.assertEqual(self.broker.call("test.approved", {"target": "link"}, approval_id=link_id)["error"],
                         "approval_invalid")

    def test_audit_chain_records_accepted_and_rejected_requests(self) -> None:
        self.broker.call("test.echo", {"word": "audit"})
        self.broker.call("nope.nope")
        log = self.broker.state / "audit.jsonl"
        ok, count, _last = broker_module.verify_audit(log)
        self.assertTrue(ok)
        entries = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertGreaterEqual(count, 2)
        self.assertEqual({e["status"] for e in entries} >= {"ok", "rejected"}, True)
        self.assertTrue(all(e["peer_uid"] == os.getuid() for e in entries))
        tampered = log.read_text().replace('"word":"audit"', '"word":"other"')
        forged = self.broker.state / "forged.jsonl"
        forged.write_text(tampered)
        self.assertFalse(broker_module.verify_audit(forged)[0])


class BrokerTrustTests(unittest.TestCase):
    def test_unauthorized_peer_uid_is_rejected_and_audited(self) -> None:
        broker = RunningBroker(allowed_uid=os.getuid() + 4242)
        try:
            response = broker.call("test.echo", {"word": "x"})
            self.assertEqual(response["error"], "unauthorized_peer")
            entry = json.loads((broker.state / "audit.jsonl").read_text().splitlines()[-1])
            self.assertEqual((entry["status"], entry["error"]), ("rejected", "unauthorized_peer"))
        finally:
            broker.close()

    def _refuses(self, mutate) -> str:
        tmp = Path(tempfile.mkdtemp(prefix="nxbroker-trust-"))
        try:
            os.chmod(tmp, 0o700)
            install = tmp / "install"
            install.mkdir(mode=0o755)
            target = install / BROKER.name
            shutil.copy2(BROKER, target)
            os.chmod(target, 0o755)
            mutate(install, target)
            out = subprocess.run(
                [sys.executable, "-I", "-B", str(target), "serve", "--allowed-uids", str(os.getuid()),
                 "--install-dir", str(install), "--state-root", str(tmp), "--test-socket", str(tmp / "s.sock"),
                 "--test-ops", str(TEST_OPS)], capture_output=True, text=True, timeout=20)
            self.assertEqual(out.returncode, 78, out.stderr)
            return out.stderr
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_refuses_mutable_broker_file(self) -> None:
        self.assertIn("untrusted_handler", self._refuses(lambda _i, t: os.chmod(t, 0o777)))

    def test_refuses_mutable_install_dir_and_handlers(self) -> None:
        self.assertIn("untrusted_handler", self._refuses(lambda i, _t: os.chmod(i, 0o777)))

        def writable_handler(install: Path, _t: Path) -> None:
            (install / "handlers").mkdir(mode=0o755)
            handler = install / "handlers" / "x.sh"
            handler.write_text("true\n")
            os.chmod(handler, 0o666)
        self.assertIn("untrusted_handler", self._refuses(writable_handler))

    def test_refuses_symlinked_handler(self) -> None:
        def symlinked(install: Path, _t: Path) -> None:
            os.symlink("/bin/true", install / "handler")
        self.assertIn("untrusted_handler", self._refuses(symlinked))

    def test_test_options_require_test_socket(self) -> None:
        out = subprocess.run([sys.executable, "-I", "-B", str(BROKER), "serve", "--allowed-uids", "1",
                              "--test-ops", str(TEST_OPS)], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(out.returncode, 0)

    def test_serve_without_systemd_socket_refuses(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="nxbroker-nosock-"))
        try:
            os.chmod(tmp, 0o700)
            target = tmp / BROKER.name
            shutil.copy2(BROKER, target)
            os.chmod(target, 0o755)
            env = {k: v for k, v in os.environ.items() if not k.startswith("LISTEN_")}
            env["NEXOLAB_OPERATOR_ALLOWED_UIDS"] = str(os.getuid())
            out = subprocess.run([sys.executable, "-I", "-B", str(target), "serve", "--install-dir", str(tmp)],
                                 capture_output=True, text=True, timeout=20, env=env)
            self.assertEqual(out.returncode, 78)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_approve_is_root_only(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("runs as root")
        out = subprocess.run([sys.executable, "-I", "-B", str(BROKER), "approve", "--op", "service.recover"],
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 77)


class FakeDocker:
    """Fake runner: a host with NEXOLAB and foreign workloads (#1769)."""

    PS_SCOPE = "\n".join([
        "nexolab-central-dashboard-1\tnexolab-central\tnexolab/dashboard:issue-1643-7db6e1a8-arm64",
        "nexolab-edge-device-agent-1\tnexolab-edge\tnexolab/device-agent:quick-agent-1490",
        "nexolab-standalone-x\t\tnexolab/tool:1",
        "sellora-backend-1\tsellora\tsellora/backend:latest",
        "nexolab-impostor-1\tsellora\tsellora/backend:latest",
    ])

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, _timeout):
        self.calls.append(argv)
        joined = " ".join(argv)
        if argv[:2] == ["docker", "ps"] and "com.docker.compose.project" in joined:
            out = self.PS_SCOPE
        elif argv[:2] == ["docker", "ps"] and "{{.Networks}}" in joined:
            out = "nexolab-central-dashboard-1\tnexolab-central\nsellora-backend-1\tsellora_default"
        elif argv[:2] == ["docker", "ps"]:
            out = ("nexolab-central-dashboard-1\timg\trunning\tUp\t\tnexolab-central\n"
                   "sellora-backend-1\tsellora/backend\trunning\tUp\t\tsellora_default")
        elif argv[:3] == ["docker", "network", "ls"]:
            out = "nexolab-central\tbridge\tlocal\tid1\nsellora_default\tbridge\tlocal\tid2\nbridge\tbridge\tlocal\tid3"
        elif argv[:3] == ["docker", "image", "ls"]:
            out = ("nexolab/dashboard:issue-1643-7db6e1a8-arm64\tsha256:a\t<none>\t1 day\t1GB\n"
                   "sellora/backend:latest\tsha256:b\t<none>\t1 day\t1GB\n"
                   "postgres:16\tsha256:c\t<none>\t1 day\t1GB")
        else:
            out = "ok"
        return broker_module.RunResult(0, out, False, False)


class BrokerNexolabScopeTests(unittest.TestCase):
    def fake(self):
        runner = FakeDocker()
        return type("B", (), {"runner": staticmethod(runner)})(), runner

    def test_only_nexolab_containers_are_visible(self) -> None:
        broker, _ = self.fake()
        self.assertEqual(broker_module.container_names(broker),
                         {"nexolab-central-dashboard-1", "nexolab-edge-device-agent-1", "nexolab-standalone-x"})
        out = broker_module.op_docker_containers(broker, {})["steps"][0]["output"]
        self.assertIn("nexolab-central-dashboard-1", out)
        self.assertNotIn("sellora", out)

    def test_foreign_container_metadata_and_logs_are_refused_before_any_call(self) -> None:
        for op in (broker_module.op_docker_logs, broker_module.op_docker_container):
            for name in ("sellora-backend-1", "nexolab-impostor-1", "does-not-exist"):
                broker, runner = self.fake()
                with self.assertRaises(broker_module.Rejected) as ctx:
                    op(broker, {"name": name, "lines": 10, "since_minutes": 5})
                self.assertEqual(ctx.exception.code, "unknown_container")
                self.assertFalse([c for c in runner.calls if c[:2] in (["docker", "logs"], ["docker", "inspect"])])

    def test_nexolab_container_logs_are_allowed(self) -> None:
        broker, runner = self.fake()
        broker_module.op_docker_logs(broker, {"name": "nexolab-central-dashboard-1", "lines": 10, "since_minutes": 5})
        self.assertIn(["docker", "logs", "--timestamps", "--tail", "10", "--since", "5m", "--",
                       "nexolab-central-dashboard-1"], runner.calls)

    def test_networks_and_images_are_scoped(self) -> None:
        broker, _ = self.fake()
        nets = broker_module.op_docker_networks(broker, {})["steps"]
        self.assertEqual(nets[0]["output"], "nexolab-central\tbridge\tlocal\tid1")
        self.assertNotIn("sellora", nets[1]["output"])
        images = broker_module.op_docker_images(broker, {})["steps"]
        self.assertIn("nexolab/dashboard", images[0]["output"])
        self.assertNotIn("sellora", images[0]["output"])
        self.assertNotIn("postgres:16", images[0]["output"])
        self.assertNotIn("sellora", images[1]["output"])


class InventorySanitizingTests(unittest.TestCase):
    REPORT = "\n".join([
        "NEXOLAB storage inventory, read-only",
        "===== Filesystems =====", "/dev/sda2 234G 199G 23G 90% /",
        "===== Commander workspaces =====", "5.5G /home/nexolab/commander-workspaces/unified-update-c296",
        "2.3G /home/nexolab/commander-workspaces/sellora-design",
        "===== Git state of operator checkouts (in-use and unpushed work is PROTECTED) =====",
        "/home/nexolab/commander-workspaces/sellora-design branch=secret-feature",
        "===== Directories in use by running processes (PROTECTED) =====", "123 /x node --token=abc",
        "===== PostgreSQL database and largest relations (read-only queries) =====", "telemetry_samples 22 GB",
        "===== Cleanup candidates (estimates only; nothing deleted) =====",
        "M5 CLEAN 883MiB regenerable caches in /home/nexolab/commander-workspaces/sellora-design:",
        "M4 PROTECTED sha256:aa (used by a container)",
    ])

    def test_only_allow_listed_sections_leave_and_foreign_workspaces_are_masked(self) -> None:
        out = broker_module.sanitize_inventory(self.REPORT)
        self.assertIn("/dev/sda2", out)
        self.assertIn("commander-workspaces/unified-update-c296", out)
        self.assertIn("M4 PROTECTED", out)
        for hidden in ("sellora", "secret-feature", "--token", "telemetry_samples", "Git state"):
            self.assertNotIn(hidden, out)
        self.assertIn("<non-nexolab-workspace>", out)

    def test_raw_report_is_root_only(self) -> None:
        source = BROKER.read_text()
        self.assertIn("os.chmod(report, 0o600)", source)
        self.assertNotIn("report_group", source)


class InstallerContractTests(unittest.TestCase):
    def test_owner_root_and_dev_boundaries(self) -> None:
        text = INSTALLER.read_text()
        self.assertIn('[[ "$owner" == "DENIED_FS EACCES" ]]', text)
        self.assertIn('[[ "$root" == "False unauthorized_peer"* ]]', text)
        self.assertIn('[[ "$dev" == "True None"* ]]', text)
        dev_call = text[text.index("dev) #"):text.index("esac", text.index("dev) #"))]
        for prop in ("NoNewPrivileges=yes", "PrivateDevices=yes", "ProtectSystem=strict", "-/run/docker.sock"):
            self.assertIn(prop, dev_call)
        self.assertNotIn("SocketMode=0666", SOCKET_UNIT.read_text())

    def test_staging_and_rollback_are_global_and_verified(self) -> None:
        text = INSTALLER.read_text()
        self.assertNotIn("local src=\"${1:?payload directory required}\" stage", text)
        self.assertIn("trap cleanup_stage EXIT", text)
        self.assertIn("ROLLBACK_VERIFIED", text)
        self.assertIn("HARD_BLOCKER_ROLLBACK_INCOMPLETE", text)
        self.assertIn("socket not enabled", text)
        self.assertIn("-m 0700 /var/lib/nexolab-operator /var/lib/nexolab-operator/reports", text)

    def test_installer_client_reports_kernel_denial_at_the_socket_file(self) -> None:
        text = INSTALLER.read_text()
        client = text[text.index("CLIENT='") + len("CLIENT='"):text.index("'\nclient()")]
        broker = RunningBroker()
        try:
            os.chmod(broker.socket, 0o000)  # stands in for "not in the socket group"
            out = subprocess.run([sys.executable, "-I", "-c", client, "broker.list", broker.socket],
                                 capture_output=True, text=True, timeout=30)
            if os.geteuid() == 0:
                self.skipTest("root bypasses file permissions")
            self.assertEqual(out.stdout.strip(), "DENIED_FS EACCES", out.stderr)
            os.chmod(broker.socket, 0o600)
            out = subprocess.run([sys.executable, "-I", "-c", client, "broker.list", broker.socket],
                                 capture_output=True, text=True, timeout=30)
            self.assertTrue(out.stdout.startswith("True None"), out.stdout + out.stderr)
        finally:
            broker.close()


class BrokerV11Tests(unittest.TestCase):
    """#1758 v1.1: redaction boundaries, log tails, Phase 0 model, approved handlers."""

    def test_redaction_never_crosses_lines_and_keeps_flags(self) -> None:
        text = ("802-11-wireless-security.key-mgmt:      wpa-psk\n"
                "802-11-wireless-security.pmf:           0 (default)\n"
                "802-11-wireless-security.psk-flags:     0 (none)\n"
                "802-11-wireless-security.psk:           supersecret\n"
                "password=hunter2 next")
        out, _ = broker_module.redact(text)
        self.assertIn("802-11-wireless-security.pmf:           0 (default)", out)
        self.assertIn("psk-flags:     0 (none)", out)
        self.assertNotIn("supersecret", out)
        self.assertNotIn("hunter2", out)

    def test_run_can_keep_the_tail(self) -> None:
        script = "import sys\nfor i in range(20000): print(f'line {i}')"
        result = broker_module.run([sys.executable, "-c", script], 30, max_bytes=2000, keep="tail")
        self.assertTrue(result.truncated)
        self.assertIn("line 19999", result.output)
        self.assertNotIn("line 0\n", result.output)
        self.assertLessEqual(len(result.output), 2000)

    def test_env_values_only_for_safe_configuration_keys(self) -> None:
        env = broker_module.sanitize_env([
            "CENTRAL_MQTT_HOST=172.18.48.66", "CENTRAL_MQTT_PORT=1884", "MQTT_PASSWORD=x", "DATABASE_URL=postgresql://u:p@db/x",
            "NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082", "JWT_SECRET=abc", "PATH=/usr/bin",
            "SESSION_TOKEN_URL=http://secret", "NODE_ENV=production"])
        self.assertIn("CENTRAL_MQTT_HOST=172.18.48.66", env)
        self.assertIn("NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082", env)
        for hidden in ("MQTT_PASSWORD=<set>", "JWT_SECRET=<set>", "PATH=<set>", "SESSION_TOKEN_URL=<set>"):
            self.assertIn(hidden, env)
        self.assertIn("DATABASE_URL=postgresql://u:p@db/x", env)  # raw here; redact() strips the userinfo
        self.assertNotIn("p@db", broker_module.redact("\n".join(env))[0])

    def test_runtime_model_covers_only_nexolab_and_hides_secrets(self) -> None:
        import json as _json
        inspect = "\t".join(_json.dumps(v) for v in (
            "/nexolab-central-dashboard-1", "nexolab/dashboard:x", "sha256:aa", "unless-stopped", "nexolab-central",
            {"3000/tcp": [{"HostIp": "172.18.48.66", "HostPort": "3000"}]},
            {"nexolab-central": {"Aliases": ["dashboard"], "IPAddress": "172.20.0.5"}},
            [{"Type": "volume", "Name": "v1", "Destination": "/data", "RW": True}],
            ["NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082", "AUTH_SECRET=zzz"],
            {"com.docker.compose.project": "nexolab-central", "secret.label": "x"}, {"Test": ["CMD", "true"]}))

        class Fake(FakeDocker):
            def __call__(self, argv, _timeout, **_kw):
                if argv[:2] == ["docker", "inspect"]:
                    return broker_module.RunResult(0, inspect, False, False)
                if argv[:3] == ["docker", "network", "inspect"]:
                    return broker_module.RunResult(0, '"bridge"\t[{"Subnet":"172.20.0.0/16"}]\t{}', False, False)
                if argv[:3] == ["docker", "network", "ls"]:
                    return broker_module.RunResult(0, "nexolab-central\nsellora_default", False, False)
                return super().__call__(argv, _timeout)

        runner = Fake()
        broker = type("B", (), {"runner": staticmethod(runner)})()
        model = broker_module.op_docker_runtime_model(broker, {})
        names = [c["name"] for c in model["containers"]]
        self.assertNotIn("sellora-backend-1", " ".join(str(c) for c in runner.calls))
        self.assertTrue(all(n.startswith("nexolab-") for n in names))
        text = _json.dumps(model)
        self.assertNotIn("zzz", text)
        self.assertNotIn("secret.label", text)
        self.assertIn("AUTH_SECRET=<set>", text)
        self.assertEqual([n["name"] for n in model["networks"]], ["nexolab-central"])

    def test_cleanup_removes_only_untagged_unused_images_without_force(self) -> None:
        calls: list[list[str]] = []
        tagged, used, free = "sha256:" + "1" * 64, "sha256:" + "2" * 64, "sha256:" + "3" * 64

        def runner(argv, _timeout, **_kw):
            calls.append(argv)
            out = ""
            if argv[:3] == ["docker", "volume", "ls"]:
                out = "pgdata\nmqtt"
            elif argv[:2] == ["docker", "ps"]:
                out = "c1"
            elif argv[:2] == ["docker", "inspect"]:
                out = used
            elif argv[:2] == ["docker", "images"]:
                out = "\n".join((tagged, used, free))
            elif argv[:3] == ["docker", "image", "inspect"]:
                out = '["nexolab/dashboard:recovery-protected-arm64"]' if argv[-1] == tagged else "[]"
            return broker_module.RunResult(0, out, False, False)

        broker = type("B", (), {"runner": staticmethod(runner)})()
        result = broker_module.op_storage_cleanup_regenerable(broker, {})
        removals = [c for c in calls if c[:3] == ["docker", "image", "rm"]]
        self.assertEqual(removals, [["docker", "image", "rm", "--", free]])
        self.assertTrue(all("-f" not in c and "--force" not in c for c in removals))
        self.assertIn(["docker", "builder", "prune", "--force", "--filter", "until=168h"], calls)
        self.assertFalse([c for c in calls if "volume" in c and ("rm" in c or "prune" in c)])
        self.assertEqual(sorted(result["steps"][1]["skipped_protected"]), sorted([tagged, used]))

    def test_cleanup_stops_if_volume_set_changes(self) -> None:
        state = {"n": 0}

        def runner(argv, _timeout, **_kw):
            out = ""
            if argv[:3] == ["docker", "volume", "ls"]:
                state["n"] += 1
                out = "pgdata" if state["n"] == 1 else ""
            return broker_module.RunResult(0, out, False, False)

        broker = type("B", (), {"runner": staticmethod(runner)})()
        with self.assertRaises(broker_module.Rejected):
            broker_module.op_storage_cleanup_regenerable(broker, {})

    def test_retire_legacy_https_requires_the_prepared_only_unit(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as temp:
            unit = Path(temp) / "nexolab-external-frontend.service"
            unit.write_text("[Unit]\nDescription=real production unit\n")
            calls: list[list[str]] = []

            def runner(argv, _timeout, **_kw):
                calls.append(argv)
                out = f"FragmentPath={unit}\nActiveState=activating\nSubState=auto-restart" if argv[:2] == [
                    "systemctl", "show"] else ""
                return broker_module.RunResult(0, out, False, False)

            broker = type("B", (), {"runner": staticmethod(runner)})()
            with mock.patch.object(broker_module, "live_https_identity", return_value={"build_id": "b"}):
                with self.assertRaises(broker_module.Rejected):
                    broker_module.op_service_retire_legacy_https(broker, {})
                self.assertFalse([c for c in calls if c[:2] != ["systemctl", "show"]])
                unit.write_text("# PREPARED ONLY: not installed/enabled\n[Unit]\n")
                with mock.patch.object(broker_module.time, "sleep"):
                    result = broker_module.op_service_retire_legacy_https(broker, {})
            self.assertIn(["systemctl", "mask", "nexolab-external-frontend.service"], calls)
            self.assertIn(["systemctl", "disable", "--now", "nexolab-external-nginx.service"], calls)
            self.assertTrue(result["live_https_identity_unchanged"])


class BrokerV12Tests(unittest.TestCase):
    """#1775 v1.2: upgrade rollback, bound deployment, DR backup handlers, mask on /etc units."""

    def setUp(self) -> None:
        from unittest import mock
        self.mock = mock
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "inbox"
        self.deploy = self.root / "deploy"
        self.home = self.root / "home"
        self.install = self.root / "lib"
        for path in (self.inbox, self.deploy, self.home, self.install / "handlers"):
            path.mkdir(parents=True)
        (self.install / "handlers" / "wp2c-stage2-frontend.py").write_text("# pinned tool\n")
        self.calls: list[list[str]] = []
        patches = [mock.patch.object(broker_module, "DEPLOY_DIR", self.deploy),
                   mock.patch.object(broker_module, "inbox_dir", lambda _b: self.inbox),
                   mock.patch.object(broker_module, "deploy_account", lambda _b: ("nexolab", self.home, os.getgid()))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

    def broker(self, exit_code: int = 0, output: str = "STAGE2_PREPARED\n") -> object:
        def runner(argv, _timeout, **_kw):
            self.calls.append(argv)
            return broker_module.RunResult(exit_code, output, False, False)
        return type("B", (), {"runner": staticmethod(runner), "install_dir": self.install,
                              "trusted_uid": os.getuid(), "allowed_uids": {1001}})()

    def artifact(self, data: bytes = b"zip-bytes") -> str:
        digest = hashlib.sha256(data).hexdigest()
        (self.inbox / f"{digest}.zip").write_bytes(data)
        return digest

    def args(self, phase: str, sha: str) -> dict:
        return {"phase": phase, "artifact_sha256": sha, "expect_current_source": "7db6e1a8" + "0" * 32,
                "expect_current_build": "CWBsCWWebOZGHa5YyWp18"}

    def test_prepare_stages_a_verified_copy_and_runs_the_pinned_tool_as_the_owner(self) -> None:
        sha = self.artifact()
        result = broker_module.op_deploy_lan_frontend(self.broker(), self.args("prepare", sha))
        self.assertTrue(result["ok"])
        self.assertEqual([s["step"] for s in result["steps"]], ["stage", "build", "preview", "check"])
        staged = self.deploy / f"{sha}.zip"
        self.assertEqual(staged.read_bytes(), b"zip-bytes")
        self.assertEqual(oct(staged.stat().st_mode & 0o777), "0o640")
        for call in self.calls:
            self.assertEqual(call[:6], ["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "--uid=nexolab"])
            self.assertIn("NoNewPrivileges=yes", call)
            self.assertIn(str(self.install / "handlers" / "wp2c-stage2-frontend.py"), call)
        stage_call = self.calls[0]
        self.assertEqual(stage_call[stage_call.index("--artifact-zip") + 1], str(staged))
        self.assertIn(sha, stage_call)
        self.assertIn("CWBsCWWebOZGHa5YyWp18", self.calls[1])
        self.assertFalse(result["production_changed"])

    def test_artifact_bytes_must_match_the_approved_hash(self) -> None:
        sha = hashlib.sha256(b"approved").hexdigest()
        (self.inbox / f"{sha}.zip").write_bytes(b"swapped by the dev account")
        with self.assertRaises(broker_module.Rejected) as ctx:
            broker_module.op_deploy_lan_frontend(self.broker(), self.args("prepare", sha))
        self.assertEqual(ctx.exception.code, "approval_mismatch")
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.deploy.iterdir()), [])

    def test_symlinked_artifact_is_refused(self) -> None:
        real = self.root / "elsewhere.zip"
        real.write_bytes(b"x")
        sha = hashlib.sha256(b"x").hexdigest()
        (self.inbox / f"{sha}.zip").symlink_to(real)
        with self.assertRaises(broker_module.Rejected):
            broker_module.op_deploy_lan_frontend(self.broker(), self.args("prepare", sha))
        self.assertEqual(self.calls, [])

    def test_workspace_staged_with_another_artifact_is_refused(self) -> None:
        sha = self.artifact()
        workspace = self.home / broker_module.STAGE2_WORKSPACE
        workspace.mkdir(parents=True)
        (workspace / "stage.json").write_text(json.dumps({"zip_sha256": "f" * 64}))
        for phase in ("prepare", "execute"):
            with self.assertRaises(broker_module.Rejected) as ctx:
                broker_module.op_deploy_lan_frontend(self.broker(), self.args(phase, sha))
            self.assertEqual(ctx.exception.code, "approval_mismatch")
        self.assertEqual(self.calls, [])

    def test_execute_needs_a_prepared_workspace_and_skips_restaging(self) -> None:
        sha = self.artifact()
        with self.assertRaises(broker_module.Rejected):
            broker_module.op_deploy_lan_frontend(self.broker(), self.args("execute", sha))
        workspace = self.home / broker_module.STAGE2_WORKSPACE
        workspace.mkdir(parents=True)
        (workspace / "stage.json").write_text(json.dumps({"zip_sha256": sha}))
        result = broker_module.op_deploy_lan_frontend(self.broker(output="STAGE2_FRONTEND_GREEN\n"),
                                                      self.args("execute", sha))
        self.assertEqual([s["step"] for s in result["steps"]], ["execute"])
        self.assertIn("STAGE2_FRONTEND_GREEN", result["steps"][0]["markers"])
        self.assertTrue(result["production_changed"])
        self.calls.clear()
        result = broker_module.op_deploy_lan_frontend(self.broker(), self.args("prepare", sha))
        self.assertEqual([s["step"] for s in result["steps"]], ["build", "preview", "check"])
        (workspace / "build.json").write_text("{}")
        result = broker_module.op_deploy_lan_frontend(self.broker(), self.args("prepare", sha))
        self.assertEqual([s["step"] for s in result["steps"]], ["preview", "check"])

    def test_a_failed_step_stops_the_sequence(self) -> None:
        sha = self.artifact()
        result = broker_module.op_deploy_lan_frontend(self.broker(exit_code=2, output="STOP WRONG_NODE x\n"),
                                                      self.args("prepare", sha))
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["steps"]), 1)
        self.assertEqual(result["steps"][0]["markers"], ["STOP WRONG_NODE x"])

    def test_deploy_schema_binds_phase_hash_and_current_identity(self) -> None:
        schema = broker_module.production_ops()["deploy.lan-frontend"].schema
        self.assertEqual(set(schema), {"phase", "artifact_sha256", "expect_current_source", "expect_current_build"})
        with self.assertRaises(broker_module.Rejected):
            broker_module.validate_args(schema, {"phase": "execute", "artifact_sha256": "../../etc/passwd",
                                                 "expect_current_source": "a" * 40, "expect_current_build": "abcdefgh"})
        with self.assertRaises(broker_module.Rejected):
            broker_module.validate_args(schema, {"phase": "shell", "expect_current_source": "a" * 40,
                                                 "expect_current_build": "abcdefgh"})

    def test_stage3_prove_runs_only_the_prove_mode_as_the_owner(self) -> None:
        (self.install / "handlers" / "wp2c-stage3-backend.py").write_text("# pinned tool\n")
        broker = self.broker(output="COMPOSE_FIDELITY_PROVEN central-mqtt (x)\nSTAGE3_PROVE_GREEN phase=switch services=5\n")
        result = broker_module.op_deploy_backend_loopback(broker, {"phase": "prove"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["production_changed"])
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call[:6], ["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "--uid=nexolab"])
        tool = call.index(str(self.install / "handlers" / "wp2c-stage3-backend.py"))
        self.assertEqual(call[tool + 1:tool + 4], ["prove", "--phase", "switch"])
        self.assertTrue(any(m.startswith("STAGE3_PROVE_GREEN") for m in result["markers"]))
        schema = broker_module.production_ops()["deploy.backend-loopback"].schema
        for phase in ("execute", "drop-compat", "rollback", "check"):
            with self.assertRaises(broker_module.Rejected):
                broker_module.validate_args(schema, {"phase": phase})

    def test_deploy_account_is_never_root_or_the_dev_account(self) -> None:
        self.mock.patch.stopall()
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
        fake = type("B", (), {"allowed_uids": {os.getuid()}})()
        with self.mock.patch.dict(os.environ, {broker_module.DEPLOY_USER_ENV: me}):
            with self.assertRaises(broker_module.Rejected):
                broker_module.deploy_account(fake)
        with self.mock.patch.dict(os.environ, {broker_module.DEPLOY_USER_ENV: "root"}):
            with self.assertRaises(broker_module.Rejected):
                broker_module.deploy_account(type("B", (), {"allowed_uids": {1001}})())

    def test_cleanup_build_cache_scope_is_an_approved_argument(self) -> None:
        schema = broker_module.production_ops()["storage.cleanup-regenerable"].schema
        self.assertEqual(broker_module.validate_args(schema, {}), {"build_cache": "older-than-7d"})
        self.assertEqual(broker_module.BUILD_CACHE_PRUNE["all-unused"], ["docker", "builder", "prune", "--all", "--force"])
        calls: list[list[str]] = []

        def runner(argv, _timeout, **_kw):
            calls.append(argv)
            return broker_module.RunResult(0, "v1" if argv[:3] == ["docker", "volume", "ls"] else "", False, False)

        broker_module.op_storage_cleanup_regenerable(type("B", (), {"runner": staticmethod(runner)})(),
                                                     {"build_cache": "all-unused"})
        self.assertIn(["docker", "builder", "prune", "--all", "--force"], calls)
        self.assertFalse([c for c in calls if "volume" in c and ("rm" in c or "prune" in c)])

    def test_backup_start_requires_the_installed_unit_and_config(self) -> None:
        def runner_for(state: str):
            def runner(argv, _timeout, **_kw):
                self.calls.append(argv)
                return broker_module.RunResult(0, state, False, False)
            return type("B", (), {"runner": staticmethod(runner)})()

        with self.assertRaises(broker_module.Rejected):
            broker_module.op_backup_start(runner_for("LoadState=not-found\nActiveState=inactive"), {})
        config = self.root / "dr-backup.json"
        with self.mock.patch.object(broker_module, "DR_CONFIG", config):
            with self.assertRaises(broker_module.Rejected):  # config missing
                broker_module.op_backup_start(runner_for("LoadState=loaded\nActiveState=inactive"), {})
            config.write_text("{}")
            with self.assertRaises(broker_module.Rejected) as ctx:
                broker_module.op_backup_start(runner_for("LoadState=loaded\nActiveState=activating"), {})
            self.assertEqual(ctx.exception.code, "busy")
        self.assertFalse([c for c in self.calls if c[:2] == ["systemctl", "start"]])

    def test_backup_health_never_reads_the_config(self) -> None:
        source = BROKER.read_text()
        health = source[source.index("def op_backup_health"):source.index("def op_backup_start")]
        self.assertNotIn("read_text", health)
        self.assertNotIn("open(", health)

    def test_retire_skips_mask_for_a_real_unit_file_in_etc(self) -> None:
        unit = self.root / "nexolab-external-frontend.service"
        unit.write_text("# PREPARED ONLY: not installed/enabled\n[Unit]\n")

        def runner(argv, _timeout, **_kw):
            self.calls.append(argv)
            out = (f"FragmentPath={unit}\nActiveState=inactive\nRequiredBy=nexolab-external-nginx.service"
                   if argv[:2] == ["systemctl", "show"] else "")
            return broker_module.RunResult(0, out, False, False)

        broker = type("B", (), {"runner": staticmethod(runner)})()
        with self.mock.patch.object(broker_module, "ETC_UNIT_DIR", self.root), \
                self.mock.patch.object(broker_module, "live_https_identity", return_value={"build_id": "b"}), \
                self.mock.patch.object(broker_module.time, "sleep"):
            result = broker_module.op_service_retire_legacy_https(broker, {})
        self.assertFalse([c for c in self.calls if c[:2] == ["systemctl", "mask"]])
        skipped = [a for a in result["actions"] if a.get("skipped")]
        self.assertEqual(len(skipped), 1)
        self.assertIn("RequiredBy", skipped[0]["pulled_in_by"])

    def test_installer_restores_the_previous_version_on_a_failed_upgrade(self) -> None:
        text = INSTALLER.read_text()
        upgrade = text[text.index("\nupgrade() {"):text.index("\nrollback() {")]
        # snapshot before anything is removed, and the restore target is armed before removal
        self.assertLess(upgrade.index('snapshot_to "$PREV.pending"'), upgrade.index("remove_installed"))
        self.assertLess(upgrade.index('RESTORE_FROM="$PREV.pending"'), upgrade.index("remove_installed"))
        self.assertLess(upgrade.index("trap 'die"), upgrade.index("remove_installed"))
        die = text[text.index("\ndie() {"):text.index("\n}", text.index("\ndie() {"))]
        self.assertIn('restore_from "$RESTORE_FROM"', die)
        self.assertIn("OPERATOR_BROKER_UPGRADE_ROLLED_BACK", die)
        self.assertIn("verify_removed || exit 2", die)  # restore failure still ends verified
        restore = text[text.index("\nrestore_from() {"):text.index("\ndie() {")]
        self.assertIn("sha256sum -c --quiet MANIFEST.sha256", restore)
        self.assertNotIn("die ", restore)  # runs inside die
        self.assertIn("acceptance", restore)
        self.assertIn("rollback) rollback ;;", text)
        self.assertIn('-m 0700 "$dir"', text)  # snapshots are root-only
        fault = [line for line in text.splitlines() if "NEXOLAB_OPERATOR_TEST_FAULT" in line]
        self.assertEqual(len(fault), 1)
        self.assertIn("|| die", fault[0])  # the test hook can only cause a rollback

    def test_service_unit_names_the_deploy_account_and_staging(self) -> None:
        unit = SERVICE.read_text()
        self.assertIn("Environment=NEXOLAB_OPERATOR_DEPLOY_USER=nexolab", unit)
        self.assertIn("ReadWritePaths=-/var/lib/nexolab-operator-deploy", unit)
        installer = INSTALLER.read_text()
        self.assertIn('-m 0750 "$DEPLOY_DIR"', installer)
        self.assertIn('"$STAGE/wp2c-stage2-frontend.py" "$LIB/handlers/wp2c-stage2-frontend.py"', installer)


class BrokerV13Tests(unittest.TestCase):
    """#1778 v1.3: manifest-bound image removal, bounded Wi-Fi test, Wi-Fi profile removal."""

    def setUp(self) -> None:
        from unittest import mock
        self.mock = mock
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        patch = mock.patch.object(broker_module, "inbox_dir", lambda _b: self.inbox)
        patch.start()
        self.addCleanup(patch.stop)
        clean = mock.patch.object(broker_module, "image_references", lambda entries: {
            "complete": True, "images": [{"ref": r, "id": i, "rollback_references": 0,
                                          "in_protected_images_file": False} for r, i in entries]})
        clean.start()
        self.addCleanup(clean.stop)
        self.calls: list[list[str]] = []

    def manifest(self, images: list[dict]) -> str:
        data = json.dumps({"images": images}).encode()
        sha = hashlib.sha256(data).hexdigest()
        (self.inbox / f"{sha}.json").write_bytes(data)
        return sha

    def docker(self, tags: dict[str, str], used: str = "") -> object:
        def runner(argv, _timeout, **_kw):
            self.calls.append(argv)
            out, code = "", 0
            if argv[:3] == ["docker", "volume", "ls"]:
                out = "pgdata\nmqtt"
            elif argv[:2] == ["docker", "ps"]:
                out = "c1" if used else ""
            elif argv[:2] == ["docker", "inspect"]:
                out = used
            elif argv[:3] == ["docker", "image", "inspect"]:
                if argv[-1] in tags:
                    out = tags[argv[-1]]
                else:
                    code = 1
            elif argv[:3] == ["docker", "image", "rm"]:
                out = f"Untagged: {argv[-1]}\nDeleted: sha256:x"
            return broker_module.RunResult(code, out, False, False)
        return type("B", (), {"runner": staticmethod(runner)})()

    def test_only_listed_unused_images_whose_tag_still_matches_are_removed(self) -> None:
        a, b, c = ("sha256:" + ch * 64 for ch in "abc")
        sha = self.manifest([{"ref": "nexolab/dashboard:issue-1522-469485b0-arm64", "id": a},
                             {"ref": "nexolab/telemetry-service:staged-2552b7ef77f7-arm64", "id": b},
                             {"ref": "nexolab/dashboard:issue-1603-edd04b4a-arm64", "id": c},
                             {"ref": "nexolab/dashboard:issue-1609-gone-arm64", "id": a}])
        broker = self.docker({"nexolab/dashboard:issue-1522-469485b0-arm64": a,
                              "nexolab/telemetry-service:staged-2552b7ef77f7-arm64": "sha256:" + "f" * 64,
                              "nexolab/dashboard:issue-1603-edd04b4a-arm64": c}, used=c)
        result = broker_module.op_storage_remove_images(broker, {"manifest_sha256": sha})
        status = {r["ref"]: r["status"] for r in result["results"]}
        self.assertEqual(status, {"nexolab/dashboard:issue-1522-469485b0-arm64": "deleted",
                                  "nexolab/telemetry-service:staged-2552b7ef77f7-arm64": "skipped_tag_moved",
                                  "nexolab/dashboard:issue-1603-edd04b4a-arm64": "skipped_in_use",
                                  "nexolab/dashboard:issue-1609-gone-arm64": "absent"})
        removals = [c for c in self.calls if c[:3] == ["docker", "image", "rm"]]
        self.assertEqual(removals, [["docker", "image", "rm", "--", "nexolab/dashboard:issue-1522-469485b0-arm64"]])
        self.assertTrue(result["volumes_unchanged"])

    def test_manifest_must_match_the_approved_hash_and_refuses_protected_or_foreign_images(self) -> None:
        good = "sha256:" + "a" * 64
        sha = hashlib.sha256(b"approved").hexdigest()
        (self.inbox / f"{sha}.json").write_text(json.dumps({"images": [{"ref": "nexolab/x:issue-1", "id": good}]}))
        with self.assertRaises(broker_module.Rejected) as ctx:
            broker_module.op_storage_remove_images(self.docker({}), {"manifest_sha256": sha})
        self.assertEqual(ctx.exception.code, "approval_mismatch")
        for ref in ("nexolab/telemetry-service:recovery-75ceb4654afb-tooling-75ceb4654afb-protected-arm64",
                    "nexolab/1518-telemetry-rollback:pre-3aaec39a", "nexolab/quick-central-base:1490",
                    "postgres:16-alpine", "sellora/backend:latest", "nexolab/x:issue-1 --force"):
            sha = self.manifest([{"ref": ref, "id": good}])
            with self.assertRaises(broker_module.Rejected, msg=ref):
                broker_module.op_storage_remove_images(self.docker({ref: good}), {"manifest_sha256": sha})
        self.assertFalse([c for c in self.calls if c[:3] == ["docker", "image", "rm"]])

    def nm(self, connections: str, route: str = "default via 192.168.1.1 dev eth0 proto dhcp metric 100",
           device_state: str = "30 (disconnected)", up_exit: int = 0) -> object:
        def runner(argv, _timeout, **_kw):
            self.calls.append(argv)
            out, code = "", 0
            if argv[:5] == ["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE,DEVICE", "connection"]:
                out = connections
            elif argv[:3] == ["ip", "-4", "route"]:
                out = route
            elif argv[:2] == ["systemctl", "show"]:
                out = "ActiveState=active"
            elif argv[:3] == ["nmcli", "-g", "GENERAL.STATE"]:
                out = device_state
            elif argv[:3] == ["nmcli", "-g", "802-11-wireless.cloned-mac-address"]:
                out = ""
            elif argv[:4] == ["nmcli", "--wait", "45", "connection"]:
                code = up_exit
            return broker_module.RunResult(code, out, False, False)
        return type("B", (), {"runner": staticmethod(runner)})()

    CONNECTIONS = ("Wired connection 1:u-eth:802-3-ethernet:yes:eth0\n"
                   "LAB KK1:u-lab:802-11-wireless:no:\n"
                   "me_mac:u-me:802-11-wireless:no:\n"
                   "odd\\:name:u-odd:802-11-wireless:no:\n")

    def test_random_mac_test_is_temporary_restored_and_never_left_up(self) -> None:
        with self.mock.patch.object(broker_module.time, "sleep"):
            result = broker_module.op_wifi_connect_test(self.nm(self.CONNECTIONS), {"profile": "LAB KK1",
                                                                                    "mac": "random"})
        modifies = [c for c in self.calls if c[:3] == ["nmcli", "connection", "modify"]]
        self.assertEqual(len(modifies), 2)
        self.assertTrue(all("--temporary" in c for c in modifies))
        self.assertEqual(modifies[0][-1], "random")
        self.assertEqual(modifies[1][-1], "")
        self.assertIn(["nmcli", "connection", "down", "uuid", "u-lab"], self.calls)
        self.assertTrue(result["connected"])
        self.assertFalse(result["kept_up"])
        self.assertTrue(result["ethernet_primary_after"])
        self.assertFalse([c for c in self.calls if "eth0" in c and c[0] == "nmcli"])

    def test_permanent_mac_test_changes_nothing_persistent(self) -> None:
        with self.mock.patch.object(broker_module.time, "sleep"):
            result = broker_module.op_wifi_connect_test(self.nm(self.CONNECTIONS, up_exit=4),
                                                        {"profile": "LAB KK1", "mac": "permanent"})
        self.assertFalse([c for c in self.calls if c[:3] == ["nmcli", "connection", "modify"]])
        self.assertFalse(result["connected"])

    def test_connect_test_preconditions(self) -> None:
        for kwargs in ({"route": "default via 10.0.0.1 dev wlan0 metric 600"}, {"device_state": "100 (connected)"},
                       {"connections": "LAB KK1:a:802-11-wireless:no:\nLAB KK1:b:802-11-wireless:no:\n"},
                       {"connections": "LAB KK1:a:802-3-ethernet:no:\n"}):
            params = {"connections": self.CONNECTIONS, **kwargs}
            with self.assertRaises(broker_module.Rejected, msg=str(kwargs)):
                broker_module.op_wifi_connect_test(self.nm(**params), {"profile": "LAB KK1", "mac": "random"})
        self.assertFalse([c for c in self.calls if c[:2] == ["nmcli", "--wait"]])

    def test_profile_remove_only_inactive_wifi(self) -> None:
        result = broker_module.op_wifi_profile_remove(self.nm(self.CONNECTIONS), {"profile": "odd:name"})
        self.assertIn(["nmcli", "connection", "delete", "uuid", "u-odd"], self.calls)
        self.assertEqual(result["deleted"], "odd:name")
        for name in ("Wired connection 1", "missing"):
            with self.assertRaises(broker_module.Rejected):
                broker_module.op_wifi_profile_remove(self.nm(self.CONNECTIONS), {"profile": name})
        active = self.CONNECTIONS.replace("me_mac:u-me:802-11-wireless:no:", "me_mac:u-me:802-11-wireless:yes:wlan0")
        with self.assertRaises(broker_module.Rejected):
            broker_module.op_wifi_profile_remove(self.nm(active), {"profile": "me_mac"})
        self.assertEqual([c for c in self.calls if c[:3] == ["nmcli", "connection", "delete"]],
                         [["nmcli", "connection", "delete", "uuid", "u-odd"]])


class BrokerV14Tests(unittest.TestCase):
    """#1782 v1.4: root-side image reference evidence and the removal guard."""

    def setUp(self) -> None:
        from unittest import mock
        self.mock = mock
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.object(broker_module, "PROTECTED_IMAGES_FILE", self.root / "absent")
        patch.start()
        self.addCleanup(patch.stop)
        self.rollback_id = "sha256:" + "ec4d14d34a41" + "1" * 52
        self.stale_id = "sha256:" + "0a01e99f497a" + "2" * 52
        self.entries = [("nexolab/dashboard:issue-1522-469485b0-arm64", self.rollback_id),
                        ("nexolab/dashboard:issue-1609-27b27386-arm64", self.stale_id)]

    def write(self, rel: str, text: str | bytes) -> Path:
        path = self.root / "records" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return path

    def test_scan_finds_ids_refs_and_tags_and_flags_rollback_context(self) -> None:
        self.write("ws/site-activation-report.json",
                   '{"frontend_rollback_release": "docker:nexolab/dashboard:issue-1522-469485b0-arm64"}\n')
        self.write("catalog/compose.yaml", f"image: {self.stale_id[7:19]}\n")
        self.write("ws/node_modules/x.json", f"{self.stale_id} rollback\n")      # skipped directory
        self.write("ws/bundle.tar", f"{self.rollback_id}\n")                     # not a text record
        self.write("ws/binary.json", b"\0" + self.stale_id.encode())            # binary
        (self.root / "records" / "ws" / "link.json").symlink_to(self.root / "records" / "ws" / "site-activation-report.json")
        result = broker_module.image_references(self.entries, roots=(self.root / "records",))
        by_ref = {i["ref"]: i for i in result["images"]}
        rollback = by_ref["nexolab/dashboard:issue-1522-469485b0-arm64"]
        self.assertEqual(rollback["references"], 1)
        self.assertEqual(rollback["rollback_references"], 1)
        stale = by_ref["nexolab/dashboard:issue-1609-27b27386-arm64"]
        self.assertEqual((stale["references"], stale["rollback_references"]), (1, 0))
        self.assertTrue(result["complete"])
        self.assertTrue(all("node_modules" not in e["path"] for i in result["images"] for e in i["evidence"]))

    def test_recovery_catalog_and_backup_paths_are_recovery_context(self) -> None:
        # #1789: the site recovery catalog referenced minio images on lines without any rollback word
        self.write("catalog/recovery-cc27b609eea2/deploy/compose/compose.central.yaml",
                   "    image: nexolab/dashboard:issue-1609-27b27386-arm64\n")
        self.write("catalog/plain/compose.yaml", f"image: {self.rollback_id[7:19]}\n")
        result = broker_module.image_references(self.entries, roots=(self.root / "records",))
        by_ref = {i["ref"]: i for i in result["images"]}
        stale = by_ref["nexolab/dashboard:issue-1609-27b27386-arm64"]
        self.assertEqual(stale["rollback_references"], 1)
        self.assertTrue(stale["evidence"][0]["recovery_path"])
        plain = by_ref["nexolab/dashboard:issue-1522-469485b0-arm64"]
        self.assertEqual((plain["references"], plain["rollback_references"]), (1, 0))
        for path in ("/var/lib/nexolab/version-management/catalog/x/manifest.json", "/var/backups/nexolab/a/b.txt",
                     "/home/nexolab/nexolab-platform/runtime/recovery/r.json", "/etc/nexolab-storage/protected-images"):
            self.assertTrue(broker_module.RECOVERY_PATH.search(path), path)
        self.assertFalse(broker_module.RECOVERY_PATH.search("/home/nexolab/commander-workspaces/nexolab-1518-test/x.py"))

    def test_snippets_are_redacted(self) -> None:
        self.write("ws/env.txt", f"ROLLBACK_IMAGE={self.stale_id} password=hunter2\n")
        result = broker_module.image_references(self.entries, roots=(self.root / "records",))
        lines = [e["line"] for i in result["images"] for e in i["evidence"]]
        self.assertTrue(lines)
        self.assertFalse([line for line in lines if "hunter2" in line])

    def test_protected_images_file_must_be_root_owned(self) -> None:
        path = self.root / "protected-images"
        path.write_text(f"# comment\n{self.stale_id}\n")
        with self.mock.patch.object(broker_module, "PROTECTED_IMAGES_FILE", path):
            if os.geteuid() == 0:
                self.assertEqual(broker_module.protected_image_ids(), {self.stale_id})
            else:
                with self.assertRaises(broker_module.Rejected):
                    broker_module.protected_image_ids()

    def test_removal_skips_rollback_referenced_and_protected_images(self) -> None:
        evidence = {"complete": True, "images": [
            {"ref": self.entries[0][0], "id": self.rollback_id, "rollback_references": 2, "in_protected_images_file": False},
            {"ref": self.entries[1][0], "id": self.stale_id, "rollback_references": 0, "in_protected_images_file": False}]}
        data = json.dumps({"images": [{"ref": r, "id": i} for r, i in self.entries]}).encode()
        sha = hashlib.sha256(data).hexdigest()
        (self.root / f"{sha}.json").write_bytes(data)
        calls: list[list[str]] = []

        def runner(argv, _timeout, **_kw):
            calls.append(argv)
            out = {("docker", "volume", "ls"): "pg"}.get(tuple(argv[:3]), "")
            if argv[:3] == ["docker", "image", "inspect"]:
                out = dict(self.entries)[argv[-1]]
            if argv[:3] == ["docker", "image", "rm"]:
                out = "Untagged: x\nDeleted: y"
            return broker_module.RunResult(0, out, False, False)

        with self.mock.patch.object(broker_module, "inbox_dir", lambda _b: self.root), \
                self.mock.patch.object(broker_module, "image_references", lambda _e: evidence):
            result = broker_module.op_storage_remove_images(type("B", (), {"runner": staticmethod(runner)})(),
                                                            {"manifest_sha256": sha})
        status = {r["ref"]: r["status"] for r in result["results"]}
        self.assertEqual(status[self.entries[0][0]], "skipped_protected_or_rollback_record")
        self.assertEqual(status[self.entries[1][0]], "deleted")
        self.assertEqual([c for c in calls if c[:3] == ["docker", "image", "rm"]],
                         [["docker", "image", "rm", "--", self.entries[1][0]]])
        evidence["complete"] = False
        with self.mock.patch.object(broker_module, "inbox_dir", lambda _b: self.root), \
                self.mock.patch.object(broker_module, "image_references", lambda _e: evidence):
            with self.assertRaises(broker_module.Rejected):
                broker_module.op_storage_remove_images(type("B", (), {"runner": staticmethod(runner)})(),
                                                       {"manifest_sha256": sha})

    def test_reference_scan_is_a_bounded_read_operation(self) -> None:
        op = broker_module.production_ops()["storage.image-references"]
        self.assertEqual((op.kind, op.heavy), ("read", True))
        source = BROKER.read_text()
        scan = source[source.index("def image_references"):source.index("def op_storage_image_references")]
        self.assertIn("followlinks=False", scan)
        self.assertIn("O_NOFOLLOW", scan)
        for forbidden in ("unlink", "rmtree", "write_", "chmod", "rename"):
            self.assertNotIn(forbidden, scan)


class BrokerStaticContractTests(unittest.TestCase):
    def test_no_shell_or_generic_execution_paths(self) -> None:
        source = BROKER.read_text()
        for forbidden in ("shell=True", "os.system", "os.popen", "--show-secrets", " -s ", "eval(", "exec(",
                          "docker exec", '"exec"', "/run/docker.sock", "modbus", "pickle"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_production_operations_are_fixed_and_classified(self) -> None:
        ops = broker_module.production_ops()
        self.assertGreaterEqual(len(ops), 15)
        for name, op in ops.items():
            self.assertRegex(name, broker_module.OP_NAME.pattern)
            self.assertIn(op.kind, ("read", "recover", "approved"))
            self.assertNotRegex(name, r"exec|shell|script|run|sudo|prune|delete|rm\b|write|modbus")
        approved = sorted(op.name for op in ops.values() if op.kind == "approved")
        self.assertEqual(approved, ["backup.start", "deploy.backend-loopback", "deploy.lan-frontend",
                                    "service.restore-legacy-https",
                                    "service.retire-legacy-https", "storage.cleanup-regenerable",
                                    "storage.remove-images", "wifi.connect-test",
                                    "wifi.profile-remove"])  # each one reviewed explicitly
        recover = [op for op in ops.values() if op.kind == "recover"]
        self.assertEqual([op.name for op in recover], ["service.recover"])
        self.assertEqual(set(broker_module.RECOVERABLE_UNITS),
                         {"nexolab-lan-gateway.service", "nexolab-network-endpoint-repair.service"})
        self.assertNotIn("nexolab-gitlab-sync.service", broker_module.READABLE_UNITS)

    def test_recover_never_acts_on_a_running_or_disabled_unit(self) -> None:
        def fake_broker(state: dict) -> object:
            calls: list[list[str]] = []

            def runner(argv, _timeout):
                calls.append(argv)
                if argv[:2] == ["systemctl", "show"]:
                    return broker_module.RunResult(0, "\n".join(f"{k}={v}" for k, v in state.items()), False, False)
                return broker_module.RunResult(0, "", False, False)
            return type("B", (), {"runner": staticmethod(runner), "calls": calls})()

        for state in ({"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active"},
                      {"LoadState": "loaded", "UnitFileState": "disabled", "ActiveState": "failed"},
                      {"LoadState": "not-found", "UnitFileState": "", "ActiveState": "inactive"}):
            fake = fake_broker(state)
            with self.assertRaises(broker_module.Rejected):
                broker_module.op_service_recover(fake, {"unit": "nexolab-lan-gateway.service"})
            self.assertFalse(any(c[:2] == ["systemctl", "restart"] for c in fake.calls))
        fake = fake_broker({"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "failed"})
        broker_module.op_service_recover(fake, {"unit": "nexolab-lan-gateway.service"})
        self.assertIn(["systemctl", "restart", "--no-block", "nexolab-lan-gateway.service"], fake.calls)

    def test_wifi_profile_never_requests_secrets(self) -> None:
        fields = broker_module.WIFI_PROFILE_FIELDS.split(",")
        self.assertNotIn("802-11-wireless-security.psk", fields)
        self.assertFalse([f for f in fields if re.search(r"psk$|wep-key|password|leap-password", f)])

    def test_service_unit_hardening(self) -> None:
        unit = SERVICE.read_text()
        directives = [line for line in unit.splitlines() if line and not line.startswith("#")]
        text = "\n".join(directives)
        for required in ("NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=read-only", "PrivateTmp=yes",
                         "DevicePolicy=closed", "MemoryMax=", "TasksMax=", "CPUQuota=",
                         "Environment=NEXOLAB_OPERATOR_ALLOWED_UIDS=1001",
                         "ExecStart=/usr/bin/python3 -I -B /usr/local/lib/nexolab-operator/nexolab-operator-broker.py serve",
                         "InaccessiblePaths=-/etc/nexolab-gitlab-sync"):
            self.assertIn(required, text)
        caps = re.search(r"^CapabilityBoundingSet=(.*)$", text, re.M).group(1).split()
        self.assertEqual(set(caps), {"CAP_DAC_READ_SEARCH", "CAP_CHOWN", "CAP_FOWNER"})
        self.assertNotIn("--test", text)
        self.assertNotIn("[Install]", unit)  # only the socket is enabled
        sock = SOCKET_UNIT.read_text()
        for required in ("ListenStream=/run/nexolab-operator/broker.sock", "SocketMode=0660",
                         "SocketGroup=nexolab-dev", "SocketUser=root", "Accept=no"):
            self.assertIn(required, sock)

    def test_installer_pins_every_payload_file(self) -> None:
        text = INSTALLER.read_text()
        pins = dict(re.findall(r'^\s*\[([A-Za-z0-9_./-]+)\]=([0-9a-f]{64})\s*$', text, re.M))
        expected = {
            "nexolab-operator-broker.py": BROKER,
            "nexolab-operator-broker.service": SERVICE,
            "nexolab-operator-broker.socket": SOCKET_UNIT,
            "nexolab-storage-inventory.sh": ROOT / "docs" / "operations" / "storage" / "nexolab-storage-inventory.sh",
            "wp2c-stage2-frontend.py": ROOT / "docs" / "operations" / "network" / "wp2c-stage2-frontend.py",
            "wp2c-stage3-backend.py": ROOT / "docs" / "operations" / "network" / "wp2c-stage3-backend.py",
        }
        self.assertEqual(set(pins), set(expected))
        for name, path in expected.items():
            self.assertEqual(pins[name], hashlib.sha256(path.read_bytes()).hexdigest(), name)
        self.assertNotIn("broker-test-ops", text)
        for forbidden in ("docker system prune", "volume prune", "down -v", "reboot", "chmod 777", "NOPASSWD"):
            self.assertNotIn(forbidden, text)

    def test_systemd_analyze_accepts_units(self) -> None:
        analyze = shutil.which("systemd-analyze")
        if analyze is None:
            self.skipTest("systemd-analyze not available")
        out = subprocess.run([analyze, "verify", "--man=no", str(SOCKET_UNIT), str(SERVICE)],
                             capture_output=True, text=True, timeout=60)
        problems = [line for line in out.stderr.splitlines()
                    if "nexolab-operator-broker" in line and not re.search(r"is not executable|No such file|Command .* is not|"
                                                      r"Failed to prepare filename|Unit .* not found|"
                                                      r"Failed to create .*: (Permission|Read-only)|"
                                                      r"Neither a valid executable", line)]
        self.assertEqual(problems, [], out.stderr)


if __name__ == "__main__":
    unittest.main()
