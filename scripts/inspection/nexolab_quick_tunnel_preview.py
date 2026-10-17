#!/usr/bin/env python3
"""Isolated, loopback-only NEXOLAB connectivity preview.

This contains NO real NEXOLAB API, telemetry, credentials, or hardware controls.
NEVER forward the production dashboard, telemetry API, or device agent through a Quick Tunnel.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXOLAB | Isolated Tunnel Preview</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif}
body{background:#0d1623;color:#edf5fc;margin:0;padding:28px;max-width:760px}
h1{font-size:2rem;margin-bottom:6px}.pill{display:inline-block;padding:7px 11px;
border-radius:12px;background:#324e62;color:#fff;font-weight:700}
article{background:#182638;border:1px solid #2e4356;border-radius:18px;padding:26px;margin-top:24px}
p{line-height:1.55;color:#c9d9e6}a{color:#7bc1ff}
</style></head>
<body>
<div class="pill">ISOLATED PREVIEW / NO REAL DEVICES</div>
<h1>NEXOLAB — HTTPS connectivity check</h1>
<article>
<h2>З'єднання із тестовим стендом працює</h2>
<p>Це ізольована демонстраційна сторінка для перевірки Cloudflare Quick Tunnel
та входу за одноразовим email-кодом.</p>
<p><strong>Реальних показників, історії випробувань, логінів NEXOLAB,
API та керування обладнанням тут немає.</strong></p>
<p>Після перевірки браузерного доступу окремо потрібні аудит і приймання
повного HTTPS/WSS-застосунку, згода власника та корпоративного IT.</p>
</article>
</body></html>""".encode("utf-8")


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid recording visitor emails, cookies, IPs or bearer tokens.
        return

    def send_content(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_content(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/healthz":
            self.send_content(200, b"preview-only\n")
        else:
            self.send_content(404, b"not found\n")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        self.send_content(405, b"method not allowed\n")

    def do_PUT(self) -> None:
        self.send_content(405, b"method not allowed\n")

    def do_DELETE(self) -> None:
        self.send_content(405, b"method not allowed\n")

    def do_PATCH(self) -> None:
        self.send_content(405, b"method not allowed\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-only NEXOLAB Quick Tunnel demo fixture")
    parser.add_argument("--port", type=int, default=18787)
    args = parser.parse_args()
    if not (1024 <= args.port <= 65535):
        parser.error("port must be between 1024 and 65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    server.daemon_threads = True
    print(f"Demo-only loopback origin: http://127.0.0.1:{args.port}/", flush=True)
    print("No real NEXOLAB components are connected. Ctrl+C stops this fixture.", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
