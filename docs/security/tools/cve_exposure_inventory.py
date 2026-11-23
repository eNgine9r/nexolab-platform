#!/usr/bin/env python3
"""Exposure inventory for an OpenSSL QUIC-server CVE in one exported container image.

Used by .github/workflows/cve-exposure-evidence.yml (and reproducible by hand):

    docker create --name x IMAGE && docker export x -o image.tar
    docker inspect IMAGE > inspect.json
    trivy image --format json -o trivy.json IMAGE
    python3 -I cve_exposure_inventory.py --cve CVE-2026-124709 --image-id device-agent \
        --arch arm64 --export image.tar --inspect inspect.json --trivy trivy.json --output summary.json

Read-only: it only reads the three input files and writes one JSON summary.
It reports
- the installed OpenSSL Debian packages (dpkg ``status`` or distroless ``status.d``),
- every ELF that links libssl/libcrypto and whether it references the QUIC
  server/listener API (only ``libssl.so`` itself is expected to),
- exposed ports (UDP would matter for QUIC) and the runtime user,
- every Trivy finding, with the rows for the requested CVE and all HIGH/CRITICAL.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Iterable

QUIC_SERVER_API = (
    b"SSL_new_listener",
    b"SSL_new_listener_from",
    b"SSL_accept_connection",
    b"SSL_listen",
    b"OSSL_QUIC_server_method",
    b"SSL_new_domain",
    b"SSL_accept_stream",
)
OPENSSL_PACKAGES = ("libssl3t64", "libssl3", "openssl", "openssl-provider-legacy")
MAX_ELF_BYTES = 400_000_000


def _parse_dpkg_status(text: str) -> dict[str, str]:
    packages: dict[str, str] = {}
    name = version = None
    for line in [*text.splitlines(), ""]:
        if not line.strip():
            if name and version:
                packages[name] = version
            name = version = None
        elif line.startswith("Package:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
    return packages


def inspect_export(path: Path) -> dict[str, Any]:
    packages: dict[str, str] = {}
    consumers: list[dict[str, Any]] = []
    with tarfile.open(path, "r|*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            if name == "var/lib/dpkg/status" or name.startswith("var/lib/dpkg/status.d/"):
                handle = archive.extractfile(member)
                if handle is not None and member.size < 50_000_000:
                    packages.update(_parse_dpkg_status(handle.read().decode("utf-8", "replace")))
                continue
            if member.size < 64 or member.size > MAX_ELF_BYTES:
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            head = handle.read(4)
            if head != b"\x7fELF":
                continue
            data = head + handle.read()
            links_ssl = b"libssl.so" in data
            links_crypto = b"libcrypto.so" in data
            basename = name.rsplit("/", 1)[-1]
            is_openssl_library = basename.startswith(("libssl.so", "libcrypto.so", "libssl-", "libcrypto-"))
            if not (links_ssl or links_crypto or is_openssl_library):
                continue
            consumers.append(
                {
                    "path": name,
                    "kind": "openssl-library" if is_openssl_library else "libssl" if links_ssl else "libcrypto-only",
                    "quic_server_api": [symbol.decode() for symbol in QUIC_SERVER_API if symbol in data],
                }
            )
    consumers.sort(key=lambda row: row["path"])
    return {
        "openssl_packages": {name: packages[name] for name in OPENSSL_PACKAGES if name in packages},
        "libssl_consumers": consumers,
        "quic_server_api_outside_openssl_libraries": [
            row["path"] for row in consumers if row["quic_server_api"] and row["kind"] != "openssl-library"
        ],
    }


def inspect_config(inspect: Any) -> dict[str, Any]:
    entry = inspect[0] if isinstance(inspect, list) and inspect else inspect
    config = (entry or {}).get("Config") or {}
    ports = sorted((config.get("ExposedPorts") or {}).keys())
    return {
        "exposed_ports": ports,
        "udp_ports": [port for port in ports if port.endswith("/udp")],
        "user": config.get("User") or "root",
        "architecture": (entry or {}).get("Architecture"),
        "os": (entry or {}).get("Os"),
    }


def _findings(report: Any) -> Iterable[dict[str, Any]]:
    for result in (report or {}).get("Results") or []:
        for vulnerability in result.get("Vulnerabilities") or []:
            yield {
                "id": vulnerability.get("VulnerabilityID"),
                "package": vulnerability.get("PkgName"),
                "installed": vulnerability.get("InstalledVersion"),
                "fixed": vulnerability.get("FixedVersion") or None,
                "severity": vulnerability.get("Severity"),
                "target": result.get("Target"),
                "class": result.get("Class"),
            }


def summarize_trivy(report: Any, cve: str) -> dict[str, Any]:
    findings = list(_findings(report))
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"] or "UNKNOWN"] = counts.get(finding["severity"] or "UNKNOWN", 0) + 1
    return {
        "os": " ".join(
            str(value)
            for value in (((report or {}).get("Metadata") or {}).get("OS") or {}).values()
            if value
        )
        or None,
        "total_findings": len(findings),
        "severity_counts": dict(sorted(counts.items())),
        "cve_rows": [finding for finding in findings if finding["id"] == cve],
        "high_critical": sorted(
            (finding for finding in findings if finding["severity"] in {"HIGH", "CRITICAL"}),
            key=lambda finding: (finding["severity"], finding["id"] or "", finding["package"] or ""),
        ),
    }


def build_summary(*, cve: str, image_id: str, arch: str, export: Path, inspect: Any, trivy: Any) -> dict[str, Any]:
    exported = inspect_export(export)
    config = inspect_config(inspect)
    trivy_summary = summarize_trivy(trivy, cve)
    return {
        "cve": cve,
        "image_id": image_id,
        "arch": arch,
        **config,
        **exported,
        "trivy": trivy_summary,
        "assessment": {
            "affected_package_present": bool(trivy_summary["cve_rows"]),
            "fix_available": any(row["fixed"] for row in trivy_summary["cve_rows"]),
            "quic_server_api_used_outside_openssl": bool(exported["quic_server_api_outside_openssl_libraries"]),
            "udp_exposed": bool(config["udp_ports"]),
            "other_high_critical": [
                f"{row['severity']} {row['id']} {row['package']} {row['installed']}"
                for row in trivy_summary["high_critical"]
                if row["id"] != cve
            ],
        },
    }


def markdown_row(summary: dict[str, Any]) -> str:
    rows = summary["trivy"]["cve_rows"]
    installed = ", ".join(sorted({row["installed"] for row in rows})) or "not affected"
    assessment = summary["assessment"]
    return (
        f"| {summary['image_id']} | {summary['arch']} | {summary['trivy']['os']} | {installed} | "
        f"{'yes' if assessment['fix_available'] else 'no'} | "
        f"{'YES' if assessment['quic_server_api_used_outside_openssl'] else 'no'} | "
        f"{', '.join(summary['udp_ports']) or 'none'} | {summary['trivy']['severity_counts']} | "
        f"{'; '.join(assessment['other_high_critical']) or 'none'} |"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cve", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--inspect", type=Path, required=True)
    parser.add_argument("--trivy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = build_summary(
        cve=args.cve,
        image_id=args.image_id,
        arch=args.arch,
        export=args.export,
        inspect=json.loads(args.inspect.read_text(encoding="utf-8")),
        trivy=json.loads(args.trivy.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(markdown_row(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
