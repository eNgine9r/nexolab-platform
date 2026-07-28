#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


REQUIRED_ASSETS = {
    "postgresql": ("postgresql", "pg_custom", "logical_snapshot"),
    "object-storage": ("s3_bucket", "object_tree", "application_quiesce"),
    "mqtt-dynamic-security": (
        "docker_volume",
        "deterministic_tar",
        "service_quiesce",
    ),
}
ALLOWED_BUNDLE_FORMATS = {"nexolab-dr-v1"}
ALLOWED_ENCRYPTION = {"aes-256-gcm"}
ALLOWED_KEY_SOURCES = {"mounted_file"}
SAFE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_SERVICE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*-$")
FORBIDDEN_KEYS = {
    "password",
    "secret",
    "token",
    "private_key",
    "access_key",
    "encryption_key",
    "command",
    "restore_command",
    "backup_command",
}


class ValidationFailure(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise ValidationFailure("disaster-recovery policy must be a JSON object")
    return payload


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailure(f"{label} is required")
    return value.strip()


def validate_relative_path(value: Any, label: str) -> str:
    text = require_text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or text.startswith("./"):
        raise ValidationFailure(f"{label} must be a canonical relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationFailure(f"{label} contains an unsafe path component")
    if "\\" in text or "\x00" in text:
        raise ValidationFailure(f"{label} contains an unsafe character")
    return text


def validate_absolute_path(value: Any, label: str) -> str:
    text = require_text(value, label)
    path = PurePosixPath(text)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ValidationFailure(f"{label} must be a canonical absolute path")
    if "\\" in text or "\x00" in text:
        raise ValidationFailure(f"{label} contains an unsafe character")
    return text


def reject_sensitive_keys(value: Any, path: str = "policy") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_KEYS:
                raise ValidationFailure(
                    f"{path}.{key} is forbidden in the versioned recovery policy"
                )
            reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_sensitive_keys(nested, f"{path}[{index}]")


def validate_bundle(bundle: Any) -> None:
    if not isinstance(bundle, dict):
        raise ValidationFailure("bundle must be an object")
    if bundle.get("format") not in ALLOWED_BUNDLE_FORMATS:
        raise ValidationFailure("bundle.format is unsupported")
    if bundle.get("encryption") not in ALLOWED_ENCRYPTION:
        raise ValidationFailure("bundle.encryption is unsupported")
    if bundle.get("key_source") not in ALLOWED_KEY_SOURCES:
        raise ValidationFailure("bundle.key_source must be mounted_file")
    paths = [
        validate_relative_path(bundle.get("manifest"), "bundle.manifest"),
        validate_relative_path(bundle.get("archive"), "bundle.archive"),
        validate_relative_path(
            bundle.get("encrypted_archive"), "bundle.encrypted_archive"
        ),
    ]
    if len(paths) != len(set(paths)):
        raise ValidationFailure("bundle output paths must be unique")
    if not paths[-1].endswith(".nxl"):
        raise ValidationFailure("bundle.encrypted_archive must use the .nxl suffix")


def validate_objectives(objectives: Any) -> None:
    if not isinstance(objectives, dict):
        raise ValidationFailure("objectives must be an object")
    required = {
        "software_rpo_seconds",
        "software_backup_target_seconds",
        "software_restore_target_seconds",
    }
    if set(objectives) != required:
        raise ValidationFailure("objectives must contain exactly the required targets")
    rpo = objectives["software_rpo_seconds"]
    backup = objectives["software_backup_target_seconds"]
    restore = objectives["software_restore_target_seconds"]
    if not isinstance(rpo, int) or isinstance(rpo, bool) or rpo < 0:
        raise ValidationFailure("software_rpo_seconds must be a non-negative integer")
    for label, value in (
        ("software_backup_target_seconds", backup),
        ("software_restore_target_seconds", restore),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValidationFailure(f"{label} must be a positive integer")


def validate_asset(asset: Any, index: int) -> tuple[str, int, str, list[str]]:
    label = f"assets[{index}]"
    if not isinstance(asset, dict):
        raise ValidationFailure(f"{label} must be an object")
    asset_id = require_text(asset.get("id"), f"{label}.id")
    if not SAFE_ID.fullmatch(asset_id):
        raise ValidationFailure(f"{label}.id is invalid")
    if asset_id not in REQUIRED_ASSETS:
        raise ValidationFailure(f"{label}.id is not a required recovery asset")
    expected_kind, expected_format, expected_boundary = REQUIRED_ASSETS[asset_id]
    if asset.get("kind") != expected_kind:
        raise ValidationFailure(f"{label}.kind does not match {asset_id}")
    if asset.get("backup_format") != expected_format:
        raise ValidationFailure(f"{label}.backup_format does not match {asset_id}")
    if asset.get("consistency_boundary") != expected_boundary:
        raise ValidationFailure(
            f"{label}.consistency_boundary does not match {asset_id}"
        )
    if asset.get("required") is not True:
        raise ValidationFailure(f"{label}.required must be true")

    service = require_text(asset.get("source_service"), f"{label}.source_service")
    if not SAFE_SERVICE.fullmatch(service):
        raise ValidationFailure(f"{label}.source_service is invalid")
    source_volume = require_text(asset.get("source_volume"), f"{label}.source_volume")
    if not SAFE_VOLUME.fullmatch(source_volume):
        raise ValidationFailure(f"{label}.source_volume is invalid")
    validate_absolute_path(asset.get("source_path"), f"{label}.source_path")
    backup_path = validate_relative_path(
        asset.get("backup_path"), f"{label}.backup_path"
    )

    restore_prefix = require_text(
        asset.get("restore_volume_prefix"), f"{label}.restore_volume_prefix"
    )
    if not SAFE_PREFIX.fullmatch(restore_prefix):
        raise ValidationFailure(f"{label}.restore_volume_prefix is invalid")
    if source_volume.startswith(restore_prefix) or restore_prefix.startswith(
        source_volume
    ):
        raise ValidationFailure(
            f"{label}.restore_volume_prefix overlaps the source volume"
        )

    restore_order = asset.get("restore_order")
    if (
        not isinstance(restore_order, int)
        or isinstance(restore_order, bool)
        or restore_order <= 0
    ):
        raise ValidationFailure(f"{label}.restore_order must be positive")

    verification = asset.get("verification")
    if (
        not isinstance(verification, list)
        or not verification
        or any(not isinstance(item, str) or not SAFE_ID.fullmatch(item) for item in verification)
    ):
        raise ValidationFailure(f"{label}.verification must contain safe identifiers")
    if len(verification) != len(set(verification)):
        raise ValidationFailure(f"{label}.verification contains duplicates")

    paths = [backup_path]
    metadata_path = asset.get("metadata_path")
    if asset_id == "object-storage":
        bucket = require_text(asset.get("bucket"), f"{label}.bucket")
        if not SAFE_VOLUME.fullmatch(bucket):
            raise ValidationFailure(f"{label}.bucket is invalid")
        paths.append(validate_relative_path(metadata_path, f"{label}.metadata_path"))
    elif metadata_path is not None or asset.get("bucket") is not None:
        raise ValidationFailure(
            f"{label}.bucket and metadata_path are valid only for object storage"
        )
    return asset_id, restore_order, source_volume, paths


def validate_policy(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    reject_sensitive_keys(payload)
    if payload.get("schema_version") != 1:
        raise ValidationFailure("schema_version must be 1")
    validate_bundle(payload.get("bundle"))
    validate_objectives(payload.get("objectives"))

    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) != len(REQUIRED_ASSETS):
        raise ValidationFailure("assets must contain exactly the required recovery set")

    ids: list[str] = []
    orders: list[int] = []
    volumes: list[str] = []
    output_paths: list[str] = []
    for index, asset in enumerate(assets):
        asset_id, order, volume, paths = validate_asset(asset, index)
        ids.append(asset_id)
        orders.append(order)
        volumes.append(volume)
        output_paths.extend(paths)

    if set(ids) != set(REQUIRED_ASSETS) or len(ids) != len(set(ids)):
        raise ValidationFailure("assets must contain each required ID exactly once")
    if len(orders) != len(set(orders)):
        raise ValidationFailure("restore_order values must be unique")
    if orders != sorted(orders):
        raise ValidationFailure("assets must be declared in restore_order")
    if len(volumes) != len(set(volumes)):
        raise ValidationFailure("source volumes must be unique")
    if len(output_paths) != len(set(output_paths)):
        raise ValidationFailure("asset backup paths must be unique")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("security/disaster-recovery-assets.json"),
    )
    args = parser.parse_args()
    payload = validate_policy(args.policy)
    print(
        "Disaster-recovery policy passed: "
        f"{len(payload['assets'])} required assets, "
        f"format={payload['bundle']['format']}, "
        f"encryption={payload['bundle']['encryption']}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationFailure as exc:
        print(f"Disaster-recovery policy failed: {exc}")
        raise SystemExit(1) from exc
