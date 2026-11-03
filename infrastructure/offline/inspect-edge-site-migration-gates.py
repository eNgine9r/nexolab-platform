#!/usr/bin/env python3
"""NEXOLAB #1469: fail-closed, read-only, exact-site Edge IPAM cutover readiness.

Never approves, performs or schedules a live migration. Reuses protected
installed package authority, existing Docker identity checks and route guard.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable

SOURCE_DIR = Path(__file__).resolve().parent
PROTECTED_ROOT = Path("/var/lib/nexolab/version-management")
NETWORK_NAME = "nexolab-edge_default"
STANDALONE = "nexolab-standalone-runtime"
PROTECTED_ROLES = {
    "mqtt": ("nexolab-edge-mqtt-1", "mqtt", "nexolab-edge_mqtt-data", "1883/tcp", "1883"),
    "device-agent": (
        "nexolab-edge-device-agent-1", "device-agent",
        "nexolab-edge_edge-data", "8081/tcp", "8081",
    ),
}


class SiteBlocked(RuntimeError):
    """Use fixed reason strings; never leak environment or credentials."""


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SiteBlocked("required_source_guard_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(
    *,
    candidate: str,
    image_digests: dict[str, frozenset[str]],
    network_report: dict[str, Any],
    containers: dict[str, dict[str, Any]],
    volumes: dict[str, dict[str, Any]],
    update_lock_free: bool,
    protected_release_ready: bool,
) -> dict[str, Any]:
    """Pure policy: site CIDR/admin reservation/rollback acceptance never fabricated."""
    gates = {
        "immutable_package_identity": False,
        "no_version_update_in_progress": False,
        "existing_cidr_overlap_confirmed": False,
        "candidate_locally_disjoint": False,
        "edge_network_identities": False,
        "edge_persistent_volume_identities": False,
        "edge_device_hardware": False,
        "site_network_reservation": False,
        "protected_consistent_rollback": False,
        "actual_offline_boot_acceptance": False,
    }
    out: dict[str, Any] = {
        "status": "BLOCKED",
        "read_only": True,
        "site_cutover_authorized": False,
        "mutation_performed": False,
        "hardware_verified": False,
        "checks": gates,
    }
    try:
        if not protected_release_ready or not image_digests:
            raise SiteBlocked("validated_site_package_unavailable")
        gates["immutable_package_identity"] = True
        if not update_lock_free:
            raise SiteBlocked("version_update_in_progress")
        gates["no_version_update_in_progress"] = True

        if network_report.get("candidate") != candidate:
            raise SiteBlocked("source_candidate_mismatch")
        overlaps = network_report.get("existing_overlap")
        if not isinstance(overlaps, list) or not any(
            x.get("docker") == NETWORK_NAME for x in overlaps if isinstance(x, dict)
        ):
            raise SiteBlocked("required_old_edge_overlap_not_proven")
        gates["existing_cidr_overlap_confirmed"] = True
        if (network_report.get("status") != "candidate_unapproved"
            or network_report.get("candidate_status") != "locally_disjoint_not_site_approved"
            or network_report.get("site_cutover_authorized") is True
            or network_report.get("mutation_performed") is not False
            or network_report.get("site_reservations_verified") is not False
            or network_report.get("candidate_conflicts")):
            raise SiteBlocked("candidate_not_locally_safe_or_source_guard_invalid")
        gates["candidate_locally_disjoint"] = True

        allowed_networks = {NETWORK_NAME, STANDALONE}
        for role, (name, image_role, volume_name, port, host_port) in PROTECTED_ROLES.items():
            obj = containers.get(role)
            if not isinstance(obj, dict) or obj.get("Name") not in ("/" + name, name):
                raise SiteBlocked("edge_container_identity_untrusted")
            labels = (obj.get("Config") or {}).get("Labels") or {}
            if (labels.get("com.docker.compose.project") != "nexolab-edge"
                or labels.get("com.docker.compose.service") != role
                or obj.get("Image") not in image_digests.get(image_role, frozenset())
                or (obj.get("State") or {}).get("Running") is not True):
                raise SiteBlocked("edge_container_image_or_compose_drift")
            networks = (obj.get("NetworkSettings") or {}).get("Networks")
            if not isinstance(networks, dict) or set(networks) != allowed_networks:
                raise SiteBlocked("edge_container_network_drift")
            bound = ((obj.get("HostConfig") or {}).get("PortBindings") or {}).get(port)
            expected = [{"HostIp": "127.0.0.1", "HostPort": host_port}]
            if bound != expected:
                raise SiteBlocked("edge_loopback_port_binding_drift")
            mounts = obj.get("Mounts") or []
            if not any(
                isinstance(m, dict) and m.get("Type") == "volume"
                and m.get("Name") == volume_name
                and m.get("Destination") == (
                    "/mosquitto/data" if role == "mqtt" else "/var/lib/nexolab"
                )
                for m in mounts
            ):
                raise SiteBlocked("edge_mqtt_or_sqlite_volume_mount_missing")
            volume = volumes.get(volume_name)
            if not isinstance(volume, dict) or volume.get("Name") != volume_name:
                raise SiteBlocked("edge_persistent_volume_missing")
        gates["edge_network_identities"] = True
        gates["edge_persistent_volume_identities"] = True
        # No software-only evidence can independently establish a protected
        # rollback / subnet reservation / human physical USB read acceptance.
        out["reason"] = "site_reservation_rollback_and_hardware_acceptance_required"
    except SiteBlocked as exc:
        out["reason"] = str(exc)
    return out


def collect_and_evaluate(
    candidate: str, reserved: tuple[str, ...] = (),
) -> dict[str, Any]:
    try:
        boot = load("nexolab_boot_observer_1469", SOURCE_DIR / "inspect-packaged-boot-network.py")
        edge = load("nexolab_edge_ipam_guard_1469", SOURCE_DIR / "inspect-edge-docker-ipam-readiness.py")
        digests = boot.validate_authority(PROTECTED_ROOT)
        boot.check_update_locks(PROTECTED_ROOT)
        report = edge.analyze(*edge.collect(), candidate=candidate, reserved=reserved)
        containers = {}
        volumes = {}
        for role, (name, _, volume_name, _, _) in PROTECTED_ROLES.items():
            containers[role] = boot.inspect_docker(name, "container")
            volumes[volume_name] = boot.inspect_docker(volume_name, "volume")
        return evaluate(
            candidate=candidate, image_digests=digests, network_report=report,
            containers=containers, volumes=volumes,
            update_lock_free=True, protected_release_ready=True,
        )
    except Exception:
        # Every exception must remain sanitized: an underlying Docker exception
        # could include a credential, URL, terminal or sensitive local path.
        return {
            "status": "BLOCKED", "reason": "required_readonly_site_evidence_unavailable",
            "read_only": True, "mutation_performed": False,
            "site_cutover_authorized": False, "hardware_verified": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True, action="store_true")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--reserved-cidr", action="append", default=[])
    args = parser.parse_args(argv)
    report = collect_and_evaluate(args.candidate, tuple(args.reserved_cidr))
    print(json.dumps(report, sort_keys=True))
    # Never return success: operator site reservation, backup/rollback, USB and
    # real boot recovery are separate guarded physical acceptance evidence.
    return 78


if __name__ == "__main__":
    sys.exit(main())
