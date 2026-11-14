#!/usr/bin/env python3
"""Synthetic NEXOLAB preview for an existing path-scoped Tailscale Funnel.
NO production APIs, telemetry, Modbus, devices, cookies or credentials are imported.
Serve ONLY on 127.0.0.1 behind the approved Tailscale HTTPS path.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import secrets
import stat
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PUBLIC_ORIGIN = "https://btc-radar.tail7f9b04.ts.net"
PREFIX = "/nexolab-preview/"
COOKIE_NAME = "nexolab_preview_session"
TTL_SECONDS = 1800

SHELL = """<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEXOLAB | Захищений тестовий доступ</title><style>
:root{font-family:system-ui,Arial;color-scheme:dark;background:#0d1623;color:#eef6fe}
body{max-width:720px;margin:auto;padding:32px 20px}
article{background:#18283b;border:1px solid #35516a;border-radius:18px;padding:26px}
h1{font-size:1.8rem}.badge{display:inline-block;background:#28577a;padding:8px 12px;border-radius:12px}
p{line-height:1.55;color:#cedbe7}
input{box-sizing:border-box;display:block;width:100%;background:#fff;color:#111;padding:14px;
border:0;border-radius:8px;margin:10px 0 16px;font-size:1rem}
button{background:#7bc7f7;color:#001729;padding:12px 16px;border:0;border-radius:9px;font-weight:700}
small{color:#99bbd1}
</style></head><body><span class="badge">ІЗОЛЬОВАНИЙ ТЕСТ — НЕ РОБОЧА СИСТЕМА</span>
<h1>NEXOLAB — перевірка HTTPS-доступу</h1><article>{content}</article>
<p><small>Не підключено до датчиків, бази даних, NEXUS MCP чи контролерів.</small></p></body></html>"""

FORM = """<h2>Вхід за паролем</h2><p>Для доступу введіть пароль тестової сторінки.</p>
<form method="post" action="/nexolab-preview/login" autocomplete="off">
<label for="password">Пароль</label><input id="password" name="password" type="password"
required maxlength="256" autocomplete="off"><button type="submit">Увійти</button></form>"""

PREVIEW = """<h2>HTTPS-підключення успішне</h2>
<p>Це захищена демонстраційна сторінка. Вхід через браузер та Tailscale Funnel працює.</p>
<p><strong>Тут немає реальних вимірювань, API чи дистанційного керування.</strong></p>
<form method="post" action="/nexolab-preview/logout">
<button type="submit">Вийти</button></form>"""


class PreviewHandler(BaseHTTPRequestHandler):
    server: "PreviewServer"

    def log_message(self, *args: object) -> None:
        # No cookie, password, source IP, request URL or authorization in logs.
        pass

    def respond(self, status: int, body: str, *, extra: dict[str, str] | None = None) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        for key, value in {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(encoded)),
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "X-NEXOLAB-Preview-Isolated": "yes",
            **(extra or {}),
        }.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def client_cookie(self) -> str:
        raw = self.headers.get("Cookie", "")
        if len(raw) > 4096:
            return ""
        try:
            parsed = SimpleCookie()
            parsed.load(raw)
            return parsed[COOKIE_NAME].value if COOKIE_NAME in parsed else ""
        except Exception:
            return ""

    def valid_cookie(self) -> bool:
        raw = self.client_cookie()
        parts = raw.split(".")
        if len(parts) != 3:
            return False
        expiry, nonce, signature = parts
        if not expiry.isdigit() or len(nonce) > 50 or len(signature) != 64:
            return False
        now = int(time.time())
        if int(expiry) <= now or int(expiry) > now + TTL_SECONDS:
            return False
        message = (expiry + "." + nonce).encode("ascii", errors="ignore")
        expected = hmac.new(self.server.signing_key, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    def same_origin(self) -> bool:
        # Browser form navigation may omit/rewrite Origin under privacy tooling.
        # Sec-Fetch-* are browser-controlled forbidden request headers, so a
        # same-origin navigation provides a strict fallback for Chrome.
        # Cross-site and same-site (other subdomain) requests remain denied.
        if self.headers.get("Sec-Fetch-Site", "") == "same-origin":
            return self.headers.get("Sec-Fetch-Mode", "") == "navigate" and self.headers.get("Sec-Fetch-Dest", "") == "document"
        return self.headers.get("Origin", "") == PUBLIC_ORIGIN

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path not in ("/", PREFIX[:-1], PREFIX):
            self.respond(404, "Not found")
        elif not self.valid_cookie():
            self.respond(200, SHELL.replace("{content}", FORM))
        else:
            self.respond(200, SHELL.replace("{content}", PREVIEW))

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in ("/login", PREFIX + "login", "/logout", PREFIX + "logout"):
            self.respond(404, "Not found")
            return
        if not self.same_origin():
            self.respond(403, "Forbidden")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.respond(400, "Bad request")
            return
        if not 0 <= size <= 2048:
            self.respond(413, "Too large")
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            self.respond(415, "Unsupported media type")
            return
        body = parse_qs(self.rfile.read(size).decode("utf-8", errors="replace"))
        if path.endswith("logout"):
            self.respond(303, "", extra={"Location": PREFIX, "Set-Cookie": f"{COOKIE_NAME}=; Path={PREFIX}; Max-Age=0; HttpOnly; Secure; SameSite=Strict"})
            return
        now = time.monotonic()
        self.server.failures = [t for t in self.server.failures if now - t < 300]
        if len(self.server.failures) >= 10:
            self.respond(429, "Please try again later")
            return
        supplied = body.get("password", [""])[0]
        if not hmac.compare_digest(supplied, self.server.password):
            self.server.failures.append(now)
            self.respond(403, SHELL.replace("{content}", FORM + "<p>Невірний пароль.</p>"))
            return
        expiry = str(int(time.time()) + TTL_SECONDS)
        nonce = secrets.token_urlsafe(16)
        payload = expiry + "." + nonce
        signature = hmac.new(self.server.signing_key, payload.encode("ascii"), hashlib.sha256).hexdigest()
        cookie = f"{COOKIE_NAME}={payload}.{signature}; Path={PREFIX}; Max-Age={TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict"
        self.respond(303, "", extra={"Location": PREFIX, "Set-Cookie": cookie})

    def do_PUT(self) -> None:
        self.respond(405, "Method not allowed")

    def do_PATCH(self) -> None:
        self.respond(405, "Method not allowed")

    def do_DELETE(self) -> None:
        self.respond(405, "Method not allowed")


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], password: str):
        super().__init__(addr, PreviewHandler)
        self.password = password
        self.signing_key = secrets.token_bytes(32)
        self.failures: list[float] = []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18787)
    args = parser.parse_args()
    mode = stat.S_IMODE(args.password_file.stat().st_mode)
    if mode & 0o077:
        parser.error("password file must not be readable by group or other users")
    password = args.password_file.read_text(encoding="utf-8").strip()
    if len(password) < 32:
        parser.error("preview password must contain at least 32 characters")
    if not 1024 <= args.port <= 65535:
        parser.error("invalid port")
    server = PreviewServer(("127.0.0.1", args.port), password)
    print(f"ISOLATED_PREVIEW_READY port={args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
