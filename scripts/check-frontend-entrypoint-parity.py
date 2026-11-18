#!/usr/bin/env python3
"""Fail-closed, read-only identity parity gate for NEXOLAB frontend entrypoints.

This tool never updates services, proxy routes, hardware, configuration or data.
Endpoints must be explicit private/loopback HTTP upstreams, not public URLs.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

COMMIT = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
PRIVATE_NETS = tuple(
    ipaddress.ip_network(net)
    for net in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")
)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def parse_entrypoint(value: str) -> tuple[str, str]:
    name, sep, origin = value.partition("=")
    if not sep or not NAME.fullmatch(name):
        raise ValueError("each --entrypoint must use name=http://private-ip:port")
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or not parsed.hostname
            or parsed.port is None):
        raise ValueError(f"{name}: expected private HTTP origin with explicit port and no path")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError(f"{name}: only literal private/loopback IPs permitted") from exc
    if not any(address in network for network in PRIVATE_NETS):
        raise ValueError(f"{name}: non-private or link-local origin prohibited")
    return name, origin.rstrip("/")


def fetch_identity(origin: str, timeout: float) -> dict[str, str]:
    req = Request(origin + "/api/runtime-identity", headers={"Accept": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirects).open(req, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}, expected 200")
            raw = response.read(16385)
    except HTTPError as exc:
        raise ValueError(f"HTTP {exc.code}, expected 200") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError("upstream unavailable") from exc
    if len(raw) > 16384:
        raise ValueError("identity response exceeds size limit")
    try:
        identity = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid JSON identity") from exc
    if not isinstance(identity, dict):
        raise ValueError("identity is not an object")
    fields = ("source_commit", "build_id", "identity_source")
    values = {field: identity.get(field) for field in fields}
    if not isinstance(values["source_commit"], str) or not COMMIT.fullmatch(values["source_commit"]):
        raise ValueError("missing or invalid source_commit")
    for field in ("build_id", "identity_source"):
        if not isinstance(values[field], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", values[field]):
            raise ValueError(f"missing or invalid {field}")
    return values


def verify(entrypoints: list[tuple[str, str]], expected_source: str, timeout: float = 3.0) -> dict:
    if not COMMIT.fullmatch(expected_source):
        raise ValueError("expected source must be an exact 40-character lowercase SHA")
    if len(entrypoints) < 2:
        raise ValueError("at least two entrypoints required")
    names = [name for name, _ in entrypoints]
    if len(set(names)) != len(names):
        raise ValueError("entrypoint names must be unique")
    entries = []
    errors = []
    for name, origin in entrypoints:
        try:
            identity = fetch_identity(origin, timeout)
            entries.append({"name": name, **identity})
            if identity["source_commit"] != expected_source:
                errors.append(f"{name}: source differs from expected approved revision")
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            entries.append({"name": name, "identity": "unavailable"})
    builds = {item["build_id"] for item in entries if "build_id" in item}
    if len(builds) > 1:
        errors.append("entrypoints do not serve identical frontend build IDs")
    return {
        "status": "PASS" if not errors else "FAIL",
        "expected_source": expected_source,
        "entries": entries,
        "failures": errors,
        "note": "Source/build parity only; auth, API, database, offline and device enrollment require separate release evidence.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--entrypoint", action="append", required=True,
                        help="name=http://127.0.0.1:3105, repeated for each operator upstream")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0 or args.timeout > 10:
            raise ValueError("timeout must be in (0,10] seconds")
        endpoints = [parse_entrypoint(item) for item in args.entrypoint]
        report = verify(endpoints, args.expected_source, args.timeout)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
