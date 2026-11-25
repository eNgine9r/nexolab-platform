#!/usr/bin/env python3
"""NEXOLAB #1466: bounded read-only original LOCAL_LAN login-path probe.

This validates only an unauthenticated browser *entry path*, not owner login,
browser JavaScript completion, fresh hardware samples or system recovery.
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import sys
from typing import Any, Callable

FRONTEND_PORT = 3000
API_PORT = 8082
MAX_BODY = 65536
PRIVATE_RANGES = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
))
READY_VALUE = "LOCAL_LAN_AUTH_PATH_REACHABLE"


class ProbeBlocked(ValueError):
    """Fixed diagnostic reason only; do not expose remote response text."""


def verify_host(host: str) -> str:
    if len(host) > 45 or not re.fullmatch(r"[0-9.]{7,15}", host):
        raise ProbeBlocked("literal_private_ipv4_required")
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as exc:
        raise ProbeBlocked("literal_private_ipv4_required") from exc
    if not any(address in network for network in PRIVATE_RANGES):
        raise ProbeBlocked("site_lan_or_loopback_only")
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ProbeBlocked("unsafe_ip_address")
    return str(address)


def request(
    host: str, port: int, path: str, *,
    timeout: float,
    origin: str | None = None,
    connection_factory: Callable[..., Any] = http.client.HTTPConnection,
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Fixed GET request; no DNS, redirects, cookies, passwords or proxy."""
    conn = connection_factory(host, port, timeout=timeout)
    try:
        headers = {"Accept": "application/json" if port == API_PORT else "text/html"}
        if origin is not None:
            headers["Origin"] = origin
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ProbeBlocked("response_body_exceeds_bound")
        return response.status, response.getheaders(), body
    except (OSError, http.client.HTTPException, TimeoutError) as exc:
        raise ProbeBlocked("required_local_endpoint_unreachable") from exc
    finally:
        conn.close()


def one_header(headers: list[tuple[str, str]], name: str) -> str | None:
    matches = [v.strip() for k, v in headers if k.lower() == name.lower()]
    if len(matches) != 1:
        return None
    return matches[0]


def evaluate(
    host: str, *,
    frontend_port: int = FRONTEND_PORT,
    api_port: int = API_PORT,
    timeout: float = 3.0,
    fetch: Callable[..., tuple[int, list[tuple[str, str]], bytes]] = request,
) -> dict[str, Any]:
    result = {
        "status": "BLOCKED",
        "checks": {
            "dashboard": False,
            "login_form": False,
            "api_readiness": False,
            "unauthenticated_session_protected": False,
            "exact_lan_cors": False,
        },
        "read_only": True,
        "browser_login_verified": False,
        "live_telemetry_verified": False,
        "hardware_verified": False,
        "site_mutation": False,
    }
    try:
        canonical = verify_host(host)
        if frontend_port != FRONTEND_PORT and frontend_port not in range(1024, 65536):
            raise ProbeBlocked("invalid_fixture_port")
        if api_port != API_PORT and api_port not in range(1024, 65536):
            raise ProbeBlocked("invalid_fixture_port")
        if not 0 < timeout <= 10:
            raise ProbeBlocked("invalid_bounded_timeout")
        origin = f"http://{canonical}:{frontend_port}"

        status, headers, body = fetch(canonical, frontend_port, "/", timeout=timeout)
        if status != 200 or not (one_header(headers, "Content-Type") or "").lower().startswith("text/html"):
            raise ProbeBlocked("dashboard_unavailable_or_not_html")
        if b"<html" not in body.lower() or b"NEXOLAB" not in body.upper():
            raise ProbeBlocked("dashboard_identity_unverified")
        result["checks"]["dashboard"] = True

        status, headers, body = fetch(canonical, frontend_port, "/login", timeout=timeout)
        if status != 200 or not (one_header(headers, "Content-Type") or "").lower().startswith("text/html"):
            raise ProbeBlocked("login_page_unavailable_or_not_html")
        if b"NEXOLAB" not in body.upper() or b"password" not in body.lower():
            raise ProbeBlocked("login_form_not_rendered")
        result["checks"]["login_form"] = True

        status, headers, body = fetch(canonical, api_port, "/health/ready", timeout=timeout)
        if status != 200 or not (one_header(headers, "Content-Type") or "").lower().startswith("application/json"):
            raise ProbeBlocked("session_api_not_ready")
        try:
            data = json.loads(body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProbeBlocked("api_readiness_invalid_json") from exc
        if not isinstance(data, dict) or not all(data.get(k) == "ready" for k in ("status", "database", "mqtt")):
            raise ProbeBlocked("api_or_dependencies_not_ready")
        result["checks"]["api_readiness"] = True

        status, headers, _ = fetch(
            canonical, api_port, "/api/v1/auth/session", timeout=timeout, origin=origin
        )
        if status != 401:
            raise ProbeBlocked("session_auth_expected_401")
        result["checks"]["unauthenticated_session_protected"] = True
        if one_header(headers, "Access-Control-Allow-Origin") != origin:
            raise ProbeBlocked("session_origin_not_explicitly_authorized")
        result["checks"]["exact_lan_cors"] = True
        result["status"] = READY_VALUE
    except ProbeBlocked as exc:
        result["reason"] = str(exc)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--host", required=True, help="explicit private literal IPv4, e.g. lab LAN")
    parser.add_argument("--timeout", type=float, default=3.0, help="1-10 seconds per check")
    args = parser.parse_args(argv)
    result = evaluate(args.host, timeout=args.timeout)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == READY_VALUE else 78


if __name__ == "__main__":
    sys.exit(main())
