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
            self.assertIn(op.kind, ("read", "recover"))  # approved handlers arrive only in reviewed releases
            self.assertNotRegex(name, r"exec|shell|script|run|sudo|prune|delete|rm\b|write|modbus")
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
