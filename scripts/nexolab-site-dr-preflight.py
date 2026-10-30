#!/usr/bin/env python3
"""NEXOLAB #1435 read-only source inventory. Never captures private data or mutates Docker.

A successful probe is NOT backup, restore, hardware, or site-cutover acceptance.
Only inspected identities and explicit unverified prerequisites are emitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Callable

GiB = 1024**3
IDENTITY = re.compile(r"^[0-9a-f]{64}$")
SHA_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
VOLUME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
PROJECTS = ("nexolab-central", "nexolab-edge")
# Source names are from compose.central/edge.yaml and must also be proved live.
# Notably "mqtt" occurs in BOTH Compose projects.
SOURCES = {
    "postgresql": ("nexolab-central", "postgres", "/var/lib/postgresql/data", "nexolab-central-postgres-data"),
    "object-storage": ("nexolab-central", "minio", "/data", "nexolab-central-object-storage-versitygw-data"),
    "mqtt-dynamic-security": ("nexolab-central", "mqtt", "/mosquitto/data", "nexolab-central-mqtt-data"),
    "edge-sqlite-outbox": ("nexolab-edge", "device-agent", "/var/lib/nexolab", "nexolab-edge_edge-data"),
    "local-auth-private-key": ("nexolab-central", "telemetry-service", None, None),
    "local-auth-public-key": ("nexolab-central", "telemetry-service", None, None),
    "central-ingestion-spool": ("nexolab-central", "telemetry-service", "/app/data/telemetry-ingestion", "nexolab-central-telemetry-ingestion-data"),
    "edge-mqtt-persistence": ("nexolab-edge", "mqtt", "/mosquitto/data", "nexolab-edge_mqtt-data"),
}
# These are hard caps for a future separately reviewed capture design, not grants
# to allocate disk, read secrets, or copy production volumes.
CAP_BYTES = {
    "postgresql": 4 * GiB,
    "object-storage": 4 * GiB,
    "mqtt-dynamic-security": GiB,
    "edge-sqlite-outbox": GiB,
    "local-auth-private-key": 1 * 1024 * 1024,
    "local-auth-public-key": 1 * 1024 * 1024,
    "central-ingestion-spool": 4 * GiB,
    "edge-mqtt-persistence": GiB,
}


class PreflightBlocked(ValueError):
    pass


def sha(text: str | bytes) -> str:
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(raw).hexdigest()


def protected_dir(path: Path, *, require_mount: bool = False) -> None:
    """No path creation, symlink following on leaf, or permission changes."""
    try:
        metadata = path.lstat()
        root = Path("/").stat()
    except OSError as exc:
        raise PreflightBlocked("protected path does not exist") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise PreflightBlocked("protected path is not a real directory")
    if metadata.st_uid != 0 or metadata.st_mode & 0o077:
        raise PreflightBlocked("protected path is not root-owned mode 0700")
    if require_mount and (not path.is_mount() or metadata.st_dev == root.st_dev):
        raise PreflightBlocked("destination lacks distinct mounted filesystem")
    # Refuse symlinked ancestors: an untrusted parent can redirect identities.
    for parent in path.parents:
        if parent.is_symlink():
            raise PreflightBlocked("protected path has symlink ancestor")


def capacity_check(work: Path, destination: Path) -> dict:
    protected_dir(work)
    protected_dir(destination, require_mount=True)
    free_work = shutil.disk_usage(work).free
    free_dest = shutil.disk_usage(destination).free
    if free_work < 24 * GiB:
        raise PreflightBlocked("working storage has less than 20 GiB reserve plus 4 GiB staging")
    if free_dest < 16 * GiB:
        raise PreflightBlocked("destination has less than 16 GiB bounded capacity")
    return {
        "working_free_bytes": free_work,
        "destination_free_bytes": free_dest,
        "working_reserve_bytes": 20 * GiB,
        "working_staging_cap_bytes": 4 * GiB,
        "destination_minimum_bytes": 16 * GiB,
        "destination_physical_independence": "unverified",
        "destination_key_custody": "unverified",
    }


def run_docker(argv: list[str]) -> str:
    """Exact argv only; no shell, environment, secrets, containers' .Env or .HostConfig."""
    try:
        result = subprocess.run(
            ["docker", *argv], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightBlocked("Docker read-only inspection unavailable") from exc
    if result.returncode or len(result.stdout) > 150000:
        raise PreflightBlocked("Docker inspection failed or exceeded output limit")
    return result.stdout.strip()


def probe_sources(run: Callable[[list[str]], str] = run_docker) -> dict:
    """Pin exact Compose labels, container image IDs and named mounts, not tags."""
    known: dict[tuple[str, str], dict] = {}
    volume_owner: dict[str, str] = {}
    for project in PROJECTS:
        stdout = run([
            "ps", "-a", "--filter", f"label=com.docker.compose.project={project}",
            "--format", "{{.ID}}",
        ])
        container_ids = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not container_ids or len(container_ids) > 30 or len(container_ids) != len(set(container_ids)):
            raise PreflightBlocked(f"{project}: missing, duplicate or excessive containers")
        for ident in container_ids:
            if not re.fullmatch(r"[a-f0-9]{12,64}", ident):
                raise PreflightBlocked("invalid Docker container identity")
            inspected = run([
                "inspect", "--format",
                '{{.Id}}|{{.Image}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}',
                ident,
            ]).split("|")
            if len(inspected) != 5:
                raise PreflightBlocked("ambiguous Docker Compose labels")
            container_id, image_id, got_project, service, status = inspected
            if not re.fullmatch(r"[a-f0-9]{64}", container_id) or not SHA_IMAGE.fullmatch(image_id):
                raise PreflightBlocked("Docker immutable image/container identity missing")
            if got_project != project or not re.fullmatch(r"[a-z0-9-]{1,64}", service):
                raise PreflightBlocked("Docker project/service identity mismatch")
            key = (project, service)
            if key in known:
                raise PreflightBlocked("duplicate Compose service identity")
            mounts = {}
            rows = run([
                "inspect", "--format",
                '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}{{println}}{{end}}',
                ident,
            ])
            for row in rows.splitlines():
                fields = row.split("|")
                if len(fields) != 3 or fields[2] in mounts:
                    raise PreflightBlocked("malformed or duplicate mount evidence")
                typ, name, target = fields
                if typ == "volume" and not VOLUME.fullmatch(name):
                    raise PreflightBlocked("invalid Docker volume identity")
                mounts[target] = {"type": typ, "name": name if typ == "volume" else None}
            known[key] = {
                "container_id_sha256": sha(container_id),
                "image_sha256": image_id.split(":", 1)[1],
                "status": status,
                "mounts": mounts,
            }

    receipt = {}
    for asset, (project, service, mount_target, expected_volume) in SOURCES.items():
        entry = known.get((project, service))
        if not entry:
            raise PreflightBlocked(f"{asset}: required Compose service missing")
        source = {
            "compose_project": project,
            "compose_service": service,
            "container_id_sha256": entry["container_id_sha256"],
            "image_sha256": entry["image_sha256"],
            "runtime_status": entry["status"],
            "capture_status": "unverified",
            "restore_status": "unverified",
            "disposition": "unclassified" if asset in ("central-ingestion-spool", "edge-mqtt-persistence") else "retain_required",
            "max_proposed_bytes": CAP_BYTES[asset],
        }
        if entry["status"] != "running":
            raise PreflightBlocked(f"{asset}: source container is not running")
        if mount_target is not None:
            mount = entry["mounts"].get(mount_target)
            if not mount or mount["type"] != "volume" or mount["name"] != expected_volume:
                raise PreflightBlocked(f"{asset}: missing, migrated or ambiguous protected volume")
            if expected_volume in volume_owner and volume_owner[expected_volume] != asset:
                raise PreflightBlocked("distinct stores map to the same named volume")
            volume_owner[expected_volume] = asset
            source["source_volume"] = expected_volume
        else:
            # No access to local-auth key bytes; a secret mount does NOT prove
            # both keys are present and matching. Capture remains unverified.
            source["secret_mount_presence"] = "unverified"
        receipt[asset] = source
    return receipt


def read_migration_authority(path: Path, vol_created_at: str, image_sha256: str) -> str:
    try:
        st = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_size > 1024 * 1024 or st.st_size <= 0:
            raise PreflightBlocked("migration authority is unsafe")
        raw = path.read_bytes()
        data = json.loads(raw)
    except PreflightBlocked:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise PreflightBlocked("migration authority missing or invalid") from exc
    if not isinstance(data, dict) or data.get("status") != "verified" or data.get("cutover_verified") is not True:
        raise PreflightBlocked("VersityGW cutover not verified")
    if data.get("target_volume_created_at") != vol_created_at:
        raise PreflightBlocked("VersityGW volume creation identity mismatch")
    if data.get("target_image_id") != f"sha256:{image_sha256}":
        raise PreflightBlocked("VersityGW immutable image authority mismatch")
    return sha(raw)


def probe_site(work: Path, destination: Path, authority: Path, run: Callable[[list[str]], str] = run_docker) -> dict:
    capacity = capacity_check(work, destination)
    assets = probe_sources(run)
    volume_name = assets["object-storage"]["source_volume"]
    created = run(["volume", "inspect", "--format", "{{.CreatedAt}}", volume_name])
    if not created or len(created) > 100:
        raise PreflightBlocked("VersityGW volume creation identity missing")
    authority_hash = read_migration_authority(authority, created, assets["object-storage"]["image_sha256"])
    assets["object-storage"]["migration_authority_sha256"] = authority_hash
    return {
        "schema_version": 2,
        "kind": "nexolab-site-dr-preflight",
        "profile": "LOCAL_LAN",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "assets": assets,
        "capacity": capacity,
        "source_inventory": "observed_read_only",
        "backup_capture": "not_performed",
        "encrypted_off_device_copy": "not_verified",
        "isolated_restore": "not_performed",
        "site_activation": "not_authorized",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=Path("/var/backups/nexolab"))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--migration-authority",
        type=Path,
        default=Path("runtime/object-storage-migration/authority.json"),
    )
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise PreflightBlocked("root required to validate protected backup directories")
        plan = probe_site(args.work_dir, args.destination, args.migration_authority)
    except PreflightBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "site_activation": "not_authorized"}))
        return 78
    print(json.dumps(plan, sort_keys=True))
    print("SITE_DR_PREFLIGHT=OBSERVED_READ_ONLY; CAPTURE=NO; RESTORE=NO; SITE_ACTIVATION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
