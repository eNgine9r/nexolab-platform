#!/usr/bin/env python3
"""Read-only fail-closed local DR backup gate. Does NOT create a backup.

NEXOLAB #1460: deliberately rejects an incomplete/assumed source inventory.
A software preflight result is not site authorisation or restore acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

RESERVE_BYTES = 20 * 1024**3
MAX_LOCAL_NEW_BACKUP_BYTES = 4 * 1024**3
MANDATORY = frozenset({
    "postgresql",
    "object-storage",
    "mqtt-dynamic-security",
    "edge-sqlite",
    "local-auth-private-key",
    "local-auth-public-key",
})


class PreflightError(ValueError):
    pass


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightError("duplicate_policy_json_key")
        result[key] = value
    return result


def read_policy(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise PreflightError("policy_not_regular_file")
    if metadata.st_size > 1024 * 1024:
        raise PreflightError("policy_too_large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError("invalid_policy_json") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise PreflightError("invalid_policy_schema")
    bundle = data.get("bundle")
    if not isinstance(bundle, dict) or bundle.get("encryption") != "aes-256-gcm" or bundle.get("key_source") != "mounted_file":
        raise PreflightError("unprotected_bundle_policy")
    if not isinstance(data.get("assets"), list):
        raise PreflightError("invalid_asset_inventory")
    return data


def evaluate_policy(policy: dict[str, Any]) -> list[str]:
    problems: set[str] = set()
    seen: set[str] = set()
    for asset in policy["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str) or not asset["id"]:
            problems.add("invalid_asset_identity")
            continue
        identity = asset["id"]
        if identity in seen:
            problems.add("duplicate_asset_identity")
        seen.add(identity)
        if identity in MANDATORY and asset.get("required") is not True:
            problems.add("mandatory_asset_not_required")
        if asset.get("kind") in ("s3_bucket", "docker_volume") and not asset.get("consistency_boundary"):
            problems.add("missing_consistency_boundary")
        if identity == "object-storage" and asset.get("source_service") == "minio":
            # The legacy MinIO identity conflicts with current VersityGW
            # observations. An operator must establish the exact live source.
            problems.add("object_storage_source_authority_unreconciled")
    if not MANDATORY.issubset(seen):
        problems.add("incomplete_mandatory_inventory")
    return sorted(problems)


def check_staging(path: Path, *, reserve: int = RESERVE_BYTES, cap: int = MAX_LOCAL_NEW_BACKUP_BYTES) -> tuple[int | None, list[str]]:
    problems = []
    try:
        item = path.lstat()
        if not stat.S_ISDIR(item.st_mode) or stat.S_ISLNK(item.st_mode):
            return None, ["staging_not_regular_directory"]
        if stat.S_IMODE(item.st_mode) & 0o022:
            problems.append("staging_allows_untrusted_writes")
        free = os.statvfs(path)
        available = free.f_bavail * free.f_frsize
    except OSError:
        return None, ["staging_unavailable"]
    if available < reserve + cap:
        problems.append("insufficient_capacity_for_20gib_reserve_plus_4gib_cap")
    return available, problems


def evaluate(policy_path: Path, staging_dir: Path) -> dict[str, Any]:
    blocked = []
    try:
        blocked.extend(evaluate_policy(read_policy(policy_path)))
    except (OSError, PreflightError):
        blocked.append("policy_unreadable_or_invalid")
    available, space_blocks = check_staging(staging_dir)
    blocked.extend(space_blocks)
    # Site backup acceptance can never follow from a repository policy and
    # an available-bytes check. Off-device encryption, actual source identity,
    # consistency and isolated restore must all be independently evidenced.
    blocked.extend((
        "site_asset_authority_unverified",
        "independent_encrypted_off_device_copy_unverified",
        "isolated_restore_unverified",
        "site_activation_not_approved",
    ))
    return {
        "profile": "LOCAL_LAN",
        "status": "BLOCKED",
        "backup_performed": False,
        "restore_performed": False,
        "staging_available_bytes": available,
        "reserve_bytes": RESERVE_BYTES,
        "max_new_backup_bytes": MAX_LOCAL_NEW_BACKUP_BYTES,
        "reasons": sorted(set(blocked)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    # Strictly read-only; never open a file in write mode, create directories
    # or interact with a production service.
    report = evaluate(args.policy, args.staging_dir)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 78 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
