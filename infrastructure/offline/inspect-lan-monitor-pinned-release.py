#!/usr/bin/env python3
"""NEXOLAB #1476: read-only exact-source offline LAN monitor release gate.

Never installs services, changes Docker, activates alerts or approves a cutover.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
VERSION_ROOT = Path("/var/lib/nexolab/version-management")
RELEASES = Path("/opt/nexolab-lan-monitor/releases")
OLD_UNIT_SCRIPT = "/opt/nexolab/current/infrastructure/offline/emit-lan-access-prometheus.py"
SOURCE_SCRIPT = "infrastructure/offline/emit-lan-access-prometheus.py"
SERVICE_FILE = "infrastructure/systemd/nexolab-lan-access-probe.service"
CAPABILITY = "lan-access-monitor-source-only"
ASSETS = frozenset((
    "infrastructure/offline/inspect-site-lan-access.py",
    SOURCE_SCRIPT,
    SERVICE_FILE,
    "infrastructure/systemd/nexolab-lan-access-probe.timer",
    "infrastructure/observability/prometheus/optional-rules/lan-access-alerts.yml",
))
HOST_METRICS = "/home/nexolab/nexolab-platform/runtime/observability/lan-access.prom"
SHA = re.compile(r"^[0-9a-f]{40}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


class GateBlocked(ValueError):
    """Static refusal reasons only, never reveal site filenames in JSON."""


def render_unit(template: str, source: str) -> str:
    """Pure service source-pin rendering, never writing an installed unit."""
    if SHA.fullmatch(source) is None:
        raise GateBlocked("invalid_immutable_source")
    required = {
        "User=nexolab", "Group=nexolab", "NoNewPrivileges=yes",
        "ProtectSystem=strict", "PrivateDevices=yes",
        "ProtectHome=read-only",
        "ReadWritePaths=/home/nexolab/nexolab-platform/runtime/observability",
    }
    directives: dict[str, list[str]] = {}
    for line in template.splitlines():
        content = line.strip()
        if not content or content.startswith(("#", "[")) or "=" not in content:
            continue
        key, value = content.split("=", 1)
        directives.setdefault(key, []).append(value)
    for line in required:
        key, value = line.split("=", 1)
        if directives.get(key) != [value]:
            raise GateBlocked("source_service_template_untrusted")
    starts = directives.get("ExecStart", [])
    if (len(starts) != 1
            or not starts[0].startswith("/usr/bin/python3 -I -B " + OLD_UNIT_SCRIPT + " ")
            or " --output " + HOST_METRICS not in starts[0]
            or template.count(OLD_UNIT_SCRIPT) != 1
            or any(key in directives for key in (
                "ExecStartPre", "ExecStartPost", "RootDirectory",
                "RootImage", "ExecCondition", "UserOverride"))):
        raise GateBlocked("source_service_template_untrusted")
    pinned = RELEASES / source / SOURCE_SCRIPT
    unit = template.replace(OLD_UNIT_SCRIPT, str(pinned))
    if OLD_UNIT_SCRIPT in unit or str(pinned) not in unit:
        raise GateBlocked("source_service_not_pinned")
    return unit


def evaluate(
    *,
    accepted_source: str,
    required_source: str,
    package_authority: bool,
    provenance: dict[str, Any],
    manifest_records: dict[str, Any],
    packaged: dict[str, Any],
    release_dirs: dict[str, Any],
    materialized: dict[str, Any],
    service_template: str,
) -> dict[str, Any]:
    gates = {key: False for key in (
        "accepted_immutable_site_package",
        "exact_required_source",
        "bundle_monitor_capability",
        "sealed_five_asset_inventory",
        "all_package_asset_digests",
        "pinned_readable_release_tree",
        "materialized_asset_identity",
        "generated_systemd_source_pin",
        "operator_rollback_site_acceptance",
    )}
    result = {
        "status": "BLOCKED", "read_only": True, "site_mutation": False,
        "activation_authorized": False, "hardware_verified": False,
        "checks": gates,
    }

    def require(value: bool, gate: str, reason: str) -> None:
        if not value:
            raise GateBlocked(reason)
        gates[gate] = True

    try:
        require(package_authority, "accepted_immutable_site_package",
                "accepted_package_unverified")
        require(SHA.fullmatch(accepted_source) is not None
                and SHA.fullmatch(required_source) is not None
                and accepted_source == required_source,
                "exact_required_source", "accepted_source_does_not_match_candidate")
        capabilities = provenance.get("tooling_capabilities")
        require(isinstance(capabilities, list)
                and all(isinstance(x, str) for x in capabilities)
                and len(capabilities) == len(set(capabilities))
                and CAPABILITY in capabilities,
                "bundle_monitor_capability", "monitor_provenance_missing_or_invalid")
        candidates = {
            name for name in manifest_records
            if isinstance(name, str) and (
                name in ASSETS
                or name.startswith("infrastructure/offline/inspect-site-lan-access")
                or name.startswith("infrastructure/offline/emit-lan-access-prometheus")
                or name.startswith("infrastructure/systemd/nexolab-lan-access-probe")
                or name.startswith("infrastructure/observability/prometheus/optional-rules/lan-access-alerts")
            )
        } if isinstance(manifest_records, dict) else set()
        require(isinstance(manifest_records, dict)
                and candidates == ASSETS
                and len(ASSETS) == 5,
                "sealed_five_asset_inventory", "required_manifest_assets_missing")
        for name in ASSETS:
            record = manifest_records[name]
            if (not isinstance(record, dict)
                or not isinstance(record.get("size_bytes"), int)
                or not 0 < record["size_bytes"] <= 100_000
                or HASH.fullmatch(str(record.get("sha256",""))) is None):
                raise GateBlocked("sealed_file_manifest_record_invalid")
        gates["sealed_five_asset_inventory"] = True
        for name in ASSETS:
            source = packaged.get(name)
            record = manifest_records[name]
            if (not isinstance(source, dict)
                or source.get("regular") is not True
                or source.get("symlink") is True
                or source.get("size_bytes") != record["size_bytes"]
                or source.get("sha256") != record["sha256"]):
                raise GateBlocked("packaged_asset_mismatch_or_unsafe")
        gates["all_package_asset_digests"] = True

        expected_dirs = ["/opt", "/opt/nexolab-lan-monitor",
                         str(RELEASES), str(RELEASES / required_source)]
        for directory in expected_dirs:
            info = release_dirs.get(directory)
            if (not isinstance(info, dict)
                or info.get("directory") is not True
                or info.get("symlink") is True
                or info.get("uid") != 0
                or info.get("mode") not in (0o755, 0o555)):
                raise GateBlocked("pinned_release_directory_not_ready")
        gates["pinned_readable_release_tree"] = True
        for name in ASSETS:
            file = materialized.get(name)
            source = packaged[name]
            if (not isinstance(file, dict)
                or file.get("regular") is not True
                or file.get("symlink") is True
                or file.get("uid") != 0
                or file.get("mode") not in (0o644, 0o444)
                or file.get("size_bytes") != source["size_bytes"]
                or file.get("sha256") != source["sha256"]):
                raise GateBlocked("pinned_release_asset_missing_or_drifted")
        gates["materialized_asset_identity"] = True

        unit = render_unit(service_template, required_source)
        require("ExecStart=/usr/bin/python3 -I -B " + str(RELEASES / required_source / SOURCE_SCRIPT) in unit,
                "generated_systemd_source_pin", "systemd_unit_source_pin_invalid")
        result["reason"] = "operator_rollback_and_site_activation_unverified"
    except GateBlocked as exc:
        result["reason"] = str(exc)
    return result


def import_guard() -> Any:
    path = PROJECT / "infrastructure/offline/inspect-packaged-boot-network.py"
    spec = importlib.util.spec_from_file_location("nexolab_pinned_monitor_boot_guard", path)
    if spec is None or spec.loader is None:
        raise GateBlocked("accepted_guard_missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inspect_stat(path: Path, *, data: bool = False) -> dict[str, Any]:
    try:
        s = path.lstat()
    except OSError:
        return {}
    result = {
        "directory": stat.S_ISDIR(s.st_mode),
        "regular": stat.S_ISREG(s.st_mode),
        "symlink": stat.S_ISLNK(s.st_mode),
        "uid": s.st_uid,
        "mode": stat.S_IMODE(s.st_mode),
        "size_bytes": s.st_size,
    }
    if data and result["regular"] and result["size_bytes"] <= 100_000:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            s2 = os.fstat(fd)
            if not stat.S_ISREG(s2.st_mode) or s2.st_size > 100_000:
                return {}
            content = os.read(fd, 100_001)
        finally:
            os.close(fd)
        if len(content) != s2.st_size:
            return {}
        result["sha256"] = hashlib.sha256(content).hexdigest()
    return result


def check_site(required_source: str) -> dict[str, Any]:
    try:
        guard = import_guard()
        guard.validate_authority(VERSION_ROOT)
        guard.check_update_locks(VERSION_ROOT)
        current = guard.read_object(VERSION_ROOT / "current.json")
        bundle = Path(current["bundle_root"])
        if (not str(bundle).startswith(str(VERSION_ROOT / "catalog") + "/")
            or bundle.name != current.get("bundle_id") or bundle.is_symlink()):
            raise GateBlocked("catalog_source_identity_untrusted")
        manifest = json.loads((bundle / "manifest.json").read_text())
        provenance = json.loads((bundle / "evidence/provenance.json").read_text())
        entries = manifest.get("files")
        if not isinstance(entries, list) or any(
            not isinstance(x, dict) or not isinstance(x.get("path"), str)
            for x in entries
        ):
            raise GateBlocked("bundle_manifest_file_inventory_invalid")
        names = [x["path"] for x in entries]
        if len(names) != len(set(names)):
            raise GateBlocked("bundle_manifest_duplicate_path")
        records = {record["path"]: record for record in entries}
        material = {name: inspect_stat(bundle / name, data=True) for name in ASSETS}
        dirs = {str(p): inspect_stat(p) for p in (
            Path("/opt"), RELEASES.parent, RELEASES, RELEASES / required_source)}
        staged = {name: inspect_stat(RELEASES / required_source / name, data=True) for name in ASSETS}
        if material.get(SERVICE_FILE, {}).get("regular"):
            fd = os.open(bundle / SERVICE_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                template = os.read(fd, 100_001).decode("utf-8")
            finally:
                os.close(fd)
            if hashlib.sha256(template.encode("utf-8")).hexdigest() != material[SERVICE_FILE].get("sha256"):
                raise GateBlocked("source_template_changed_during_read")
        else:
            template = ""
        return evaluate(
            accepted_source=current.get("source_commit",""),
            required_source=required_source,
            package_authority=manifest.get("source_commit")==current.get("source_commit"),
            provenance=provenance,
            manifest_records=records,
            packaged=material, release_dirs=dirs,
            materialized=staged,
            service_template=template,
        )
    except Exception:
        return {
            "status":"BLOCKED", "reason":"protected_pinned_release_evidence_unavailable",
            "read_only":True, "site_mutation":False,
            "activation_authorized":False, "hardware_verified":False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--required-source-commit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(check_site(args.required_source_commit), sort_keys=True))
    return 78


if __name__ == "__main__":
    sys.exit(main())
