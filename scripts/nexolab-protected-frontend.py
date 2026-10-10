#!/usr/bin/env python3
"""Validate/render an existing protected frontend; never manage OAuth or Funnel."""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from urllib.parse import urlsplit


def origin_host(origin: str) -> str:
    if not re.fullmatch(r"https://[a-z0-9.-]+", origin):
        raise ValueError("protected origin must be an exact HTTPS hostname without path or port")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.netloc != parsed.hostname
            or parsed.path or parsed.query or parsed.fragment
            or not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)):
        raise ValueError("protected origin must be an exact HTTPS hostname without path or port")
    return parsed.hostname


def directives(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        if line.startswith("["):
            section = line
        elif section == "[Service]" and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key == "Environment":
                key, value = value.split("=", 1)
                key = "env:" + key
            if key in values:
                raise ValueError("duplicate frontend service directive: " + key)
            values[key] = value
    return values


def require_memory_controller() -> None:
    if "memory" not in Path("/sys/fs/cgroup/cgroup.controllers").read_text().split():
        raise ValueError("protected frontend requires the kernel cgroup v2 memory controller")


def require_candidate_port(port: int) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))


def validate(unit: str, nginx: str, origin: str, organization: str) -> None:
    host = origin_host(origin)
    values = directives(unit)
    expected = {
        "env:NEXT_PUBLIC_NEXOLAB_API_BASE_URL": origin,
        "env:NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL": f"wss://{host}/api/v1/telemetry/live",
        "env:NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER": "local",
        "env:NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID": organization,
        "env:NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE": "true",
        "env:NEXOLAB_EXTERNAL_HTTPS_STAGE": "true",
        "NoNewPrivileges": "yes", "ProtectSystem": "strict",
        "ProtectHome": "read-only", "MemoryMax": "768M", "MemorySwapMax": "0",
    }
    if any(values.get(key) != value for key, value in expected.items()):
        raise ValueError("existing frontend origin/auth/security contract differs")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", values.get("User", "")):
        raise ValueError("frontend requires a named unprivileged user")
    if values["User"] == "root" or "--hostname 127.0.0.1 --port 3100" not in values.get("ExecStart", ""):
        raise ValueError("protected frontend must bind only to loopback port 3100")
    if not re.search(r"server_name\s+" + re.escape(host) + r"\s*;", nginx):
        raise ValueError("gateway hostname differs from the artifact origin")
    if "auth_request /_nexolab_external_auth;" not in nginx or "http://127.0.0.1:3100" not in nginx:
        raise ValueError("existing gateway must retain its protected frontend upstream")


def render_unit(unit: str, release: str, node: str, api: str) -> str:
    for value in (release, node):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
            raise ValueError("frontend paths must be absolute and systemd-safe")
    parsed = urlsplit(api)
    if (not re.fullmatch(r"http://[A-Za-z0-9.:-]+", api)
            or parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("server API must be a local HTTP origin")
    replacements = {
        "WorkingDirectory": release,
        "ExecStart": f"{node} {release}/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100",
        "ReadWritePaths": release + "/.next/cache",
        "Environment=NEXOLAB_RUNTIME_IDENTITY_FILE": release + "/.nexolab-runtime-identity.json",
        "Environment=NEXOLAB_SERVER_API_BASE_URL": api,
    }
    found: set[str] = set()
    lines = []
    for line in unit.splitlines():
        match = next((key for key in replacements if line.startswith(key + "=")), None)
        if match:
            found.add(match)
            line = match + "=" + replacements[match]
        lines.append(line)
    if found != set(replacements):
        raise ValueError("existing frontend unit lacks a required replaceable directive")
    return "\n".join(lines) + "\n"


def request(port: int, path: str, host: str, *, websocket: bool = False, timeout: float = 3) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Host": host}
        if websocket:
            headers.update({"Connection": "Upgrade", "Upgrade": "websocket",
                            "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(65537)
    finally:
        connection.close()


def probe_frontend(port: int, source: str, build: str, host: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            status, body = request(port, "/api/runtime-identity", host)
            identity = json.loads(body)
            if (status == 200 and identity.get("source_commit") == source
                    and identity.get("build_id") == build and request(port, "/login", host)[0] == 200):
                return
        except (OSError, ValueError, http.client.HTTPException):
            pass
        if time.monotonic() >= deadline:
            raise ValueError("protected frontend did not prove exact source/build readiness")
        time.sleep(0.25)


def probe_gateway(host: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    paths = ("/api/v1/equipment", "/api/v1/telemetry/live", "/api/device-agent/xjp60d",
             "/api/v1/equipment/00000000-0000-0000-0000-000000000001/images/00000000-0000-0000-0000-000000000001/content", "/login")
    while True:
        try:
            for path in paths:
                status = request(18790, path, host, websocket=path == "/api/v1/telemetry/live",
                                 timeout=max(0.01, min(3, deadline - time.monotonic())))[0]
                if status != (302 if path == "/login" else 401):
                    raise ValueError("gateway browser sign-in gate did not return a redirect" if path == "/login"
                                     else "gateway did not reject an anonymous protected request")
            return
        except (OSError, http.client.HTTPException):
            # Type=simple may return before NGINX binds. Retry only transport
            # startup failures; an unsafe HTTP result is rejected immediately.
            if time.monotonic() >= deadline:
                raise ValueError("existing gateway loopback listener did not become ready") from None
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def require_gateway_active(host: str) -> None:
    result = subprocess.run(["systemctl", "is-active", "--quiet", "nexolab-external-nginx.service"],
                            check=False, capture_output=True, timeout=5)
    if result.returncode != 0:
        raise ValueError("existing protected gateway must be active before a frontend handoff")
    probe_gateway(host)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("validate", "render", "snapshot", "probe", "gateway", "gateway-active"))
    parser.add_argument("--unit", type=Path)
    parser.add_argument("--nginx", type=Path)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--organization")
    parser.add_argument("--release", type=Path)
    parser.add_argument("--node")
    parser.add_argument("--api")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--port", type=int, default=3100)
    parser.add_argument("--source")
    parser.add_argument("--build")
    parser.add_argument("--identity", type=Path)
    args = parser.parse_args()
    host = origin_host(args.origin)
    if args.action == "validate":
        require_memory_controller()
        validate(args.unit.read_text(), args.nginx.read_text(), args.origin, args.organization)
        if not args.api or f"proxy_pass {args.api};" not in args.nginx.read_text():
            raise ValueError("existing gateway API upstream differs from the selected LAN API")
    elif args.action == "render":
        args.output.write_text(render_unit(args.unit.read_text(), str(args.release), args.node, args.api))
        (args.release / ".next/cache").mkdir(exist_ok=True)
        identity = {"schema_version": "nexolab-runtime-identity-v1", "service": "dashboard",
                    "source_commit": args.source, "build_id": args.build, "deployed_at": None,
                    "identity_source": "offline_image_manifest"}
        (args.release / ".nexolab-runtime-identity.json").write_text(json.dumps(identity) + "\n")
    elif args.action == "probe":
        if args.identity:
            identity = json.loads(args.identity.read_text())
            args.source, args.build = identity["source_commit"], identity["build_id"]
        if not args.source or not args.build:
            raise ValueError("exact source/build identity is required")
        probe_frontend(args.port, args.source, args.build, host)
    elif args.action == "snapshot":
        status, body = request(args.port, "/api/runtime-identity", host)
        identity = json.loads(body)
        if (status != 200 or not re.fullmatch(r"[0-9a-f]{40}", identity.get("source_commit", ""))
                or not identity.get("build_id")):
            raise ValueError("current protected frontend identity is unverified")
        probe_frontend(args.port, identity["source_commit"], identity["build_id"], host)
        args.output.write_text(json.dumps(identity) + "\n")
    elif args.action == "gateway-active":
        require_gateway_active(host)
    else:
        probe_gateway(host)


if __name__ == "__main__":
    main()
