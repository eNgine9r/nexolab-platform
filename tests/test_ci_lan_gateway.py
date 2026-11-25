"""Tests for the network-independent LOCAL_LAN gateway (#1734 WP2b)."""

from __future__ import annotations

import base64
import http.server
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "docs" / "operations" / "network" / "nexolab-lan-gateway.mjs"
UNIT = ROOT / "docs" / "operations" / "network" / "nexolab-lan-gateway.service"
NODE = shutil.which("node") or str(Path.home() / ".local" / "node" / "bin" / "node")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Upstream(http.server.BaseHTTPRequestHandler):
    name = "upstream"

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"upstream": self.name, "path": self.path,
                           "xff": self.headers.get("x-forwarded-for"),
                           "xfh": self.headers.get("x-forwarded-host")}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *args: object) -> None:
        pass


class _Api(_Upstream):
    name = "api"


class _Dashboard(_Upstream):
    name = "dashboard"


class _WebSocketEcho(threading.Thread):
    """Accepts one upgrade, answers 101 and echoes raw bytes back."""

    def __init__(self, server: socket.socket) -> None:
        super().__init__(daemon=True)
        self.server = server
        self.request = b""

    def run(self) -> None:
        conn, _ = self.server.accept()
        with conn:
            while b"\r\n\r\n" not in self.request:
                self.request += conn.recv(4096)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            data = conn.recv(4096)
            conn.sendall(data)


@unittest.skipUnless(Path(NODE).exists(), "node is required")
class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.servers = []
        self.api = self._serve(_Api)
        self.dash = self._serve(_Dashboard)
        self.port = _free_port()
        self.proc = self._start(self.api, self.dash)

    def _serve(self, handler: type) -> int:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return server.server_address[1]

    def _start(self, api: int, dash: int, extra: dict | None = None) -> subprocess.Popen:
        env = {**os.environ, "NEXOLAB_LAN_GATEWAY_HOST": "127.0.0.1", "NEXOLAB_LAN_GATEWAY_PORT": str(self.port),
               "NEXOLAB_LAN_GATEWAY_API": f"http://127.0.0.1:{api}", "NEXOLAB_LAN_GATEWAY_DASHBOARD": f"http://127.0.0.1:{dash}",
               **(extra or {})}
        proc = subprocess.Popen([NODE, str(GATEWAY)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return proc
            except OSError:
                if proc.poll() is not None:
                    return proc
                time.sleep(0.05)
        return proc

    def tearDown(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=5)
        for stream in (self.proc.stdout, self.proc.stderr):
            if stream:
                stream.close()
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def _get(self, path: str, host: str | None = None) -> tuple[int, dict | str]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if host:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=5) as res:
                raw = res.read().decode()
                return res.status, json.loads(raw) if raw.startswith("{") else raw
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    def test_routes_api_and_dashboard_on_the_same_origin(self) -> None:
        status, body = self._get("/api/v1/telemetry/latest?x=1", host="192.168.1.220:3000")
        self.assertEqual(status, 200)
        self.assertEqual(body["upstream"], "api")
        self.assertEqual(body["path"], "/api/v1/telemetry/latest?x=1")
        self.assertEqual(body["xfh"], "192.168.1.220:3000")
        self.assertEqual(self._get("/api/v1")[1]["upstream"], "api")
        for path in ("/", "/live", "/api/runtime-identity", "/api/device-agent/x", "/api/v10/x"):
            self.assertEqual(self._get(path)[1]["upstream"], "dashboard", path)

    def test_health_endpoint(self) -> None:
        status, body = self._get("/__nexolab_lan_gateway/health")
        self.assertEqual((status, body["status"]), (200, "ok"))

    def test_api_outage_is_explicit_and_dashboard_stays_up(self) -> None:
        self.servers[0].shutdown()
        self.servers[0].server_close()
        status, body = self._get("/api/v1/health/ready")
        self.assertEqual(status, 503)
        self.assertIn("telemetry api unavailable", body)
        self.assertEqual(self._get("/")[1]["upstream"], "dashboard")

    def test_websocket_upgrade_is_proxied_to_api_only(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        echo = _WebSocketEcho(listener)
        echo.start()
        self.proc.terminate()
        self.proc.wait(timeout=5)
        for stream in (self.proc.stdout, self.proc.stderr):
            stream and stream.close()
        self.proc = self._start(listener.getsockname()[1], self.dash)
        key = base64.b64encode(os.urandom(16)).decode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall((f"GET /api/v1/telemetry/live HTTP/1.1\r\nHost: nexolab-edge-01.local:3000\r\n"
                            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                            "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            reply = b""
            while b"\r\n\r\n" not in reply:
                reply += client.recv(4096)
            self.assertIn(b"101 Switching Protocols", reply)
            client.sendall(b"frame-bytes")
            self.assertEqual(client.recv(4096), b"frame-bytes")
        echo.join(timeout=5)
        self.assertIn(b"GET /api/v1/telemetry/live HTTP/1.1", echo.request)
        self.assertIn(b"sec-websocket-key: " + key.encode(), echo.request)
        listener.close()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(b"GET /live HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            self.assertIn(b"400", client.recv(4096))

    def test_traversal_is_rejected(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(b"GET /api/v1/../../etc HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            self.assertIn(b"400", client.recv(4096))


@unittest.skipUnless(Path(NODE).exists(), "node is required")
class ConfigTests(unittest.TestCase):
    def _refused(self, api: str) -> str:
        env = {**os.environ, "NEXOLAB_LAN_GATEWAY_HOST": "127.0.0.1", "NEXOLAB_LAN_GATEWAY_PORT": str(_free_port()),
               "NEXOLAB_LAN_GATEWAY_API": api}
        result = subprocess.run([NODE, str(GATEWAY)], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 64, result.stderr)
        return result.stderr

    def test_refuses_non_loopback_or_unsafe_upstreams(self) -> None:
        for api in ("http://192.168.1.220:8082", "http://172.18.48.66:8082", "https://127.0.0.1:8082",
                    "http://user:pw@127.0.0.1:8082", "http://127.0.0.1:8082/x", "http://evil.example:8082",
                    "http://127.0.0.1"):
            self.assertIn("NEXOLAB_LAN_GATEWAY_CONFIG_REFUSED", self._refused(api), api)


class UnitContractTests(unittest.TestCase):
    def test_unit_is_bounded_and_binds_all_interfaces(self) -> None:
        unit = UNIT.read_text(encoding="utf-8")
        for line in ("NoNewPrivileges=yes", "ProtectSystem=strict", "MemoryMax=", "Restart=always",
                     "NEXOLAB_LAN_GATEWAY_HOST=0.0.0.0", "NEXOLAB_LAN_GATEWAY_API=http://127.0.0.1:8082/"):
            self.assertIn(line, unit)
        self.assertNotIn("172.18.48.66", unit)
        self.assertNotIn("192.168.", unit)


if __name__ == "__main__":
    unittest.main()
