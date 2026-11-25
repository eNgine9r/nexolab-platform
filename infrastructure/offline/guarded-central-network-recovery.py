#!/usr/bin/env python3
"""NEXOLAB #1462 / parent #1399 protected source-only central Docker network repair.

No site installation, boot activation or network mutation on --check.
Any future --execute is a separately owner-approved protected cutover, not an
unattended workaround. Never touches Edge, PostgreSQL, Docker network IPAM,
service images, persistent volumes, credentials, hardware or host routes.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable

ROOT = Path("/var/lib/nexolab/version-management")
BOOT_OBSERVER = Path(__file__).with_name("inspect-packaged-boot-network.py")
BOUNDED_NETWORKS = frozenset({"nexolab-central", "nexolab-standalone-runtime"})
# Only already validated, existing containers and already existing bridge networks.
# No Compose up/down, Docker network create/rm, restart or changes to Edge/PG.
PROTECTED_AUTH_MOUNTS = frozenset({
    "/run/secrets/nexolab_local_auth_private_key",
    "/run/secrets/nexolab_local_auth_public_key",
})
ROLE_ALIASES = {
    "mqtt": {"nexolab-central": ("mqtt",), "nexolab-standalone-runtime": ("mqtt", "central-mqtt")},
    "telemetry-service": {
        "nexolab-central": ("telemetry-service",),
        "nexolab-standalone-runtime": ("telemetry-service", "central-api"),
    },
    "dashboard": {"nexolab-central": ("dashboard",)},
    "minio": {"nexolab-central": ("minio",)},
}


class RecoveryBlocked(RuntimeError):
    pass


def observer_module():
    spec = importlib.util.spec_from_file_location("nexolab_boot_observer", BOOT_OBSERVER)
    if spec is None or spec.loader is None:
        raise RecoveryBlocked("boot_observer_source_missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def execute_docker(argv: list[str]) -> None:
    """One fixed schema; no shell, no externally supplied network/service."""
    if not argv or argv[:3] != ["docker", "network", "connect"]:
        raise RecoveryBlocked("unapproved_docker_operation")
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryBlocked("scoped_network_attach_failed") from exc


def get_attached(obj: dict[str, Any]) -> set[str]:
    nets = (obj.get("NetworkSettings") or {}).get("Networks")
    if not isinstance(nets, dict):
        raise RecoveryBlocked("invalid_running_network_state")
    return set(nets)


def create_plan(observation: dict[str, Any], inspect: Callable[[str, str], dict[str, Any]],
                mod: Any) -> list[dict[str, Any]]:
    if observation["status"] == "ready":
        return []
    if observation["status"] != "drift_detected" or observation.get("manual_only_services"):
        raise RecoveryBlocked("manual_or_hardware_drift_present")
    planned: list[dict[str, Any]] = []
    for role in observation["candidate_order"]:
        if role not in ROLE_ALIASES:
            raise RecoveryBlocked("unapproved_repair_role")
        name = mod.CONTAINER_NAMES[role]
        obj = inspect(name, "container")
        if (obj.get("State") or {}).get("Running") is not True:
            raise RecoveryBlocked("target_container_not_running")
        if role == "telemetry-service":
            # Never reconnect an API container with missing/changed signing
            # keys or writable bind-mounted credential locations.
            mounts = {
                m.get("Destination"): m
                for m in (obj.get("Mounts") or [])
                if isinstance(m, dict)
            }
            if any(
                mounts.get(dest, {}).get("Type") != "bind"
                or mounts.get(dest, {}).get("RW") is not False
                for dest in PROTECTED_AUTH_MOUNTS
            ):
                raise RecoveryBlocked("protected_auth_bind_mount_missing_or_writable")
        current = get_attached(obj)
        expected = mod.NETWORK_REQUIREMENTS[role]
        # An unknown extra network is a manual incident, not a recovery target.
        if not current.issubset(expected):
            raise RecoveryBlocked("unexpected_container_network")
        missing = expected - current
        if not missing:
            raise RecoveryBlocked("drift_without_missing_network")
        if not missing.issubset(BOUNDED_NETWORKS):
            raise RecoveryBlocked("unapproved_target_network")
        for network in sorted(missing):
            aliases = ROLE_ALIASES[role].get(network)
            if not aliases:
                raise RecoveryBlocked("no_fixed_network_alias_policy")
            net = inspect(network, "network")
            if net.get("Name") != network or net.get("Driver") != "bridge":
                raise RecoveryBlocked("untrusted_docker_network_identity")
            configs = ((net.get("IPAM") or {}).get("Config") or [])
            if not isinstance(configs, list) or len(configs) != 1 or not configs[0].get("Subnet"):
                raise RecoveryBlocked("invalid_existing_network_ipam")
            planned.append({"role": role, "container": name, "network": network,
                            "aliases": list(aliases)})
    # A deterministic, bounded four-role repair. Never touch DB, Edge or devices.
    if len(planned) > 6:
        raise RecoveryBlocked("too_many_recovery_operations")
    return planned


def check_live(mod: Any, root: Path, inspect: Callable[[str, str], dict[str, Any]],
               *, locks_already_held: bool = False):
    mod.inspect_host_cidr()
    digests = mod.validate_authority(root)
    # The protected worker/update-plane locks are already held EXCLUSIVELY
    # during execute. Reopening their inodes for a second shared flock would
    # self-conflict on Linux because each open has a distinct file description.
    # Skipping this re-acquire is safe ONLY while the caller's ExitStack still
    # owns the exact pair of exclusive locks.
    if not locks_already_held:
        mod.check_update_locks(root)
    observation = mod.diagnose_containers(digests, inspect)
    observation["status"] = ("manual_review_required" if observation["manual_only_services"]
                             else "drift_detected" if observation["container_drift"] else "ready")
    return digests, observation, create_plan(observation, inspect, mod)


def hold_update_locks(stack: ExitStack, root: Path) -> None:
    for item in ("worker.lock", "update-plane.lock"):
        path = root / item
        if not path.is_file() or path.is_symlink():
            raise RecoveryBlocked("protected_update_lock_missing")
        handle = stack.enter_context(path.open("rb"))
        try:
            # Exclusive lock prevents two root recovery invocations racing
            # as well as excluding installed update-plane writers.
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryBlocked("version_update_active") from exc


def recover(
    root: Path, *,
    approval_bundle: str | None = None,
    approval_source: str | None = None,
    enable: bool = False,
    mod: Any = None,
    inspect: Callable[[str, str], dict[str, Any]] | None = None,
    connect: Callable[[list[str]], None] = execute_docker,
    is_root: Callable[[], bool] = lambda: os.geteuid() == 0,
) -> dict[str, Any]:
    mod = mod or observer_module()
    inspect = inspect or mod.inspect_docker
    applied = 0
    try:
        _, observation, plan = check_live(mod, root, inspect)
        if not enable:
            return {"status": "clean" if not plan else "dry_run_only",
                    "mutation_performed": False,"operation_count": len(plan),
                    "planned": [{"role": a["role"], "network": a["network"]} for a in plan],
                    "site_cutover": "NOT_AUTHORIZED"}
        if not is_root() or not approval_bundle or not approval_source:
            raise RecoveryBlocked("explicit_root_and_site_release_approval_required")
        if re.fullmatch(r"[A-Za-z0-9._-]{8,170}", approval_bundle) is None:
            raise RecoveryBlocked("invalid_approved_release_identity")
        if re.fullmatch(r"[0-9a-f]{40}", approval_source) is None:
            raise RecoveryBlocked("invalid_approved_source_identity")
        if not plan:
            return {"status": "already_ready", "mutation_performed": False,
                    "operation_count": 0}
        # Locks are held across ALL operations, not released between preflight
        # and network changes. The current release identity is rechecked.
        with ExitStack() as stack:
            hold_update_locks(stack, root)
            current = mod.read_object(root / "current.json")
            if current.get("bundle_id") != approval_bundle or current.get("source_commit") != approval_source:
                raise RecoveryBlocked("approved_release_no_longer_current")
            digests, before, new_plan = check_live(mod, root, inspect, locks_already_held=True)
            if new_plan != plan:
                raise RecoveryBlocked("network_state_changed_after_preflight")
            if before.get("manual_only_services"):
                raise RecoveryBlocked("manual_drift_present")
            for item in plan:
                # No generic user-provided command and no network creation.
                # Source/volume/mount provenance rechecked before every action.
                if mod.validate_authority(root) != digests:
                    raise RecoveryBlocked("immutable_package_changed")
                mod.inspect_host_cidr()
                mod.diagnose_containers(digests, inspect)
                obj = inspect(item["container"], "container")
                if item["network"] in get_attached(obj):
                    raise RecoveryBlocked("network_state_changed_during_recovery")
                argv = ["docker", "network", "connect"]
                for alias in item["aliases"]:
                    argv.extend(["--alias", alias])
                argv.extend([item["network"], item["container"]])
                connect(argv)
                applied += 1
                obj = inspect(item["container"], "container")
                if item["network"] not in get_attached(obj):
                    raise RecoveryBlocked("network_attach_not_observed")
            return {"status": "connection_restore_attempted",
                    "mutation_performed": bool(applied), "operation_count": applied,
                    "site_runtime_verified": False, "hardware_verified": False}
    except (RecoveryBlocked, mod.BootGuardError, OSError, ValueError) as exc:
        return {"status": "blocked_partial_mutation" if applied else "blocked",
                "mutation_performed": bool(applied), "operations_completed": applied,
                "reason": str(exc)[:150], "site_cutover": "NOT_AUTHORIZED"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="read-only default; no site mutation")
    group.add_argument("--execute", action="store_true", help="separate owner-approved site operation")
    parser.add_argument("--approved-bundle-id", help="exact installed validated package ID")
    parser.add_argument("--approved-source-commit", help="exact installed source commit")
    args = parser.parse_args(argv)
    # Installed protected root is fixed; no path injection into privileged
    # reads. Source-only testing injects its own fake modules/roots.
    result = recover(ROOT, enable=args.execute,
                     approval_bundle=args.approved_bundle_id,
                     approval_source=args.approved_source_commit)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("clean", "already_ready") else 78


if __name__ == "__main__":
    sys.exit(main())
