#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_METRICS_BYTES = 1_048_576


def read_metrics(path: Path) -> bytes:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("metrics textfile must be a regular non-symlink file")
    if metadata.st_size > MAX_METRICS_BYTES:
        raise ValueError("metrics textfile exceeds the size limit")
    content = path.read_bytes()
    if b"\x00" in content:
        raise ValueError("metrics textfile contains a NUL byte")
    if content and not content.endswith(b"\n"):
        content += b"\n"
    return content


class Handler(BaseHTTPRequestHandler):
    server: "MetricsServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _write(self, status: HTTPStatus, content: bytes, media_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path == "/health":
            try:
                read_metrics(self.server.metrics_path)
            except (OSError, ValueError) as error:
                self._write(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    (str(error) + "\n").encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
                return
            self._write(
                HTTPStatus.OK,
                b'{"status":"ok"}\n',
                "application/json; charset=utf-8",
            )
            return
        if self.path == "/metrics":
            try:
                content = read_metrics(self.server.metrics_path)
            except (OSError, ValueError) as error:
                self._write(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    (str(error) + "\n").encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
                return
            self._write(
                HTTPStatus.OK,
                content,
                "text/plain; version=0.0.4; charset=utf-8",
            )
            return
        self._write(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8")


class MetricsServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], metrics_path: Path) -> None:
        super().__init__(address, Handler)
        self.metrics_path = metrics_path


def main() -> int:
    host = os.getenv("NEXOLAB_TEXTFILE_HOST", "0.0.0.0")
    port = int(os.getenv("NEXOLAB_TEXTFILE_PORT", "9109"))
    path = Path(
        os.getenv(
            "NEXOLAB_TEXTFILE_PATH",
            "/var/lib/nexolab-observability/disaster-recovery.prom",
        )
    )
    MetricsServer((host, port), path).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
