#!/usr/bin/env python3
"""Read-only, fail-closed NEXOLAB Docker/containerd host-package guard (#1421).

APT holds do NOT prove immutable package authority, stop privileged dpkg
overrides, fix broken Docker networking, or authorize any site operation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable

PACKAGES = (
    "docker-ce",
    "docker-ce-cli",
    "containerd.io",
    "docker-compose-plugin",
    "docker-buildx-plugin",
    "docker-ce-rootless-extras",
)
MAX_OUTPUT_BYTES = 32768
# Debian allows an epoch (e.g. 5:29.9.2-1~debian), not whitespace/control chars.
VERSION = re.compile(r"^[0-9][a-zA-Z0-9.+:~\\-]{0,119}$")
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,127}$")


class PackagePolicyError(RuntimeError):
    """APT inventories are unavailable, ambiguous or inconsistent."""


def run_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, check=True, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackagePolicyError("local_package_inventory_unavailable") from exc
    if len(result.stdout) > MAX_OUTPUT_BYTES:
        raise PackagePolicyError("local_package_inventory_oversized")
    return result.stdout


def inspect(command: Callable[[list[str]], str] = run_command) -> dict[str, object]:
    held_output = command(["apt-mark", "showhold"])
    if len(held_output) > MAX_OUTPUT_BYTES:
        raise PackagePolicyError("oversized_apt_hold_inventory")
    held = held_output.splitlines()
    if any(not PACKAGE.fullmatch(item) for item in held):
        raise PackagePolicyError("invalid_apt_hold_inventory")
    if len(set(held)) != len(held):
        raise PackagePolicyError("duplicate_apt_hold_inventory")
    hold_set = set(held)

    raw = command([
        "dpkg-query",
        "-W",
        "-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n",
        *PACKAGES,
    ])
    if not raw or len(raw) > MAX_OUTPUT_BYTES:
        raise PackagePolicyError("missing_or_oversized_dpkg_inventory")
    installed: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            raise PackagePolicyError("invalid_dpkg_package_inventory")
        package, version, status = parts
        if package not in PACKAGES or package in installed:
            raise PackagePolicyError("missing_or_unexpected_container_runtime_package")
        if not VERSION.fullmatch(version):
            raise PackagePolicyError("invalid_protected_package_version")
        # dpkg status abbreviation: Desired (i=install, h=hold), Status
        # (i=installed), Error (blank=none). A mere available version is
        # never sufficient; rc/unpacked/half-configured is NOT installed.
        if status not in ("ii ", "hi "):
            raise PackagePolicyError("protected_package_not_fully_installed")
        if (status == "hi ") != (package in hold_set):
            raise PackagePolicyError("contradictory_apt_dpkg_hold_state")
        installed[package] = version
    if set(installed) != set(PACKAGES):
        raise PackagePolicyError("missing_or_unexpected_container_runtime_package")

    unprotected = [package for package in PACKAGES if package not in hold_set]
    return {
        "status": "guarded" if not unprotected else "unprotected",
        "profile": "LOCAL_LAN",
        "read_only": True,
        "mutation_performed": False,
        "packages": [
            {"name": package, "version": installed[package], "held": package in hold_set}
            for package in PACKAGES
        ],
        "unprotected": unprotected,
        "immutable_runtime_authority": "unverified",
        "runtime_site_health": "unverified",
        "caveat": "APT holds are not proof of release authority, site backup or network health",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only host package policy audit")
    parser.parse_args(argv)
    try:
        report = inspect()
    except PackagePolicyError:
        report = {
            "status": "blocked",
            "reason": "protected_package_inventory_unavailable_or_inconsistent",
            "read_only": True,
            "mutation_performed": False,
            "immutable_runtime_authority": "unverified",
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "guarded" else 78


if __name__ == "__main__":
    sys.exit(main())
