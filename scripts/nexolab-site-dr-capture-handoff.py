#!/usr/bin/env python3
"""#1439 source-only offline eight-store capture handoff gate.

It NEVER executes a backup, reads site assets or authorizes production action.
Operator-provided hashes/attestations are NOT independent proof of real custody.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import stat

GiB = 1024**3
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_FIELDS = {
    "schema_version", "kind", "profile", "site_id", "observed_at",
    "preflight_sha256", "source_device_sha256", "destination_device_sha256",
    "custody", "continuity", "assets",
}
CUSTODY_FIELDS = {
    "independent_physical_media_reviewed", "encrypted_off_device_destination_reviewed",
    "key_custody_separate_reviewed", "encryption", "key_source",
    "destination_review_sha256", "key_custody_review_sha256",
}
CONTINUITY_FIELDS = {
    "sampling_interval_seconds", "offline_core_reviewed", "outbox_high_water_reviewed",
    "legacy_minio_retained_reviewed", "versitygw_retained_reviewed",
    "no_modbus_hardware_writes", "consistency_review_sha256",
}
ASSET_FIELDS = {
    "id", "disposition", "consistency_method", "image_sha256",
    "container_id_sha256", "estimated_archive_bytes", "review_evidence_sha256",
}
METHODS = {
    "postgresql": "online_pg_dump_custom",
    "object-storage": "separately_approved_s3_quiesce",
    "mqtt-dynamic-security": "separately_approved_mqtt_quiesce",
    "edge-sqlite-outbox": "sqlite_online_backup_with_high_water",
    "local-auth-private-key": "protected_keypair_snapshot",
    "local-auth-public-key": "protected_keypair_snapshot",
    "central-ingestion-spool": "sqlite_online_backup_with_high_water",
    "edge-mqtt-persistence": "separately_approved_mqtt_quiesce",
}
SERVICES = {
    "postgresql": ("nexolab-central", "postgres"),
    "object-storage": ("nexolab-central", "minio"),
    "mqtt-dynamic-security": ("nexolab-central", "mqtt"),
    "edge-sqlite-outbox": ("nexolab-edge", "device-agent"),
    "local-auth-private-key": ("nexolab-central", "telemetry-service"),
    "local-auth-public-key": ("nexolab-central", "telemetry-service"),
    "central-ingestion-spool": ("nexolab-central", "telemetry-service"),
    "edge-mqtt-persistence": ("nexolab-edge", "mqtt"),
}
CAP_BYTES = {
    "postgresql": 4 * GiB,
    "object-storage": 4 * GiB,
    "mqtt-dynamic-security": GiB,
    "edge-sqlite-outbox": GiB,
    "local-auth-private-key": 1024 * 1024,
    "local-auth-public-key": 1024 * 1024,
    "central-ingestion-spool": 4 * GiB,
    "edge-mqtt-persistence": GiB,
}
VOLUMES = {
    "postgresql": "nexolab-central-postgres-data",
    "object-storage": "nexolab-central-object-storage-versitygw-data",
    "mqtt-dynamic-security": "nexolab-central-mqtt-data",
    "edge-sqlite-outbox": "nexolab-edge_edge-data",
    "central-ingestion-spool": "nexolab-central-telemetry-ingestion-data",
    "edge-mqtt-persistence": "nexolab-edge_mqtt-data",
}


class HandoffBlocked(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise HandoffBlocked(reason)


def keys(value: object, required: set[str], name: str) -> dict:
    require(isinstance(value, dict), f"{name}: expected object")
    require(set(value) == required, f"{name}: missing or unexpected fields")
    return value


def digest(value: object, name: str) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, f"{name}: invalid SHA-256")
    return value


def canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def timestamp(value: object) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "timestamp must be UTC")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffBlocked("timestamp malformed") from exc
    require(result.tzinfo == timezone.utc, "timestamp must use UTC")
    return result


def parse_offline_document(path: Path) -> dict:
    try:
        mode = path.lstat()
        require(stat.S_ISREG(mode.st_mode) and not path.is_symlink(), "untrusted or symlink document")
        require(0 < mode.st_size <= 131072, "oversized or empty document")
        require(stat.S_IMODE(mode.st_mode) & 0o077 == 0, "sensitive receipt must be mode 0600")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffBlocked("invalid offline input receipt") from exc
    require(isinstance(data, dict), "offline receipt must be JSON object")
    return data


def review(preflight: object, handoff: object) -> dict:
    p = keys(preflight, {
        "schema_version", "kind", "profile", "observed_at", "assets",
        "capacity", "source_inventory", "backup_capture",
        "encrypted_off_device_copy", "isolated_restore", "site_activation",
    }, "preflight")
    h = keys(handoff, RECEIPT_FIELDS, "handoff")
    require(p["schema_version"] == 2 and p["kind"] == "nexolab-site-dr-preflight", "preflight version")
    require(p["profile"] == "LOCAL_LAN" and h["profile"] == "LOCAL_LAN", "wrong runtime profile")
    require(h["schema_version"] == 1 and h["kind"] == "nexolab-site-capture-handoff", "wrong handoff version")
    require(h["site_id"] == "nexolab-edge-01", "site identity drift")
    require(p["source_inventory"] == "observed_read_only", "not observed from protected source")
    require(p["backup_capture"] == "not_performed", "unexpected live capture claim")
    require(p["encrypted_off_device_copy"] == "not_verified", "preflight cannot certify copy")
    require(p["isolated_restore"] == "not_performed" and p["site_activation"] == "not_authorized", "site activation forbidden")
    require(digest(h["preflight_sha256"], "preflight_sha256") == hashlib.sha256(canonical(p)).hexdigest(), "preflight hash mismatch")
    source_dt, handoff_dt = timestamp(p["observed_at"]), timestamp(h["observed_at"])
    require(source_dt <= handoff_dt <= source_dt + timedelta(minutes=30), "stale or future-dated handoff")
    source_device = digest(h["source_device_sha256"], "source_device_sha256")
    dest_device = digest(h["destination_device_sha256"], "destination_device_sha256")
    require(source_device != dest_device, "backup destination same device as source")

    capacity = keys(p["capacity"], {
        "working_free_bytes", "destination_free_bytes", "working_reserve_bytes",
        "working_staging_cap_bytes", "destination_minimum_bytes",
        "destination_physical_independence", "destination_key_custody",
    }, "capacity")
    for name in ("working_free_bytes", "destination_free_bytes", "working_reserve_bytes", "working_staging_cap_bytes", "destination_minimum_bytes"):
        require(type(capacity[name]) is int and capacity[name] >= 0, f"capacity.{name}: invalid bytes")
    require(capacity["working_free_bytes"] >= 24 * GiB, "less than protected 20 GiB + 4 GiB staging")
    require(capacity["destination_free_bytes"] >= 16 * GiB, "destination <16 GiB")
    require(capacity["working_reserve_bytes"] == 20 * GiB, "working reserve policy drift")
    require(capacity["working_staging_cap_bytes"] == 4 * GiB, "staging cap policy drift")
    require(capacity["destination_minimum_bytes"] == 16 * GiB, "destination minimum policy drift")
    require(capacity["destination_physical_independence"] == "unverified", "preflight must not claim physical independence")
    require(capacity["destination_key_custody"] == "unverified", "preflight must not claim key custody")

    custody = keys(h["custody"], CUSTODY_FIELDS, "custody")
    for field in ("independent_physical_media_reviewed", "encrypted_off_device_destination_reviewed", "key_custody_separate_reviewed"):
        require(custody[field] is True, f"{field}: separate operator review missing")
    require(custody["encryption"] == "aes-256-gcm", "AES-256-GCM required")
    require(custody["key_source"] == "mounted_file", "protected mounted key required")
    digest(custody["destination_review_sha256"], "destination_review_sha256")
    digest(custody["key_custody_review_sha256"], "key_custody_review_sha256")

    continuity = keys(h["continuity"], CONTINUITY_FIELDS, "continuity")
    require(type(continuity["sampling_interval_seconds"]) is int and continuity["sampling_interval_seconds"] == 10, "10-second sampling continuity not reviewed")
    for field in (
        "offline_core_reviewed", "outbox_high_water_reviewed",
        "legacy_minio_retained_reviewed", "versitygw_retained_reviewed",
        "no_modbus_hardware_writes",
    ):
        require(continuity[field] is True, f"{field}: protected operational continuity missing")
    digest(continuity["consistency_review_sha256"], "consistency_review_sha256")

    sources = keys(p["assets"], set(METHODS), "preflight assets")
    declared = h["assets"]
    require(isinstance(declared, list) and len(declared) == len(METHODS), "incomplete capture handoff")
    seen: set[str] = set()
    same_service: dict[tuple[str, str], tuple[str, str]] = {}
    total = 0
    for item in declared:
        require(isinstance(item, dict), "asset handoff must be object")
        ident = item.get("id")
        require(isinstance(ident, str) and ident in METHODS, "unknown capture asset")
        require(ident not in seen, "duplicate capture asset")
        seen.add(ident)
        entry = keys(item, ASSET_FIELDS, f"{ident} handoff")
        src_expected = {
            "compose_project", "compose_service", "container_id_sha256", "image_sha256",
            "runtime_status", "capture_status", "restore_status", "disposition",
            "max_proposed_bytes",
        }
        if ident in VOLUMES:
            src_expected = src_expected | {"source_volume"}
        else:
            src_expected = src_expected | {"secret_mount_presence"}
        if ident == "object-storage":
            src_expected = src_expected | {"migration_authority_sha256"}
        source = keys(sources[ident], src_expected, f"{ident} source")
        require(
            (source["compose_project"], source["compose_service"]) == SERVICES[ident],
            f"{ident}: Compose project/service drift",
        )
        container_identity = (source["container_id_sha256"], source["image_sha256"])
        service_key = SERVICES[ident]
        if service_key in same_service:
            require(same_service[service_key] == container_identity, f"{ident}: shared service identity drift")
        same_service[service_key] = container_identity
        require(source["max_proposed_bytes"] == CAP_BYTES[ident], f"{ident}: per-store cap policy drift")
        require(source["runtime_status"] == "running", f"{ident}: not running")
        require(source["capture_status"] == "unverified" and source["restore_status"] == "unverified", f"{ident}: false snapshot proof")
        require(source["disposition"] in ("unclassified", "retain_required"), f"{ident}: unrecognized source state")
        require(entry["disposition"] == "retain", f"{ident}: unclassified state or missing retention")
        require(entry["consistency_method"] == METHODS[ident], f"{ident}: wrong quiesce/online backup boundary")
        require(digest(entry["image_sha256"], f"{ident}.image") == digest(source["image_sha256"], f"{ident}.source_image"), f"{ident}: source image drift")
        require(digest(entry["container_id_sha256"], f"{ident}.container") == digest(source["container_id_sha256"], f"{ident}.source_container"), f"{ident}: container drift")
        digest(entry["review_evidence_sha256"], f"{ident}.review_evidence")
        if ident in VOLUMES:
            require(source["source_volume"] == VOLUMES[ident], f"{ident}: volume authority drift")
        else:
            require(source["secret_mount_presence"] == "unverified", "secret presence must not be inferred from Docker")
        if ident == "object-storage":
            digest(source["migration_authority_sha256"], "VersityGW migration authority")
        amount = entry["estimated_archive_bytes"]
        require(type(amount) is int and 0 < amount <= source["max_proposed_bytes"], f"{ident}: exceeds per-store bound")
        require(type(source["max_proposed_bytes"]) is int and source["max_proposed_bytes"] > 0, f"{ident}: invalid maximum")
        total += amount

    require(seen == set(METHODS), "incomplete store inventory")
    require(total <= capacity["destination_free_bytes"] - 2 * GiB, "aggregate archive exceeds destination headroom")
    return {
        "status": "STRUCTURAL_PLAN_READY_FOR_INDEPENDENT_REVIEW",
        "stores": len(METHODS),
        "proposed_archive_bytes": total,
        "source_observed": True,
        "encrypted_backup": "NOT_PERFORMED",
        "off_device_copy": "NOT_PERFORMED",
        "actual_isolated_restore": "NOT_PERFORMED",
        "hardware_acceptance": "UNVERIFIED",
        "production_capture": "NOT_AUTHORIZED",
        "site_activation": "NOT_AUTHORIZED",
        "operator_attestations": "NOT_INDEPENDENTLY_VERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = review(parse_offline_document(args.preflight), parse_offline_document(args.handoff))
    except HandoffBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "site_activation": "NOT_AUTHORIZED"}))
        return 78
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
