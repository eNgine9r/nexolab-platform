#!/usr/bin/env python3
"""#1472 read-only, fail-closed source/host-bound LAN alert install gate.

No site mutation, installation, network operation, hardware command or privileged execution.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import urllib.request
from typing import Any

PROTECTED_ROOT = Path("/var/lib/nexolab/version-management")
SOURCE_ROOT = Path(__file__).resolve().parents[2]
HOST_DIR = Path("/home/nexolab/nexolab-platform/runtime/observability")
CONTAINER_DIR = "/var/lib/nexolab-observability"
EXPORTER = "nexolab-central-observability-textfile-1"
LEGACY = "disaster-recovery.prom"
NEW_FILE = "lan-access.prom"
FILES = (
    "infrastructure/offline/inspect-site-lan-access.py",
    "infrastructure/offline/emit-lan-access-prometheus.py",
    "infrastructure/observability/prometheus/optional-rules/lan-access-alerts.yml",
    "infrastructure/systemd/nexolab-lan-access-probe.service",
    "infrastructure/systemd/nexolab-lan-access-probe.timer",
    "scripts/serve-prometheus-textfile.py",
)

def load_guard():
    source = SOURCE_ROOT / "infrastructure/offline/inspect-packaged-boot-network.py"
    spec = importlib.util.spec_from_file_location("nexolab_lan_install_boot_guard", source)
    if spec is None or spec.loader is None:
        raise ValueError("missing_immutable_package_guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def assess(
    *,
    installed_source: str, required_source: str,
    authority: bool, updates_idle: bool, exporter: dict[str, Any],
    directory: dict[str, Any], legacy: dict[str, Any],
    source_complete: bool, timer_loaded: bool, alerts_loaded: bool,
) -> dict[str, Any]:
    checks = {key: False for key in (
        "package_authority", "exact_installed_release",
        "update_locks_idle", "exporter_mounts_and_legacy_mode",
        "host_directory_and_target_safe", "legacy_dr_metrics_preserved",
        "source_units_complete", "site_probe_not_already_active",
        "optional_rules_not_prematurely_active",
        "site_rollback_and_activation_approved",
    )}
    result: dict[str, Any] = {
        "status": "BLOCKED", "read_only": True,
        "site_mutation": False, "site_activation_authorized": False,
        "hardware_verified": False, "checks": checks,
    }
    def check(value: bool, key: str, reason: str) -> None:
        if not value:
            raise ValueError(reason)
        checks[key] = True
    try:
        check(authority, "package_authority", "protected_package_authority_unavailable")
        check(
            re.fullmatch(r"[0-9a-f]{40}", installed_source) is not None
            and re.fullmatch(r"[0-9a-f]{40}", required_source) is not None
            and installed_source == required_source,
            "exact_installed_release", "requested_source_not_accepted_on_site",
        )
        check(updates_idle, "update_locks_idle", "protected_site_update_active")
        mounts = exporter.get("mounts")
        observed = exporter.get("path")
        good = (
            exporter.get("name") == EXPORTER
            and exporter.get("running") is True
            and exporter.get("project") == "nexolab-central"
            and exporter.get("role") == "observability-textfile"
            and observed == CONTAINER_DIR + "/" + LEGACY
            and isinstance(mounts, list)
        )
        if good:
            data = [m for m in mounts if m.get("Destination") == CONTAINER_DIR]
            script = [m for m in mounts if m.get("Destination") == "/opt/nexolab/scripts/serve-prometheus-textfile.py"]
            good = (
                len(data) == len(script) == 1
                and data[0].get("Type") == script[0].get("Type") == "bind"
                and data[0].get("Source") == str(HOST_DIR)
                and data[0].get("RW") is False
                and script[0].get("Source") == "/home/nexolab/nexolab-platform/scripts/serve-prometheus-textfile.py"
                and script[0].get("RW") is False
            )
        check(good, "exporter_mounts_and_legacy_mode", "exporter_host_bind_or_legacy_mode_mismatch")
        check(
            directory.get("is_directory") is True
            and directory.get("is_symlink") is False
            and directory.get("owner") == "nexolab"
            and directory.get("mode") == 0o700
            and directory.get("same_local_filesystem") is True
            and directory.get("new_target_safe") is True,
            "host_directory_and_target_safe", "unsafe_or_unmapped_site_metrics_directory",
        )
        check(
            legacy.get("regular") is True and legacy.get("symlink") is False
            and legacy.get("owner") == "nexolab"
            and legacy.get("mode") in (0o600, 0o640)
            and legacy.get("size", 0) > 0,
            "legacy_dr_metrics_preserved", "existing_dr_metrics_untrusted",
        )
        check(source_complete, "source_units_complete", "source_artifacts_or_host_path_mismatch")
        check(not timer_loaded, "site_probe_not_already_active", "site_probe_timer_unreviewed_or_active")
        check(not alerts_loaded, "optional_rules_not_prematurely_active", "optional_alerts_activated_before_probe")
        result["reason"] = "protected_install_rollback_and_owner_activation_required"
    except ValueError as exc:
        result["reason"] = str(exc)
    return result

def stat_path(path: Path) -> dict[str, Any]:
    try:
        st = path.lstat()
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (OSError, KeyError):
        return {}
    return {
        "is_directory": stat.S_ISDIR(st.st_mode),
        "regular": stat.S_ISREG(st.st_mode),
        "is_symlink": stat.S_ISLNK(st.st_mode),
        "symlink": stat.S_ISLNK(st.st_mode),
        "mode": stat.S_IMODE(st.st_mode),
        "owner": owner, "size": st.st_size,
    }

def collect(required_source: str) -> dict[str, Any]:
    try:
        guard = load_guard()
        guard.validate_authority(PROTECTED_ROOT)
        metadata = guard.read_object(PROTECTED_ROOT / "current.json")
        guard.check_update_locks(PROTECTED_ROOT)
        obj = guard.inspect_docker(EXPORTER, "container")
        labels = (obj.get("Config") or {}).get("Labels") or {}
        env = (obj.get("Config") or {}).get("Env") or []
        choices = [item.split("=", 1)[1] for item in env if item.startswith("NEXOLAB_TEXTFILE_PATH=")]
        exporter = {
            "name": (obj.get("Name") or "").lstrip("/"),
            "running": (obj.get("State") or {}).get("Running"),
            "project": labels.get("com.docker.compose.project"),
            "role": labels.get("com.docker.compose.service"),
            "mounts": obj.get("Mounts"),
            "path": choices[0] if len(choices) == 1 else None,
        }
        directory = stat_path(HOST_DIR)
        target = stat_path(HOST_DIR / NEW_FILE)
        directory["new_target_safe"] = not target or (
            target.get("regular") is True and target.get("symlink") is False
            and target.get("owner") == "nexolab")
        directory["same_local_filesystem"] = (
            HOST_DIR.is_dir() and HOST_DIR.stat().st_dev == HOST_DIR.parent.stat().st_dev
        )
        source_complete = all(
            (SOURCE_ROOT / path).is_file() and not (SOURCE_ROOT / path).is_symlink()
            for path in FILES
        )
        unit = (SOURCE_ROOT / FILES[3]).read_text()
        source_complete = source_complete and all(s in unit for s in (
            "User=nexolab", "Group=nexolab", "NoNewPrivileges=yes",
            "ProtectHome=read-only",
            "ReadWritePaths=" + str(HOST_DIR),
            "--output " + str(HOST_DIR / NEW_FILE),
        ))
        result = subprocess.run(
            ["systemctl", "show", "nexolab-lan-access-probe.timer",
             "--property=LoadState", "--value"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        with urllib.request.urlopen("http://127.0.0.1:9090/api/v1/rules", timeout=5) as response:
            rules = json.load(response)
        groups = ((rules.get("data") or {}).get("groups") or [])
        return assess(
            installed_source=metadata.get("source_commit", ""),
            required_source=required_source, authority=True, updates_idle=True,
            exporter=exporter, directory=directory,
            legacy=stat_path(HOST_DIR / LEGACY),
            source_complete=source_complete,
            timer_loaded=result.stdout.strip() not in ("not-found", "masked"),
            alerts_loaded=any(
                isinstance(g, dict) and g.get("name") == "nexolab-lan-access"
                for g in groups
            ),
        )
    except Exception:
        # No exception text: Docker/OS errors may contain private paths/data.
        return {"status": "BLOCKED", "reason": "protected_site_evidence_unavailable",
                "read_only": True, "site_mutation": False,
                "site_activation_authorized": False, "hardware_verified": False}

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True, action="store_true")
    parser.add_argument("--required-source-commit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(collect(args.required_source_commit), sort_keys=True))
    return 78

if __name__ == "__main__":
    sys.exit(main())
