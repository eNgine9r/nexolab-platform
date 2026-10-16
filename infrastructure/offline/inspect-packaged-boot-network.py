#!/usr/bin/env python3
"""Observe accepted NEXOLAB packaged Docker network state. NEVER mutates it.

This is the first stage of #1399. No restart, network connect, Compose up,
lock creation, file write, hardware command, or update authority mutation.
A protected *separate* operator activation is required for any future repair.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

EXPECTED_VOLUMES = {
    "mqtt": {"nexolab-central-mqtt-data"},
    "postgres": {"nexolab-central-postgres-data"},
    "minio": {"nexolab-central-object-storage-versitygw-data"},
    "telemetry-service": {"nexolab-central-telemetry-ingestion-data"},
    "device-agent": {"nexolab-edge_edge-data"},
}
CENTRAL_SERVICES = ("postgres", "mqtt", "telemetry-service", "dashboard", "minio")
NETWORK_REQUIREMENTS = {
    "postgres": {"nexolab-central"},
    "mqtt": {"nexolab-central", "nexolab-standalone-runtime"},
    "telemetry-service": {"nexolab-central", "nexolab-standalone-runtime"},
    "dashboard": {"nexolab-central"},
    "minio": {"nexolab-central"},
    "device-agent": {"nexolab-edge_default", "nexolab-standalone-runtime"},
}
REPAIR_PRIORITY = ("mqtt", "telemetry-service", "dashboard", "minio")
IMAGE_ROLES = {
    "minio": "object-storage", "telemetry-service": "telemetry-service",
    "dashboard": "dashboard", "mqtt": "mqtt", "postgres": "postgres",
    "device-agent": "device-agent",
}
CONTAINER_NAMES = {
    **{s: f"nexolab-central-{s}-1" for s in CENTRAL_SERVICES},
    "device-agent": "nexolab-edge-device-agent-1",
}


class BootGuardError(RuntimeError):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise BootGuardError(reason)


def read_object(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootGuardError("protected_authority_file_missing_or_invalid") from exc
    require(isinstance(obj, dict), "protected_authority_not_an_object")
    return obj


def validate_authority(root: Path) -> dict[str, str]:
    # No symlink traversal into a new release root or arbitrary user-supplied
    # bundle. Only the installed trusted catalog path is accepted.
    require(root.is_dir() and not root.is_symlink(), "protected_root_unavailable")
    current = read_object(root / "current.json")
    require(
        current.get("deployment_authority") == "validated_package"
        and current.get("runtime_state_known") is True
        and current.get("health") == "ready",
        "installed_package_authority_not_ready",
    )
    bundle_id = current.get("bundle_id")
    source = current.get("source_commit")
    require(isinstance(bundle_id, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{8,170}", bundle_id) is not None,
            "invalid_bundle_id")
    require(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source) is not None,
            "installed_source_identity_invalid")
    require(current.get("platform") == "linux/arm64" and platform.machine() == "aarch64",
            "installed_platform_mismatch")
    catalog = root / "catalog" / bundle_id
    require(catalog.is_dir() and not catalog.is_symlink(), "installed_catalog_unavailable")
    require(current.get("bundle_root") == str(catalog), "catalog_path_not_trusted")
    manifest_path = catalog / "manifest.json"
    marker = read_object(catalog / ".nexolab-validated.json")
    manifest = read_object(manifest_path)
    try:
        sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BootGuardError("manifest_not_readable") from exc
    require(marker.get("manifest_sha256") == sha, "immutable_package_manifest_marker_mismatch")
    require(
        manifest.get("source_commit") == source
        and manifest.get("platform") == "linux/arm64"
        and (manifest.get("version_management") or {}).get("bundle_id") == bundle_id,
        "installed_bundle_metadata_mismatch",
    )
    images = manifest.get("images")
    require(isinstance(images, list), "installed_image_inventory_missing")
    hashes = {
        obj["id"]: obj["image_id"]
        for obj in images
        if isinstance(obj, dict)
        and isinstance(obj.get("id"), str)
        and isinstance(obj.get("image_id"), str)
    }
    require(
        all(x in hashes and re.fullmatch(r"sha256:[0-9a-f]{64}", hashes[x])
            for x in IMAGE_ROLES.values()),
        "immutable_image_inventory_incomplete",
    )
    previous = current.get("previous_bundle_id")
    if previous is not None:
        require(
            isinstance(previous, str)
            and re.fullmatch(r"[a-zA-Z0-9_.-]{8,170}", previous) is not None
            and (root / "catalog" / previous).is_dir(),
            "prior_rollback_bundle_missing",
        )
    return hashes


def check_update_locks(root: Path) -> None:
    handles = []
    try:
        for name in ("worker.lock", "update-plane.lock"):
            path = root / name
            require(path.is_file() and not path.is_symlink(), "protected_update_lock_missing")
            handle = path.open("r")
            handles.append(handle)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BootGuardError("version_update_active") from exc
    finally:
        for handle in reversed(handles):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def inspect_docker(name: str, kind: str = "container") -> dict[str, Any]:
    try:
        p = subprocess.run(
            ["docker", "inspect", "--type", kind, name],
            capture_output=True, text=True, check=True, timeout=8,
        )
        payload = json.loads(p.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise BootGuardError("docker_inspection_failed") from exc
    require(
        isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict),
        "docker_inspection_not_unique",
    )
    return payload[0]


def diagnose_containers(
    expected_images: dict[str, str],
    inspect: Callable[[str, str], dict[str, Any]] = inspect_docker,
) -> dict[str, Any]:
    drift: list[dict[str, str]] = []
    observed: dict[str, dict[str, Any]] = {}
    for role, name in CONTAINER_NAMES.items():
        obj = inspect(name, "container")
        labels = (obj.get("Config") or {}).get("Labels") or {}
        expected_project = "nexolab-edge" if role == "device-agent" else "nexolab-central"
        expected_service = "minio" if role == "minio" else role
        require(
            labels.get("com.docker.compose.project") == expected_project
            and labels.get("com.docker.compose.service") == expected_service,
            f"container_compose_identity_untrusted_{role}",
        )
        require(obj.get("Image") == expected_images[IMAGE_ROLES[role]],
                f"container_image_drift_{role}")
        expected_volume_names = EXPECTED_VOLUMES.get(role, set())
        actual_volume_names = {
            mount.get("Name")
            for mount in obj.get("Mounts") or []
            if isinstance(mount, dict) and mount.get("Type") == "volume"
        }
        require(expected_volume_names <= actual_volume_names, f"volume_mount_missing_{role}")
        for volume_name in expected_volume_names:
            volume = inspect(volume_name, "volume")
            require(volume.get("Name") == volume_name, f"named_volume_missing_{role}")

        networks = (obj.get("NetworkSettings") or {}).get("Networks") or {}
        require(isinstance(networks, dict), f"invalid_network_metadata_{role}")
        missing = sorted(NETWORK_REQUIREMENTS[role] - set(networks))
        if missing:
            drift.append({"service": role, "kind": "missing_network", "detail": ",".join(missing)})
        state = obj.get("State") or {}
        running = state.get("Running") is True
        if not running:
            drift.append({"service": role, "kind": "not_running", "detail": "container"})
        health = (state.get("Health") or {}).get("Status")
        if role != "minio" and health != "healthy":
            drift.append({"service": role, "kind": "unhealthy", "detail": "healthcheck"})
        if role in {"dashboard", "mqtt", "telemetry-service", "minio"}:
            bound = (obj.get("HostConfig") or {}).get("PortBindings") or {}
            actual = (obj.get("NetworkSettings") or {}).get("Ports") or {}
            expected = {"dashboard": "3000/tcp", "mqtt": "1883/tcp",
                        "telemetry-service": "8082/tcp", "minio": "9000/tcp"}[role]
            configured = bound.get(expected) or []
            published = actual.get(expected) or []
            if not configured or not all(x in published for x in configured):
                drift.append({"service": role, "kind": "missing_published_port",
                              "detail": expected})
        observed[role] = {"running": running, "networks": sorted(networks)}
    priority = [
        name for name in REPAIR_PRIORITY
        if any(item["service"] == name for item in drift)
    ]
    manual_roles = sorted({
        item["service"] for item in drift if item["service"] not in REPAIR_PRIORITY
    })
    return {"container_drift": drift, "candidate_order": priority,
            "manual_only_services": manual_roles,
            "protected_containers": sorted(observed)}


def inspect_host_cidr() -> None:
    script = Path(__file__).with_name("verify-lan-docker-network-isolation.py")
    require(script.is_file(), "source_bound_network_cidr_guard_missing")
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(script)],
            capture_output=True, text=True, timeout=25,
        )
        result = json.loads(process.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise BootGuardError("host_cidr_preflight_unavailable") from exc
    require(process.returncode == 0 and result.get("status") == "verified"
            and result.get("read_only") is True, "physical_docker_cidr_not_safe")


def run(root: Path, *,
        cidr_check: Callable[[], None] = inspect_host_cidr,
        authority: Callable[[Path], dict[str, str]] = validate_authority,
        locks: Callable[[Path], None] = check_update_locks,
        inspect: Callable[[str, str], dict[str, Any]] = inspect_docker) -> dict[str, Any]:
    # CIDR is the first fail-closed gate; never propose a repair with the
    # known physical LAN vs Docker route conflict.
    cidr_check()
    expected_images = authority(root)
    locks(root)
    observation = diagnose_containers(expected_images, inspect)
    state = ("manual_review_required" if observation["manual_only_services"]
             else "drift_detected" if observation["container_drift"] else "ready")
    return {"status": state,
            "mode": "observe_only", "mutation_performed": False,
            "owner_authorization_required_for_repair": bool(observation["container_drift"]),
            **observation}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/var/lib/nexolab/version-management"))
    parser.add_argument("--check", action="store_true", help="Read-only; only mode supported")
    args = parser.parse_args()
    try:
        result = run(args.root)
    except BootGuardError as exc:
        result = {"status": "blocked", "mode": "observe_only",
                  "mutation_performed": False, "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
