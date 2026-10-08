#!/usr/bin/env python3
"""Isolated NGINX/OAuth boundary smoke-test; no Google secrets or product services.

This test is deliberately DESTRUCTIVE TO NOTHING: it starts only temporary
loopback listeners on random ports, mocks all upstreams, and removes them after
testing. NEVER rewrite the production NGINX or OAuth files in place.
"""
from __future__ import annotations

import argparse
import http.client
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


EXTERNAL_HOST = "nexolab-edge-01.tail7f9b04.ts.net"
NEEDED = (
    "listen 127.0.0.1:18790;",
    "proxy_pass http://127.0.0.1:4180/oauth2/auth;",
    "proxy_pass http://127.0.0.1:4180;",
    "proxy_pass http://REPLACE_WITH_APPROVED_PRIVATE_API_IP:8082;",
    "proxy_pass http://127.0.0.1:3100;",
    "include /etc/nginx/mime.types;",
)


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_mock(name: str, forwarded: list[tuple[str, str]]):
    class MockHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            pass  # No cookies, URLs, identities or tokens in test logs.

        def do_GET(self) -> None:
            if name == "oauth":
                if self.path.startswith("/oauth2/auth"):
                    self.send_response(202 if "fixture-ok=1" in self.headers.get("Cookie", "") else 401)
                else:
                    self.send_response(200)
                self.end_headers()
                return
            forwarded.append((name, self.path))
            is_websocket = self.headers.get("Upgrade", "").lower() == "websocket"
            self.send_response(101 if is_websocket else 200)
            if is_websocket:
                self.send_header("Connection", "Upgrade")
                self.send_header("Upgrade", "websocket")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, name=f"fake-{name}", daemon=True)
    thread.start()
    return server, thread


def render_template(source: str, *, auth_port: int, api_port: int, web_port: int,
                    gateway_port: int, work: Path) -> str:
    for expected in NEEDED:
        expected_count = 2 if expected == "proxy_pass http://127.0.0.1:3100;" else 1
        if source.count(expected) != expected_count:
            raise AssertionError(f"unreviewed NGINX template: {expected}")
    prepared = source.replace(
        "listen 127.0.0.1:18790;", f"listen 127.0.0.1:{gateway_port};"
    ).replace(
        "proxy_pass http://127.0.0.1:4180/oauth2/auth;",
        f"proxy_pass http://127.0.0.1:{auth_port}/oauth2/auth;",
    ).replace(
        "proxy_pass http://127.0.0.1:4180;",
        f"proxy_pass http://127.0.0.1:{auth_port};",
    ).replace(
        "proxy_pass http://REPLACE_WITH_APPROVED_PRIVATE_API_IP:8082;",
        f"proxy_pass http://127.0.0.1:{api_port};",
    ).replaceAll(
        "proxy_pass http://127.0.0.1:3100;",
        f"proxy_pass http://127.0.0.1:{web_port};",
    ).replace(
        "include /etc/nginx/mime.types;", "types { text/plain txt; }"
    ).replace(
        "pid /tmp/nexolab-external-https-stage-nginx.pid;",
        f"pid {work / 'nginx.pid'};",
    )
    # Avoid relying on any machine-wide /var/lib/nginx directories.
    prepared = prepared.replace(
        "http {", "http {\n" +
        f"  client_body_temp_path {work / 'body'};\n" +
        f"  proxy_temp_path {work / 'proxy'};\n",
        1,
    )
    return prepared


def get(port: int, path: str, *, allowed: bool = False, wrong_host: bool = False,
        upgrade: bool = False) -> tuple[int, dict[str, str]]:
    headers = {"Host": "invalid.example" if wrong_host else EXTERNAL_HOST}
    if allowed:
        headers["Cookie"] = "fixture-ok=1"
    if upgrade:
        headers.update({
            "Connection": "Upgrade",
            "Upgrade": "websocket",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        })
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        conn.request("GET", path, headers=headers)
        result = conn.getresponse()
        result.read()
        return result.status, dict(result.getheaders())
    finally:
        conn.close()


def run(binary: Path, template: Path) -> None:
    if not binary.is_file() or not template.is_file():
        raise AssertionError("NGINX binary and source template must exist")
    source = template.read_text(encoding="utf-8")
    forwarded: list[tuple[str, str]] = []
    mock_servers = []
    nginx: subprocess.Popen[bytes] | None = None
    with tempfile.TemporaryDirectory(prefix="nexolab-nginx-oauth-test-") as work_name:
        work = Path(work_name)
        for kind in ("body", "proxy"):
            (work / kind).mkdir()
        try:
            for name in ("oauth", "api", "web"):
                mock_servers.append(start_mock(name, forwarded))
            auth_port, api_port, web_port = (
                server.server_address[1] for server, _thread in mock_servers
            )
            gateway_port = free_local_port()
            conf = work / "nginx.conf"
            conf.write_text(
                render_template(
                    source, auth_port=auth_port, api_port=api_port,
                    web_port=web_port, gateway_port=gateway_port, work=work
                ), encoding="utf-8"
            )
            cmd = [str(binary), "-p", str(work) + "/", "-c", str(conf)]
            syntactic = subprocess.run(
                cmd + ["-t"], capture_output=True, text=True, timeout=10
            )
            if syntactic.returncode:
                raise AssertionError("NGINX config -t failed (no product changes): " + syntactic.stderr[:1400])
            nginx = subprocess.Popen(
                cmd + ["-g", "daemon off;"], stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            for _ in range(30):
                if nginx.poll() is not None:
                    err = nginx.stderr.read(1000).decode("utf-8", "replace")
                    raise AssertionError("isolated NGINX refused to start: " + err)
                try:
                    get(gateway_port, "/oauth2/start")
                    break
                except (OSError, http.client.HTTPException):
                    time.sleep(0.1)
            else:
                raise AssertionError("isolated NGINX did not bind within 3s")

            def expect(label: str, path: str, code: int, **kwargs: bool):
                before = len(forwarded)
                status, headers = get(gateway_port, path, **kwargs)
                if status != code:
                    raise AssertionError(f"{label}: expected HTTP {code}, got {status}")
                print(f"PASS {label}: HTTP {status}")
                return before, len(forwarded), headers

            before, after, headers = expect("browser requires sign-in", "/", 302)
            assert before == after and headers.get("Location") == "/oauth2/start?rd=%2F"
            before, after, _ = expect("API is blocked without OAuth", "/api/v1/private", 401)
            assert before == after
            before, after, _ = expect(
                "device-agent is blocked without OAuth",
                "/api/device-agent/private", 401
            )
            assert before == after
            before, after, _ = expect(
                "unauthorized WebSocket handshake blocked",
                "/api/v1/telemetry/live", 401, upgrade=True
            )
            assert before == after
            before, after, _ = expect("wrong host rejected", "/", 421, wrong_host=True)
            assert before == after
            before, after, _ = expect("gateway auth subrequest is internal", "/_nexolab_external_auth", 404)
            assert before == after
            before, after, _ = expect("fake authorized API forwarded", "/api/v1/private", 200, allowed=True)
            assert after == before + 1 and forwarded[-1] == ("api", "/api/v1/private")
            before, after, _ = expect(
                "fake authorized frontend forwarded", "/", 200, allowed=True
            )
            assert after == before + 1 and forwarded[-1] == ("web", "/")
            before, after, _ = expect(
                "fake authorized device route forwarded",
                "/api/device-agent/private", 200, allowed=True
            )
            assert after == before + 1 and forwarded[-1] == ("web", "/api/device-agent/private")
            before, after, headers = expect(
                "fake authorized WebSocket upgrade forwarded",
                "/api/v1/telemetry/live", 101, allowed=True, upgrade=True
            )
            assert after == before + 1 and forwarded[-1] == ("api", "/api/v1/telemetry/live")
            assert headers.get("Upgrade", "").lower() == "websocket"

            # Simulate identity service failure without touching any real service.
            mock_servers[0][0].shutdown()
            mock_servers[0][0].server_close()
            before = len(forwarded)
            status, _headers = get(gateway_port, "/")
            if status < 500 or len(forwarded) != before:
                raise AssertionError("identity proxy outage must fail closed without forwarding")
            print(f"PASS OAuth outage remains fail-closed: HTTP {status}")
            print("PASS: 10 synthetic HTTP cases; no Google, controllers, S3, LAN API or public route")
        finally:
            if nginx is not None:
                nginx.terminate()
                try:
                    nginx.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    nginx.kill()
                    nginx.communicate(timeout=4)
            for server, thread in mock_servers:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nginx-binary", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    args = parser.parse_args()
    run(args.nginx_binary, args.template)
