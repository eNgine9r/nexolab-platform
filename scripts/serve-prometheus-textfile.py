#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import stat
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_METRICS_BYTES = 1_048_576


def _read_file(path: Path, maximum: int) -> bytes:
    # O_NOFOLLOW + fstat protects a concurrent symlink swap between check/read,
    # including for directory mode. Default legacy file mode stays supported.
    try:
        handle = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError("metrics file cannot be safely opened") from error
    try:
        metadata = os.fstat(handle)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("metrics textfile must be regular")
        if metadata.st_size > maximum:
            raise ValueError("metrics textfile exceeds the size limit")
        content = os.read(handle, maximum + 1)
    finally:
        os.close(handle)
    if len(content) > maximum or b"\x00" in content:
        raise ValueError("metrics textfile content is unsafe")
    return content + (b"\n" if content and not content.endswith(b"\n") else b"")


def read_metrics(path: Path) -> bytes:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("metrics path must not be a symlink")
    # Default legacy single-file mode is kept byte-for-byte compatible.
    if stat.S_ISREG(metadata.st_mode):
        return _read_file(path, MAX_METRICS_BYTES)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("metrics path must be a file or directory")
    names = sorted(entry for entry in path.iterdir() if entry.suffix == ".prom")
    if not names or len(names) > 32:
        raise ValueError("metrics directory has no files or too many files")
    content = bytearray()
    for entry in names:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.prom", entry.name) is None:
            raise ValueError("metrics filename not allowlisted")
        # Deliberately fail the entire scrape if even one file is unsafe.
        part = _read_file(entry, MAX_METRICS_BYTES - len(content))
        if len(content) + len(part) > MAX_METRICS_BYTES:
            raise ValueError("total metrics size limit exceeded")
        content.extend(part)
    return bytes(content)


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
