#!/usr/bin/env python3
"""Offline loopback proof using REAL oauth2-proxy + REAL NGINX and fake upstreams.

No real identity, Google credentials, token exchange, product API, hardware or
Internet access is required. Only deny/redirect paths can be verified offline.
Every process terminates on exit. Never run as root or enable Tailscale Funnel.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import importlib.util
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def import_fixture(source: Path):
    spec = importlib.util.spec_from_file_location("nexolab_nginx_fake_oauth_probe", source)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load NGINX synthetic fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_get(port: int, target: str, *, cookie: str = "", upgrade: bool = False,
             host: str = "nexolab-edge-01.tail7f9b04.ts.net"):
    headers = {"Host": host}
    if cookie:
        headers["Cookie"] = cookie
    if upgrade:
        headers.update({
            "Upgrade": "websocket", "Connection": "Upgrade",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        })
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        response.read()
        return response.status, response.getheaders()
    finally:
        connection.close()


def wait_for_service(port: int, proc: subprocess.Popen[bytes]) -> None:
    for _ in range(80):
        if proc.poll() is not None:
            raise AssertionError("synthetic service exited prematurely")
        try:
            http_get(port, "/oauth2/auth")
            return
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
    raise AssertionError("synthetic service did not bind loopback in time")


def stop(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)


def run(proxy: Path, nginx: Path, config: Path, nginx_config: Path, ng_fixture: Path) -> None:
    if os.geteuid() == 0:
        raise AssertionError("synthetic test must run unprivileged")
    for file in (proxy, nginx, config, nginx_config, ng_fixture):
        if not file.is_file():
            raise AssertionError("missing local synthetic test input")
    fixture = import_fixture(ng_fixture)
    forwarded: list[tuple[str, str]] = []
    service_handles = []
    oauth_proc = None
    nginx_proc = None
    with tempfile.TemporaryDirectory(prefix="nxl-real-oauth-fake-google-") as root:
        work = Path(root)
        work.chmod(0o700)
        (work / "secrets").mkdir(mode=0o700)
        for temp in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
            (work / temp).mkdir()
        local_config = work / "oauth2-proxy.cfg"
        source = config.read_text(encoding="utf-8")
        auth_port = fixture.free_local_port()
        old_address = 'http_address = "127.0.0.1:4180"'
        old_list = 'authenticated_emails_file = "/etc/nexolab-external/allowed-emails.txt"'
        if source.count(old_address) != 1 or source.count(old_list) != 1:
            raise AssertionError("unreviewed OAuth config template")
        local_list = work / "secrets" / "fake-allowed-emails.txt"
        local_list.write_text("fixture-operator@example.test\n", encoding="ascii")
        local_list.chmod(0o600)
        local_config.write_text(source.replace(old_address, f'http_address = "127.0.0.1:{auth_port}"').replace(
            old_list, f'authenticated_emails_file = "{local_list}"'
        ), encoding="utf-8")
        client_file = work / "secrets" / "fake-google-secret"
        cookie_file = work / "secrets" / "fake-cookie-secret"
        client_file.write_text("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xture", encoding="ascii")
        cookie_file.write_text(base64.b64encode(secrets.token_bytes(32)).decode("ascii"), encoding="ascii")
        for file in (client_file, cookie_file):
            file.chmod(0o600)
        # Actual OAuth binary, fake credentials and loopback-only. No env
        # credentials; Google endpoint is never contacted by this test.
        oauth_cmd = [
            str(proxy), "--config", str(local_config),
            "--client-id", "12345678-fixture.apps.googleusercontent.com",
            "--client-secret-file", str(client_file),
            "--cookie-secret-file", str(cookie_file),
        ]
        try:
            oauth_proc = subprocess.Popen(oauth_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            wait_for_service(auth_port, oauth_proc)
            code, _ = http_get(auth_port, "/oauth2/auth")
            if code != 401:
                raise AssertionError(f"unauthenticated real OAuth2 Proxy returned {code}, expected 401")
            print("PASS real oauth2-proxy denies absent session: HTTP 401")
            code, headers = http_get(auth_port, "/oauth2/start?rd=%2F")
            location = [value for name, value in headers if name.lower() == "location"]
            set_cookies = [value for name, value in headers if name.lower() == "set-cookie"]
            if code != 302 or not location or not location[0].startswith("https://accounts.google.com/"):
                raise AssertionError("synthetic OAuth login did not redirect to Google's HTTPS consent endpoint")
            if not set_cookies or not all("secure" in cookie.lower() and "httponly" in cookie.lower() for cookie in set_cookies):
                raise AssertionError("synthetic OAuth login did not set Secure, HttpOnly CSRF cookies")
            print("PASS real OAuth redirect uses HTTPS with Secure, HttpOnly CSRF cookies")
            code, _ = http_get(auth_port, "/oauth2/callback?code=fake-without-state")
            if code < 400:
                raise AssertionError("OAuth callback without matching CSRF state must fail")
            print(f"PASS callback without state rejected: HTTP {code}")

            for name in ("api", "web"):
                service_handles.append(fixture.start_mock(name, forwarded))
            api_port, web_port = (handle[0].server_address[1] for handle in service_handles)
            gateway_port = fixture.free_local_port()
            rendered = fixture.render_template(
                nginx_config.read_text(encoding="utf-8"),
                auth_port=auth_port, api_port=api_port,
                web_port=web_port, gateway_port=gateway_port, work=work,
            )
            ng_config = work / "nginx.conf"
            ng_config.write_text(rendered, encoding="utf-8")
            ng_cmd = [str(nginx), "-p", str(work) + "/", "-c", str(ng_config)]
            result = subprocess.run(ng_cmd + ["-t"], capture_output=True, text=True, timeout=8)
            if result.returncode != 0:
                raise AssertionError("NGINX static config failed: " + result.stderr[:500])
            nginx_proc = subprocess.Popen(ng_cmd + ["-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for _ in range(40):
                if nginx_proc.poll() is not None:
                    raise AssertionError("synthetic NGINX exited unexpectedly")
                try:
                    http_get(gateway_port, "/oauth2/auth")
                    break
                except (OSError, http.client.HTTPException):
                    time.sleep(0.1)
            else:
                raise AssertionError("synthetic NGINX did not bind loopback")
            cases = [
                ("anonymous browser", "/", 302, False),
                ("anonymous API", "/api/v1/private", 401, False),
                ("anonymous device agent", "/api/device-agent/private", 401, False),
                ("anonymous websocket", "/api/v1/telemetry/live", 401, True),
            ]
            for label, url, expected, upgrade in cases:
                previous = len(forwarded)
                status, headers = http_get(gateway_port, url, upgrade=upgrade)
                if status != expected or len(forwarded) != previous:
                    raise AssertionError(f"{label} must fail closed; got {status}")
                if expected == 302:
                    loc = [v for n, v in headers if n.lower() == "location"]
                    if loc != ["/oauth2/start?rd=%2F"]:
                        raise AssertionError("NGINX login redirect must remain relative")
                print(f"PASS real-proxy+NGINX {label}: HTTP {status}, no API forwarding")
            # This is the real identity boundary, unlike the synthetic 202
            # positive mock. Positive user login requires authorized operator.
            status, headers = http_get(gateway_port, "/oauth2/start?rd=%2F")
            if status != 302:
                raise AssertionError("NGINX real OAuth path must produce Google login redirect")
            loc = [v for n, v in headers if n.lower() == "location"]
            if not loc or not loc[0].startswith("https://accounts.google.com/"):
                raise AssertionError("NGINX real OAuth path lost Google's HTTPS destination")
            print("PASS NGINX forwards real OAuth2 Proxy login endpoint")
            print("PASS: 8 live-binary, synthetic-credential cases; NO real Google login or public route")
        finally:
            stop(nginx_proc)
            stop(oauth_proc)
            for service, thread in service_handles:
                service.shutdown()
                service.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for k in ("oauth2-proxy-binary", "nginx-binary", "oauth-config",
              "nginx-config", "nginx-fixture"):
        p.add_argument("--" + k, type=Path, required=True)
    opts = vars(p.parse_args())
    run(opts["oauth2_proxy_binary"], opts["nginx_binary"], opts["oauth_config"],
        opts["nginx_config"], opts["nginx_fixture"])
