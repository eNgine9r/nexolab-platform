#!/usr/bin/env python3
"""Read-only, fail-closed check for unguarded NEXOLAB Docker APT packages.

This is not an installer: it never runs apt, changes holds or restarts services.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

PACKAGES = (
    "docker-ce", "docker-ce-cli", "containerd.io",
    "docker-compose-plugin", "docker-buildx-plugin", "docker-ce-rootless-extras",
)


class PackagePolicyError(RuntimeError):
    """APT inventory is incomplete or cannot be trusted."""


def run_command(args: list[str]) -> str:
    try:
        return subprocess.run(
            args, check=True, capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackagePolicyError("local_package_inventory_unavailable") from exc


def inspect(command: Callable[[list[str]], str] = run_command) -> dict[str, object]:
    held = command(["apt-mark", "showhold"]).splitlines()
    if any(not item or item.strip() != item or any(c.isspace() for c in item) for item in held):
        raise PackagePolicyError("invalid_apt_hold_inventory")
    if len(set(held)) != len(held):
        raise PackagePolicyError("duplicate_apt_hold_inventory")
    raw = command([
        "dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n", *PACKAGES,
    ])
    versions: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0] or not parts[1] or parts[0] in versions:
            raise PackagePolicyError("invalid_dpkg_package_inventory")
        versions[parts[0]] = parts[1]
    if set(versions) != set(PACKAGES):
        raise PackagePolicyError("missing_or_unexpected_container_runtime_package")
    unprotected = [pkg for pkg in PACKAGES if pkg not in held]
    return {
        "status": "guarded" if not unprotected else "unprotected",
        "read_only": True,
        "mutation_performed": False,
        "packages": [{"name": pkg, "version": versions[pkg], "held": pkg in held}
                     for pkg in PACKAGES],
        "unprotected": unprotected,
        "caveat": "APT holds are not proof of release authority or network health",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="read-only host package policy audit")
    parser.parse_args(argv)
    try:
        result = inspect()
    except PackagePolicyError as exc:
        result = {"status": "blocked", "reason": str(exc), "read_only": True,
                  "mutation_performed": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "guarded" else 2


if __name__ == "__main__":
    sys.exit(main())
