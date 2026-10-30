#!/usr/bin/env python3
"""NEXOLAB #1441: read-only offline DR observability, NEVER site readiness approval.

Missing/stale backup or systemd timer evidence is an alarm, not permission to
restart services, take backups, erase data or activate production recovery.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess

GiB = 1024 ** 3
TIMER = "nexolab-dr-backup.timer"
PROPERTIES = {"LoadState", "UnitFileState", "ActiveState", "Persistent"}
EXPECTED = {"postgresql", "object-storage", "mqtt-dynamic-security",
            "edge-sqlite-outbox", "local-auth-private-key",
            "local-auth-public-key", "central-ingestion-spool", "edge-mqtt-persistence"}
STATUS = {"BLOCKED", "UNVERIFIED", "REPORTED_OK"}


class HealthBlocked(ValueError):
    pass


def read_sanitized_receipt(path: Path) -> dict:
    try:
        st = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(st.st_mode):
            raise HealthBlocked("evidence is a symlink or non-regular file")
        if not 0 < st.st_size <= 512 * 1024 or stat.S_IMODE(st.st_mode) & 0o077:
            raise HealthBlocked("evidence size or mode is unsafe; require 0600")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HealthBlocked("protected sanitized receipt is unavailable") from exc
    if not isinstance(data, dict):
        raise HealthBlocked("receipt must be a JSON object")
    return data


def read_timer() -> dict[str, str]:
    """Exact allowlisted read-only systemctl query; no shell or service changes."""
    argv = [
        "systemctl", "show", TIMER, "--no-pager",
        *[f"--property={name}" for name in sorted(PROPERTIES)],
    ]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HealthBlocked("systemd timer metadata not available") from exc
    if result.returncode != 0 or len(result.stdout) > 2048:
        raise HealthBlocked("read-only systemd timer query failed")
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            raise HealthBlocked("invalid systemd property evidence")
        key, value = line.split("=", 1)
        if key not in PROPERTIES or key in properties or len(value) > 128:
            raise HealthBlocked("unexpected or duplicate systemd metadata")
        properties[key] = value
    if set(properties) != PROPERTIES:
        raise HealthBlocked("missing systemd timer metadata")
    return properties


def verify_structural_contract(inventory: dict) -> None:
    script = Path(__file__).with_name("validate-site-dr-inventory-v2.py")
    spec = importlib.util.spec_from_file_location("nexolab_dr_v2_validator", script)
    if spec is None or spec.loader is None:
        raise HealthBlocked("local v2 contract unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        module.validate_site_inventory(inventory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HealthBlocked("8-store inventory does not satisfy v2 contract") from exc


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HealthBlocked("inventory timestamp missing UTC")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HealthBlocked("inventory timestamp malformed") from exc
    if stamp.utcoffset() != timedelta(0):
        raise HealthBlocked("inventory timestamp must be UTC")
    return stamp


def assess(
    inventory: dict | None,
    timer: dict[str, str] | None,
    root_free_bytes: int | None,
    *,
    now: datetime | None = None,
    structural_validator=verify_structural_contract,
) -> dict:
    """Always fail closed for independent site recovery; do not treat claims as proof."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise HealthBlocked("current time lacks timezone")
    gates: dict[str, dict[str, str]] = {}

    def gate(name: str, state: str, reason: str) -> None:
        if state not in STATUS:
            raise HealthBlocked("invalid status")
        gates[name] = {"status": state, "reason": reason}

    if timer is None:
        gate("scheduler", "BLOCKED", "application backup timer evidence unavailable")
    elif set(timer) != PROPERTIES:
        gate("scheduler", "BLOCKED", "incomplete timer metadata")
    elif (timer["LoadState"], timer["UnitFileState"], timer["ActiveState"], timer["Persistent"]) != (
        "loaded", "enabled", "active", "yes"
    ):
        gate("scheduler", "BLOCKED", "required persistent application backup timer not enabled and active")
    else:
        gate("scheduler", "REPORTED_OK", "timer installed, enabled and active; successful backup NOT proven")

    if type(root_free_bytes) is not int or root_free_bytes < 20 * GiB:
        gate("root_headroom", "BLOCKED", "20 GiB protected root free reserve not proven")
    else:
        gate("root_headroom", "REPORTED_OK", "root free reserve observed; staging budget separately required")

    if inventory is None:
        gate("multi_store_inventory", "BLOCKED", "complete eight-store v2 receipt unavailable")
        gate("backup_freshness", "BLOCKED", "last complete encrypted capture unverified")
    else:
        try:
            structural_validator(inventory)
            assets = inventory.get("assets")
            if not isinstance(assets, list):
                raise HealthBlocked("asset receipt list missing")
            names = [asset.get("id") for asset in assets if isinstance(asset, dict)]
            if len(names) != len(EXPECTED) or set(names) != EXPECTED:
                raise HealthBlocked("partial or duplicate eight-store evidence")
            gate("multi_store_inventory", "UNVERIFIED", "v2 receipt structurally valid; real contents and custody not independently checked")
            observed_at = parse_utc(inventory.get("observed_at"))
            if observed_at > now + timedelta(minutes=1) or now - observed_at > timedelta(hours=26):
                gate("backup_freshness", "BLOCKED", "receipt stale or future dated; actual schedule success unknown")
            else:
                gate("backup_freshness", "UNVERIFIED", "recent attestation only; no independently inspected backup job")
        except (HealthBlocked, ValueError, TypeError, KeyError):
            gate("multi_store_inventory", "BLOCKED", "complete v2 protected receipt invalid or partial")
            gate("backup_freshness", "BLOCKED", "valid complete backup capture time not established")

    gate("encrypted_off_device_copy", "UNVERIFIED", "claim cannot prove independent off-device encrypted custody")
    gate("isolated_restore", "UNVERIFIED", "claim cannot prove actual fresh-volume isolated restore")
    gate("hardware_acceptance", "UNVERIFIED", "no real equipment evidence")
    return {
        "status": "BLOCKED",
        "profile": "LOCAL_LAN",
        "probe": "READ_ONLY_OFFLINE",
        "gates": gates,
        "production_backup": "NOT_PERFORMED_BY_PROBE",
        "site_activation": "NOT_AUTHORIZED",
        "next_action": "independently verify all protected stores, encrypted off-device copy, isolated restore and authorized scheduler",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, help="optional mode-0600 sanitized v2 DR receipt")
    args = parser.parse_args()
    inventory: dict | None = None
    timer: dict[str, str] | None = None
    try:
        if args.inventory is not None:
            inventory = read_sanitized_receipt(args.inventory)
    except HealthBlocked:
        pass
    try:
        timer = read_timer()
    except HealthBlocked:
        pass
    try:
        free = shutil.disk_usage("/").free
    except OSError:
        free = None
    print(json.dumps(assess(inventory, timer, free), sort_keys=True))
    return 78  # No in-chat structural evidence authorizes a real site restore.


if __name__ == "__main__":
    raise SystemExit(main())
