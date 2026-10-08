#!/usr/bin/env python3
"""Read-only readiness checks for a *dedicated-host* NEXOLAB HTTPS staging profile.

This is NOT deployment tooling. Never starts a tunnel, changes LAN ports,
refreshes authentication tokens or interacts with actual controllers.
No network requests or filesystem writes are made.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


class GateError(ValueError):
    """Non-compliant external staging profile."""


def _url(value: object, key: str, scheme: str) -> tuple[str, int | None, str]:
    if not isinstance(value, str):
        raise GateError(f"{key} must be a URL string")
    p = urlsplit(value)
    if (
        p.scheme != scheme
        or not p.hostname
        or p.username is not None
        or p.password is not None
        or p.query
        or p.fragment
        or p.path not in ("", "/")
    ):
        raise GateError(f"{key} must be an absolute {scheme} origin without credentials, paths or query")
    try:
        port = p.port
    except ValueError as err:
        raise GateError(f"{key} has an invalid port") from err
    return p.hostname.lower(), port, p.scheme


def _public_origin(value: object) -> str:
    hostname, port, _ = _url(value, "public_origin", "https")
    if port is not None and port != 443:
        raise GateError("the external origin must use standard HTTPS port 443")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise GateError("the external hostname must not be localhost")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname or hostname.endswith(".local"):
            raise GateError("public hostname must be a resolvable DNS name")
    else:
        raise GateError("external origin must use a DNS name rather than a literal IP")
    return f"https://{hostname}"


def _loopback(value: object, key: str, port: int) -> None:
    hostname, actual_port, _ = _url(value, key, "http")
    if hostname not in ("127.0.0.1", "localhost", "::1") or actual_port != port:
        raise GateError(f"{key} must remain on loopback port {port}")


def _private_api(value: object) -> None:
    hostname, port, _ = _url(value, "private_api_origin", "http")
    if port != 8082:
        raise GateError("private API must use its existing controlled port 8082")
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError as err:
        if hostname != "localhost":
            raise GateError("private API must use a concrete private IP or loopback") from err
    else:
        if not (ip.is_private or ip.is_loopback):
            raise GateError("private API cannot point to a public internet IP")


def validate(profile: dict[str, object]) -> None:
    """Fail closed on unknown schema, unsafe origins and missing identity barriers."""
    required = {
        "profile",
        "public_origin",
        "api_base_url",
        "websocket_url",
        "frontend_origin",
        "private_api_origin",
        "gateway_origin",
        "identity_gateway_origin",
        "frontend_auth_provider",
        "backend_auth_mode",
        "backend_local_auth",
        "dedicated_hostname",
        "named_identity_allowlist",
        "identity_mfa",
        "dashboard_rbac",
        "direct_wan_port_forwarding",
        "public_route_enabled",
        "object_storage_externally_exposed",
        "object_storage_browser_support",
        "modbus_writes_enabled",
        "company_it_approval_recorded",
    }
    missing, unknown = required - profile.keys(), profile.keys() - required
    if missing or unknown:
        raise GateError(f"manifest schema mismatch (missing={sorted(missing)}, unknown={sorted(unknown)})")
    if profile["profile"] != "isolated_external_stage":
        raise GateError("external staging must use the isolated staging profile")

    origin = _public_origin(profile["public_origin"])
    api_host, api_port, _ = _url(profile["api_base_url"], "api_base_url", "https")
    if f"https://{api_host}" != origin or api_port not in (None, 443):
        raise GateError("API must use the exact same HTTPS origin as the browser")

    ws = urlsplit(str(profile["websocket_url"]))
    if (
        ws.scheme != "wss"
        or ws.netloc.lower() != urlsplit(origin).netloc.lower()
        or ws.path != "/api/v1/telemetry/live"
        or ws.username is not None
        or ws.password is not None
        or ws.query
        or ws.fragment
    ):
        raise GateError("WebSocket must use the exact public WSS origin and approved telemetry path")

    _loopback(profile["frontend_origin"], "frontend_origin", 3100)
    _loopback(profile["gateway_origin"], "gateway_origin", 18790)
    _loopback(profile["identity_gateway_origin"], "identity_gateway_origin", 4180)
    _private_api(profile["private_api_origin"])

    for key in ("dedicated_hostname", "named_identity_allowlist", "identity_mfa", "dashboard_rbac", "backend_local_auth"):
        if profile[key] is not True:
            raise GateError(f"{key} must be enabled")

    if profile["frontend_auth_provider"] != "local" or profile["backend_auth_mode"] != "jwt":
        raise GateError("local JWT and server-side RBAC must stay enabled")

    for key in ("direct_wan_port_forwarding", "public_route_enabled", "object_storage_externally_exposed", "modbus_writes_enabled"):
        if profile[key] is not False:
            raise GateError(f"{key} must remain disabled in staging")

    if profile["object_storage_browser_support"] != "blocked_pending_proxy":
        raise GateError("object storage is not accepted for external browsers until authorized proxy is tested")

    # Stage may be prepared without corporate IT approval, but its absence is
    # a hard public GO-LIVE blocker, independent from this dry-run gate.
    if type(profile["company_it_approval_recorded"]) is not bool:
        raise GateError("company_it_approval_recorded must be boolean")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise GateError("manifest must contain a JSON object")
        validate(profile)
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1

    print("PASS: source-only HTTPS staging profile passes the basic fail-closed policy checks")
    print("PUBLICATION=BLOCKED: identity provider, image path, live endpoint RBAC, MFA, staging E2E and IT approval not verified")
    print("NO DEVICES TOUCHED; NO TUNNEL ENABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
