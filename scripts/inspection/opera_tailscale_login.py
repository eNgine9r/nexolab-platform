#!/usr/bin/env python3
"""Socket-activated, read-only Opera/Tailscale inspection login helper."""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import secrets
import socket
import socketserver
import stat
import struct
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Mapping
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

CONFIG_ENV = "NEXOLAB_INSPECTION_CONFIG"
SYSTEMD_LISTEN_FD = 3
ROOT_UID = 0
MAX_RESPONSE_BYTES = 256 * 1024
LOGIN_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class InspectionConfig:
    expected_user: str
    expected_client_ip: str
    expected_host: str
    credential_file: Path
    login_url: str
    redirect_path: str = "/"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _required_string(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def validate_private_file(path: Path, expected_uid: int) -> None:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path} must be a regular file")
    if metadata.st_uid != expected_uid:
        raise ValueError(f"{path} must be owned by the helper user")
    if metadata.st_mode & 0o077:
        raise ValueError(f"{path} must not be group/world accessible")


def validate_local_login_url(login_url: str, expected_host: str | None = None) -> None:
    parsed = urlsplit(login_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("login_url must be an absolute HTTP(S) URL")
    if parsed.hostname == "localhost":
        return
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.scheme != "https":
            raise ValueError("non-loopback login_url must use HTTPS")
        if not expected_host or parsed.netloc != expected_host:
            raise ValueError("HTTPS login_url hostname must match expected_host")
        return
    private_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    if address.is_loopback:
        return
    if not any(address in network for network in private_networks):
        raise ValueError("login_url host must be loopback or RFC1918 private")
    if parsed.scheme != "https":
        raise ValueError("non-loopback login_url must use HTTPS")


def load_config(path: Path) -> InspectionConfig:
    validate_private_file(path, os.geteuid())
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("inspection config root must be an object")
    redirect_path = str(document.get("redirect_path", "/")).strip()
    if not redirect_path.startswith("/") or redirect_path.startswith("//"):
        raise ValueError("redirect_path must be a local absolute path")
    expected_host = _required_string(document, "expected_host")
    login_url = _required_string(document, "login_url")
    validate_local_login_url(login_url, expected_host)
    return InspectionConfig(
        expected_user=_required_string(document, "expected_user"),
        expected_client_ip=_required_string(document, "expected_client_ip"),
        expected_host=expected_host,
        credential_file=Path(_required_string(document, "credential_file")),
        login_url=login_url,
        redirect_path=redirect_path,
    )


def last_forwarded_ip(value: str | None) -> str | None:
    if value is None:
        return None
    parts = [item.strip() for item in value.split(",") if item.strip()]
    return parts[-1] if parts else None


def headers_authorized(headers: Mapping[str, str], config: InspectionConfig) -> bool:
    return (
        headers.get("tailscale-user-login") == config.expected_user
        and last_forwarded_ip(headers.get("x-forwarded-for")) == config.expected_client_ip
        and headers.get("x-forwarded-proto") == "https"
        and headers.get("x-forwarded-host") == config.expected_host
    )


def load_credential(path: Path) -> dict[str, str]:
    validate_private_file(path, os.geteuid())
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("credential root must be an object")
    username = _required_string(document, "username")
    password = _required_string(document, "password")
    return {"username": username, "password": password}


def exchange_tokens(config: InspectionConfig) -> TokenPair:
    credential = load_credential(config.credential_file)
    body = json.dumps(credential, separators=(",", ":")).encode("utf-8")
    request = urlrequest.Request(
        config.login_url,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(request, timeout=LOGIN_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError) as exc:
        raise RuntimeError("inspection login exchange failed") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeError("inspection login response exceeded the size limit")
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise RuntimeError("inspection login response must be an object")
    access_token = _required_string(document, "access_token")
    refresh_token = _required_string(document, "refresh_token")
    expires_in = document.get("expires_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise RuntimeError("inspection login response has invalid expires_in")
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


def build_session_html(tokens: TokenPair, redirect_path: str) -> tuple[bytes, str]:
    token_payload = json.dumps(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.b64encode(token_payload).decode("ascii")
    nonce = secrets.token_urlsafe(18)
    html = f"""<!doctype html><meta charset=\"utf-8\"><script nonce=\"{nonce}\">
const t=JSON.parse(atob(\"{encoded}\"));
sessionStorage.setItem(\"nexolab.local-auth.access-token\",t.access_token);
sessionStorage.setItem(\"nexolab.local-auth.refresh-token\",t.refresh_token);
sessionStorage.setItem(\"nexolab.local-auth.access-expires-at\",String(Date.now()+t.expires_in*1000));
location.replace({json.dumps(redirect_path)});
</script>"""
    return html.encode("utf-8"), nonce


def peer_uid(connection: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    except OSError:
        return None
    _pid, uid, _gid = struct.unpack("3i", raw)
    return uid


class ActivatedUnixHTTPServer(socketserver.TCPServer):
    address_family = socket.AF_UNIX

    def __init__(self, handler_class: type[socketserver.BaseRequestHandler]) -> None:
        socketserver.BaseServer.__init__(self, None, handler_class)
        self.socket = socket.fromfd(
            SYSTEMD_LISTEN_FD,
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )
        self.server_address = self.socket.getsockname()

    def server_bind(self) -> None:
        raise RuntimeError("socket activation owns the listen socket")

    def server_activate(self) -> None:
        raise RuntimeError("socket activation owns the listen socket")

    def verify_request(self, request: socket.socket, client_address: object) -> bool:
        del client_address
        return peer_uid(request) == ROOT_UID

    def server_close(self) -> None:
        self.socket.close()


def _config_from_environment() -> InspectionConfig:
    path = os.environ.get(CONFIG_ENV)
    if not path:
        raise RuntimeError(f"{CONFIG_ENV} is required")
    return load_config(Path(path))


class InspectionLoginHandler(BaseHTTPRequestHandler):
    server_version = "NEXOLABInspection/1"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _write(self, status: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        config = _config_from_environment()
        if urlsplit(self.path).path not in {"/", "/inspection-login"}:
            self._write(404, b"Not found", "text/plain; charset=utf-8")
            return
        if not headers_authorized(self.headers, config):
            self._write(403, b"Inspection access denied", "text/plain; charset=utf-8")
            return
        try:
            tokens = exchange_tokens(config)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
            self._write(503, b"Inspection login unavailable", "text/plain; charset=utf-8")
            return
        body, nonce = build_session_html(tokens, config.redirect_path)
        self._write(
            200,
            body,
            "text/html; charset=utf-8",
            Content_Security_Policy=(
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
        )


def validate_systemd_socket_activation() -> None:
    listen_pid = os.environ.get("LISTEN_PID")
    listen_fds = os.environ.get("LISTEN_FDS")
    if listen_pid != str(os.getpid()) or listen_fds != "1":
        raise RuntimeError("exactly one systemd socket-activation file descriptor is required")


def main() -> int:
    validate_systemd_socket_activation()
    _config_from_environment()
    with ActivatedUnixHTTPServer(InspectionLoginHandler) as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
