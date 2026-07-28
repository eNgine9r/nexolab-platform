from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "security" / "disaster-recovery-assets.json"
MODULE_PATH = ROOT / "scripts" / "nexolab-backup-bundle.py"
SPEC = importlib.util.spec_from_file_location(
    "nexolab_backup_bundle_archive_validation",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_key(path: Path) -> Path:
    path.write_bytes(bytes(range(32)))
    path.chmod(0o600)
    return path


def tar_with_entries(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in entries:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def encrypted_archive(tmp_path: Path, archive: bytes) -> tuple[Path, Path]:
    key = write_key(tmp_path / "crafted.key")
    header = {
        "schema_version": 1,
        "format": "nexolab-dr-v1",
        "encryption": "aes-256-gcm",
        "repository": "eNgine9r/nexolab-platform",
        "commit": "b" * 40,
        "created_at": "2026-07-28T08:00:00Z",
        "nonce": base64.b64encode(bytes(range(12))).decode("ascii"),
    }
    bundle = tmp_path / "crafted.nxl"
    bundle.write_bytes(MODULE.encrypt_archive(archive, key.read_bytes(), header))
    bundle.chmod(0o600)
    return key, bundle


def crafted_manifest(files: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "format": "nexolab-dr-v1",
        "repository": "eNgine9r/nexolab-platform",
        "commit": "b" * 40,
        "created_at": "2026-07-28T08:00:00Z",
        "files": files,
        "assets": [],
    }


def test_authenticated_duplicate_archive_entry_is_rejected(tmp_path: Path) -> None:
    manifest = MODULE.canonical_json(crafted_manifest([])) + b"\n"
    archive = tar_with_entries(
        [("manifest.json", manifest), ("manifest.json", manifest)]
    )
    key, bundle = encrypted_archive(tmp_path, archive)

    with pytest.raises(MODULE.BundleFailure, match="duplicate archive entry"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )


def test_authenticated_missing_declared_entry_is_rejected(tmp_path: Path) -> None:
    manifest = crafted_manifest(
        [
            {
                "path": "postgresql/nexolab.dump",
                "size": 7,
                "sha256": MODULE.sha256_bytes(b"payload"),
            }
        ]
    )
    archive = tar_with_entries(
        [("manifest.json", MODULE.canonical_json(manifest) + b"\n")]
    )
    key, bundle = encrypted_archive(tmp_path, archive)

    with pytest.raises(MODULE.BundleFailure, match="missing declared file"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )


def test_authenticated_unexpected_entry_is_rejected(tmp_path: Path) -> None:
    payload = b"payload"
    manifest = crafted_manifest(
        [
            {
                "path": "postgresql/nexolab.dump",
                "size": len(payload),
                "sha256": MODULE.sha256_bytes(payload),
            }
        ]
    )
    archive = tar_with_entries(
        [
            ("manifest.json", MODULE.canonical_json(manifest) + b"\n"),
            ("postgresql/nexolab.dump", payload),
            ("unexpected.txt", b"blocked"),
        ]
    )
    key, bundle = encrypted_archive(tmp_path, archive)

    with pytest.raises(MODULE.BundleFailure, match="unexpected files"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )
