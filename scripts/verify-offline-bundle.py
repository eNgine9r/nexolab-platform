#!/usr/bin/env python3
"""Verify NEXOLAB offline bundle integrity and optionally loaded Docker images."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

IMAGE_ENV = {
    "dashboard": "OFFLINE_DASHBOARD_IMAGE",
    "telemetry-service": "OFFLINE_TELEMETRY_IMAGE",
    "device-agent": "OFFLINE_DEVICE_AGENT_IMAGE",
    "mqtt": "OFFLINE_MQTT_IMAGE",
    "postgres": "OFFLINE_POSTGRES_IMAGE",
    "minio": "OFFLINE_MINIO_IMAGE",
    "minio-client": "OFFLINE_MINIO_CLIENT_IMAGE",
}
REQUIRED_IMAGES = set(IMAGE_ENV)
AUTH_PROVIDERS = {"disabled", "local", "acceptance", "supabase"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(rb"ghp_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def verify_manifest(bundle_root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(manifest.get("schema_version") == 1, "Unsupported manifest schema")
    require(manifest.get("platform") in {"linux/amd64", "linux/arm64"}, "Unsupported platform")
    require(manifest.get("runtime_network_required") is False, "Bundle requires runtime network")
    require(manifest.get("paid_runtime_service_required") is False, "Bundle requires paid runtime")
    require(manifest.get("secrets_included") is False, "Manifest claims bundled secrets")
    management = manifest.get("version_management")
    require(isinstance(management, dict), "Missing version management contract")
    require(isinstance(management.get("bundle_id"), str) and management["bundle_id"], "Missing bundle ID")
    schema = management.get("database_schema")
    require(isinstance(schema, dict), "Missing database schema compatibility")
    require(isinstance(schema.get("head"), str) and schema["head"], "Missing schema head")
    for field in ("upgrade_from", "runtime_compatible_schema_heads"):
        require(
            isinstance(schema.get(field), list)
            and bool(schema[field])
            and all(isinstance(value, str) and value for value in schema[field]),
            f"Invalid database schema field: {field}",
        )
    require(management.get("backup_required") is True, "Version update does not require backup")
    require(management.get("migration_before_readiness") is True, "Migration ordering is unsafe")
    require(management.get("preserve_named_volumes") is True, "Named volumes are not preserved")
    require(management.get("preserve_edge_sqlite") is True, "Edge SQLite is not preserved")

    dashboard = manifest.get("dashboard")
    require(isinstance(dashboard, dict), "Missing dashboard configuration")
    auth_provider = dashboard.get("auth_provider")
    require(auth_provider in AUTH_PROVIDERS, "Unsupported dashboard auth provider")

    local_auth = manifest.get("local_auth")
    require(isinstance(local_auth, dict), "Missing local_auth contract")
    require(local_auth.get("supported") is True, "Bundle does not support local authentication")
    require(local_auth.get("secrets_packaged") is False, "Local auth secrets must not be packaged")
    require(
        local_auth.get("selected") is (auth_provider == "local"),
        "Local auth selection does not match dashboard provider",
    )
    overlay_relative = str(local_auth.get("compose_overlay", ""))
    require(overlay_relative, "Missing local auth Compose overlay path")
    require(
        (bundle_root / overlay_relative).is_file(),
        f"Missing local auth Compose overlay: {overlay_relative}",
    )

    archive = manifest.get("images_archive")
    require(isinstance(archive, dict), "Missing images_archive")
    archive_path = bundle_root / str(archive.get("path", ""))
    require(archive_path.is_file(), f"Missing image archive: {archive_path}")
    require(SHA256_PATTERN.fullmatch(str(archive.get("sha256", ""))) is not None, "Invalid archive digest")
    require(sha256(archive_path) == archive["sha256"], "Image archive checksum mismatch")
    require(archive_path.stat().st_size == archive.get("size_bytes"), "Image archive size mismatch")

    images_payload = manifest.get("images")
    require(isinstance(images_payload, list), "Missing image inventory")
    images: dict[str, dict[str, Any]] = {}
    for image in images_payload:
        require(isinstance(image, dict), "Invalid image record")
        logical_id = str(image.get("id", ""))
        require(logical_id not in images, f"Duplicate image id: {logical_id}")
        require(IMAGE_ID_PATTERN.fullmatch(str(image.get("image_id", ""))) is not None, f"Invalid image ID: {logical_id}")
        require(image.get("platform") == manifest["platform"], f"Platform mismatch: {logical_id}")
        require(isinstance(image.get("reference"), str) and image["reference"], f"Missing image reference: {logical_id}")
        sbom = image.get("sbom")
        require(isinstance(sbom, dict), f"Missing SBOM record: {logical_id}")
        for format_name in ("cyclonedx", "spdx"):
            evidence = sbom.get(format_name)
            require(isinstance(evidence, dict), f"Missing {format_name} SBOM: {logical_id}")
            evidence_path = bundle_root / str(evidence.get("path", ""))
            require(evidence_path.is_file(), f"Missing SBOM file: {evidence_path}")
            require(sha256(evidence_path) == evidence.get("sha256"), f"SBOM checksum mismatch: {evidence_path}")
        images[logical_id] = image

    require(set(images) == REQUIRED_IMAGES, f"Image inventory mismatch: {sorted(images)}")

    files_payload = manifest.get("files")
    require(isinstance(files_payload, list), "Missing files inventory")
    seen_paths: set[str] = set()
    for record in files_payload:
        require(isinstance(record, dict), "Invalid file record")
        relative = str(record.get("path", ""))
        require(relative and relative not in seen_paths, f"Duplicate/empty file path: {relative}")
        seen_paths.add(relative)
        path = bundle_root / relative
        require(path.is_file(), f"Missing bundle file: {relative}")
        require(path.stat().st_size == record.get("size_bytes"), f"Size mismatch: {relative}")
        require(sha256(path) == record.get("sha256"), f"Checksum mismatch: {relative}")
    require(overlay_relative in seen_paths, "Local auth Compose overlay is not in the file inventory")

    policy = manifest.get("persistent_data_policy")
    require(isinstance(policy, dict), "Missing persistent data policy")
    require(policy.get("packaged") is False, "Persistent data must not be packaged")
    require(policy.get("delete_volumes") is False, "Bundle allows volume deletion")
    require(policy.get("compose_down_v_allowed") is False, "Bundle allows docker compose down -v")
    return images


def verify_checksum_file(bundle_root: Path) -> None:
    checksum_path = bundle_root / "SHA256SUMS"
    require(checksum_path.is_file(), "Missing SHA256SUMS")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, separator, relative = line.partition("  ")
        require(bool(separator), f"Invalid SHA256SUMS line: {line}")
        require(SHA256_PATTERN.fullmatch(expected) is not None, f"Invalid checksum: {line}")
        path = bundle_root / relative
        require(path.is_file(), f"Missing checksummed file: {relative}")
        require(sha256(path) == expected, f"SHA256SUMS mismatch: {relative}")


def reject_secret_material(bundle_root: Path) -> None:
    forbidden_names = {".env", ".env.central", ".env.edge", "id_rsa", "id_ed25519"}
    for path in bundle_root.rglob("*"):
        if not path.is_file():
            continue
        require(path.name not in forbidden_names, f"Forbidden secret/config file in bundle: {path}")
        if path.suffix in {".tar", ".gz", ".zip"} or path.stat().st_size > 2 * 1024 * 1024:
            continue
        content = path.read_bytes()
        for pattern in SECRET_PATTERNS:
            require(pattern.search(content) is None, f"Secret-like material found in {path}")


def inspect_loaded_images(images: dict[str, dict[str, Any]]) -> None:
    for logical_id, image in sorted(images.items()):
        result = subprocess.run(
            ["docker", "image", "inspect", image["reference"], "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
        )
        require(result.returncode == 0, f"Image is not loaded: {image['reference']}")
        require(result.stdout.strip() == image["image_id"], f"Loaded image ID mismatch: {logical_id}")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def emit_shell_env(images: dict[str, dict[str, Any]]) -> None:
    for logical_id, variable in IMAGE_ENV.items():
        print(f"export {variable}={shell_quote(images[logical_id]['reference'])}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--check-loaded-images", action="store_true")
    parser.add_argument("--emit-shell-env", action="store_true")
    args = parser.parse_args()

    bundle_root = args.bundle_root.resolve()
    require(bundle_root.is_dir(), f"Bundle directory does not exist: {bundle_root}")
    manifest = load_json(bundle_root / "manifest.json")
    images = verify_manifest(bundle_root, manifest)
    verify_checksum_file(bundle_root)
    reject_secret_material(bundle_root)
    if args.check_loaded_images:
        inspect_loaded_images(images)
    if args.emit_shell_env:
        emit_shell_env(images)
    else:
        print(
            json.dumps(
                {
                    "status": "verified",
                    "bundle_version": manifest["bundle_version"],
                    "platform": manifest["platform"],
                    "auth_provider": manifest["dashboard"]["auth_provider"],
                    "images": len(images),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"offline bundle verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
