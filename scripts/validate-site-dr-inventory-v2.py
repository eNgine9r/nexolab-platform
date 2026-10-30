#!/usr/bin/env python3
"""Offline, fail-closed NEXOLAB site recovery inventory contract (Issue #1433).

Structural/attestation gate ONLY; never reads production sources or performs backup.
Successful validation is NOT proof of real hardware, off-device custody or restore.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
GiB = 1024**3

# The v1 five-asset policy remains untouched: this is an additive site receipt.
# Auxiliary ingestion and edge MQTT MUST be classified, not silently discarded.
REQUIRED = {
    "postgresql": ("postgres", "logical_snapshot", "pg_custom"),
    "object-storage": ("minio", "application_quiesce", "object_tree"),
    "mqtt-dynamic-security": ("mqtt", "service_quiesce", "deterministic_tar"),
    "edge-sqlite-outbox": ("device-agent", "online_sqlite_backup", "sqlite_backup"),
    "local-auth-private-key": ("telemetry-service", "operator_secret_snapshot", "pem"),
    "local-auth-public-key": ("telemetry-service", "operator_secret_snapshot", "pem"),
    "central-ingestion-spool": ("telemetry-service", "online_sqlite_backup", "sqlite_backup"),
    "edge-mqtt-persistence": ("edge-mqtt", "service_quiesce", "deterministic_tar"),
}
REBUILDABLE = {"central-ingestion-spool", "edge-mqtt-persistence"}
NO_VOLUME = {"local-auth-private-key", "local-auth-public-key"}
FIELDS = {
    "schema_version", "kind", "profile", "site_id", "release_commit",
    "capture_id", "observed_at", "v1_bundle_format", "storage", "assets",
}
STORAGE_FIELDS = {
    "encrypted_bundle_sha256", "encrypted_manifest_sha256", "encryption",
    "key_source", "independent_key_custody_verified",
    "off_device_copy_verified", "source_disk_independent",
    "destination_kind", "destination_identity_sha256", "free_after_bytes",
    "isolated_restore_verified", "restore_target_kind",
    "restore_target_identity_sha256", "restore_receipt_sha256",
}
SOURCE_FIELDS = {
    "compose_service", "image_sha256", "source_identity_sha256",
    "authority_sha256", "observed_at",
}
CAPTURE_FIELDS = {
    "status", "format", "consistency_boundary", "sha256", "bytes",
    "captured_at", "consistency_group_sha256",
}
RESTORE_FIELDS = {
    "status", "receipt_sha256", "new_target", "source_untouched",
    "verification_sha256",
}


class InventoryError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def object_keys(value: object, expected: set[str], name: str) -> dict:
    require(isinstance(value, dict), f"{name}: expected object")
    require(set(value) == expected, f"{name}: missing or unexpected keys")
    return value


def digest(value: object, name: str) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, f"{name}: invalid SHA-256")
    return value


def utc_timestamp(value: object, name: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{name}: expected UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryError(f"{name}: invalid timestamp") from exc
    require(parsed.tzinfo == timezone.utc, f"{name}: UTC required")
    return parsed


def safe_name(value: object, name: str) -> str:
    require(isinstance(value, str) and SAFE_ID.fullmatch(value) is not None, f"{name}: invalid ID")
    return value


def validate_site_inventory(value: object) -> None:
    inventory = object_keys(value, FIELDS, "inventory")
    require(type(inventory["schema_version"]) is int and inventory["schema_version"] == 2, "schema_version must be 2")
    require(inventory["kind"] == "nexolab-site-dr-inventory", "invalid inventory kind")
    require(inventory["profile"] == "LOCAL_LAN", "profile must be LOCAL_LAN")
    require(inventory["v1_bundle_format"] == "nexolab-dr-v1", "v1 bundle compatibility missing")
    safe_name(inventory["site_id"], "site_id")
    safe_name(inventory["capture_id"], "capture_id")
    require(isinstance(inventory["release_commit"], str) and COMMIT.fullmatch(inventory["release_commit"]) is not None, "invalid release commit")
    utc_timestamp(inventory["observed_at"], "observed_at")

    storage = object_keys(inventory["storage"], STORAGE_FIELDS, "storage")
    for name in (
        "encrypted_bundle_sha256", "encrypted_manifest_sha256",
        "destination_identity_sha256", "restore_target_identity_sha256",
        "restore_receipt_sha256",
    ):
        digest(storage[name], f"storage.{name}")
    require(storage["encryption"] == "aes-256-gcm", "encryption must be AES-256-GCM")
    require(storage["key_source"] == "mounted_file", "key_source must be mounted_file")
    for name in (
        "independent_key_custody_verified", "off_device_copy_verified",
        "source_disk_independent", "isolated_restore_verified",
    ):
        require(storage[name] is True, f"storage.{name}: verification missing")
    require(storage["destination_kind"] in ("dedicated_media", "independent_host"), "backup destination not independent")
    require(storage["restore_target_kind"] == "isolated_host", "restoration must use isolated host")
    require(
        isinstance(storage["free_after_bytes"], int)
        and not isinstance(storage["free_after_bytes"], bool)
        and storage["free_after_bytes"] >= 20 * GiB,
        "less than 20 GiB protected free reserve",
    )
    require(
        storage["destination_identity_sha256"] != storage["restore_target_identity_sha256"],
        "backup and restore targets must be independent",
    )

    assets = inventory["assets"]
    require(isinstance(assets, list) and len(assets) == len(REQUIRED), "incomplete or unexpected asset inventory")
    seen: set[str] = set()
    group: str | None = None
    auth_pair: list[str] = []

    for asset in assets:
        require(isinstance(asset, dict), "asset must be object")
        identifier = asset.get("id")
        require(isinstance(identifier, str) and identifier in REQUIRED, "unrecognized protected asset")
        require(identifier not in seen, f"duplicate asset {identifier}")
        seen.add(identifier)
        service, boundary, fmt = REQUIRED[identifier]
        disposition = asset.get("disposition")
        require(disposition in ("retain", "proven_rebuildable"), f"{identifier}: unclassified data")
        if disposition == "proven_rebuildable":
            require(identifier in REBUILDABLE, f"{identifier}: asset cannot be discarded")
            object_keys(asset, {"id", "disposition", "source", "rebuild_proof_sha256"}, identifier)
            digest(asset["rebuild_proof_sha256"], f"{identifier}.rebuild_proof_sha256")
        else:
            object_keys(asset, {"id", "disposition", "source", "capture", "restore"} | ({"storage_backend"} if identifier == "object-storage" else set()), identifier)
        src_fields = SOURCE_FIELDS if identifier in NO_VOLUME else SOURCE_FIELDS | {"source_volume"}
        source = object_keys(asset["source"], src_fields, f"{identifier}.source")
        require(source["compose_service"] == service, f"{identifier}: service identity mismatch")
        for name in ("image_sha256", "source_identity_sha256", "authority_sha256"):
            digest(source[name], f"{identifier}.source.{name}")
        utc_timestamp(source["observed_at"], f"{identifier}.source.observed_at")
        if identifier not in NO_VOLUME:
            volume = source["source_volume"]
            require(
                isinstance(volume, str)
                and len(volume) < 129
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", volume) is not None,
                f"{identifier}: invalid source volume",
            )
        if identifier == "object-storage":
            require(
                source["source_volume"].endswith("-object-storage-versitygw-data"),
                "VersityGW source volume not migrated or unverified",
            )
            require(
                asset.get("storage_backend") == "versitygw",
                "object-storage: backend identity mismatch",
            )
            if disposition == "retain":
                object_keys(
                    asset, {"id", "disposition", "source", "capture", "restore", "storage_backend"},
                    identifier,
                )
        elif "storage_backend" in asset:
            raise InventoryError(f"{identifier}: unexpected storage backend")

        if disposition == "proven_rebuildable":
            continue

        capture = object_keys(asset["capture"], CAPTURE_FIELDS, f"{identifier}.capture")
        restore = object_keys(asset["restore"], RESTORE_FIELDS, f"{identifier}.restore")
        require(capture["status"] == "verified", f"{identifier}: capture unverified")
        require(capture["format"] == fmt, f"{identifier}: capture format mismatch")
        require(capture["consistency_boundary"] == boundary, f"{identifier}: consistency boundary mismatch")
        digest(capture["sha256"], f"{identifier}.capture.sha256")
        digest(capture["consistency_group_sha256"], f"{identifier}.capture.consistency_group_sha256")
        require(
            type(capture["bytes"]) is int and capture["bytes"] > 0,
            f"{identifier}: missing archive bytes",
        )
        utc_timestamp(capture["captured_at"], f"{identifier}.capture.captured_at")
        if group is None:
            group = capture["consistency_group_sha256"]
        require(group == capture["consistency_group_sha256"], "cross-store consistency proof mismatch")
        require(restore["status"] == "verified", f"{identifier}: no isolated restore")
        require(restore["new_target"] is True and restore["source_untouched"] is True, f"{identifier}: unsafe restore target")
        digest(restore["receipt_sha256"], f"{identifier}.restore.receipt_sha256")
        digest(restore["verification_sha256"], f"{identifier}.restore.verification_sha256")
        if identifier in NO_VOLUME:
            auth_pair.append(restore["verification_sha256"])

    require(seen == set(REQUIRED), "required site assets missing")
    require(group is not None, "no retained data captures")
    require(len(auth_pair) == 2 and auth_pair[0] == auth_pair[1], "local-auth keypair verification mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.inventory.read_text(encoding="utf-8"))
        validate_site_inventory(data)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"SITE_DR_V2_STRUCTURAL_GATE=BLOCKED ({type(exc).__name__}: {exc})")
        return 78
    print("SITE_DR_V2_STRUCTURAL_GATE=PASS")
    print("SITE_DR_V2_RUNTIME_EVIDENCE=NOT_INDEPENDENTLY_VERIFIED")
    print("SITE_DR_V2_SITE_ACTIVATION=NOT_AUTHORIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
