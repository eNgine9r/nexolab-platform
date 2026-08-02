from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "security" / "disaster-recovery-assets.json"
MODULE_PATH = ROOT / "scripts" / "nexolab-backup-bundle.py"
SPEC = importlib.util.spec_from_file_location("nexolab_backup_bundle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_key(path: Path, content: bytes | None = None) -> Path:
    path.write_bytes(content or bytes(range(32)))
    path.chmod(0o600)
    return path


def write_payload(root: Path) -> Path:
    payload = root / "payload"
    (payload / "postgresql").mkdir(parents=True)
    (payload / "postgresql" / "nexolab.dump").write_bytes(b"postgres-custom-dump")
    objects = payload / "object-storage" / "objects"
    (objects / "equipment").mkdir(parents=True)
    (objects / "equipment" / "image.bin").write_bytes(b"private-object-bytes")
    (payload / "object-storage" / "objects.json").write_text(
        json.dumps(
            [
                {
                    "key": "equipment/image.bin",
                    "size": 20,
                    "etag": "example-etag",
                    "sha256": "example-sha256",
                }
            ]
        ),
        encoding="utf-8",
    )
    (payload / "mqtt").mkdir(parents=True)
    (payload / "mqtt" / "mosquitto-data.tar").write_bytes(b"mqtt-volume-tar")
    (payload / "local-auth").mkdir(parents=True)
    private_key = payload / "local-auth" / "private.pem"
    public_key = payload / "local-auth" / "public.pem"
    private_key.write_bytes(b"local-auth-private-key-fixture")
    public_key.write_bytes(b"local-auth-public-key-fixture")
    private_key.chmod(0o600)
    public_key.chmod(0o644)
    return payload


def create_bundle(tmp_path: Path) -> tuple[Path, Path, Path]:
    payload = write_payload(tmp_path)
    key = write_key(tmp_path / "backup.key")
    bundle = tmp_path / "backup.nxl"
    MODULE.create_bundle(
        payload_dir=payload,
        key_file=key,
        output=bundle,
        policy_path=POLICY_PATH,
        repository="eNgine9r/nexolab-platform",
        commit="a" * 40,
        created_at="2026-07-28T08:00:00Z",
    )
    return payload, key, bundle


def test_create_verify_and_extract_round_trip(tmp_path: Path) -> None:
    payload, key, bundle = create_bundle(tmp_path)

    manifest, files = MODULE.verify_bundle(
        bundle=bundle,
        key_file=key,
        policy_path=POLICY_PATH,
    )

    assert manifest["commit"] == "a" * 40
    assert manifest["created_at"] == "2026-07-28T08:00:00Z"
    assert [asset["id"] for asset in manifest["assets"]] == [
        "postgresql",
        "object-storage",
        "mqtt-dynamic-security",
        "local-auth-private-key",
        "local-auth-public-key",
    ]
    assert set(files) == {
        "postgresql/nexolab.dump",
        "object-storage/objects/equipment/image.bin",
        "object-storage/objects.json",
        "mqtt/mosquitto-data.tar",
        "local-auth/private.pem",
        "local-auth/public.pem",
    }

    restored = tmp_path / "restored"
    MODULE.extract_bundle(
        bundle=bundle,
        key_file=key,
        policy_path=POLICY_PATH,
        output_dir=restored,
    )

    for source in payload.rglob("*"):
        if source.is_file():
            relative = source.relative_to(payload)
            assert (restored / relative).read_bytes() == source.read_bytes()
    assert (restored / "manifest.json").is_file()
    assert stat_mode(bundle) == 0o600


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_wrong_key_fails_authentication(tmp_path: Path) -> None:
    _, _, bundle = create_bundle(tmp_path)
    wrong_key = write_key(tmp_path / "wrong.key", os.urandom(32))

    with pytest.raises(MODULE.BundleFailure, match="authentication failed"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=wrong_key,
            policy_path=POLICY_PATH,
        )


def test_ciphertext_tamper_fails_authentication(tmp_path: Path) -> None:
    _, key, bundle = create_bundle(tmp_path)
    content = bytearray(bundle.read_bytes())
    content[-1] ^= 0x01
    bundle.write_bytes(content)

    with pytest.raises(MODULE.BundleFailure, match="authentication failed"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )


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


def test_authenticated_path_traversal_archive_is_rejected(tmp_path: Path) -> None:
    archive = tar_with_entries([("../escape", b"payload")])
    key, bundle = encrypted_archive(tmp_path, archive)

    with pytest.raises(MODULE.BundleFailure, match="archive entry is unsafe"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )


def test_authenticated_component_hash_drift_is_rejected(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "format": "nexolab-dr-v1",
        "repository": "eNgine9r/nexolab-platform",
        "commit": "b" * 40,
        "created_at": "2026-07-28T08:00:00Z",
        "files": [
            {
                "path": "postgresql/nexolab.dump",
                "size": 7,
                "sha256": "0" * 64,
            }
        ],
        "assets": [],
    }
    archive = tar_with_entries(
        [
            ("manifest.json", MODULE.canonical_json(manifest) + b"\n"),
            ("postgresql/nexolab.dump", b"changed"),
        ]
    )
    key, bundle = encrypted_archive(tmp_path, archive)

    with pytest.raises(MODULE.BundleFailure, match="hash mismatch"):
        MODULE.verify_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
        )


def test_payload_symlink_is_rejected(tmp_path: Path) -> None:
    payload = write_payload(tmp_path)
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    (payload / "object-storage" / "objects" / "link").symlink_to(target)
    key = write_key(tmp_path / "backup.key")

    with pytest.raises(MODULE.BundleFailure, match="payload symlink is forbidden"):
        MODULE.create_bundle(
            payload_dir=payload,
            key_file=key,
            output=tmp_path / "backup.nxl",
            policy_path=POLICY_PATH,
            repository="eNgine9r/nexolab-platform",
            commit="a" * 40,
        )


def test_missing_required_asset_is_rejected(tmp_path: Path) -> None:
    payload = write_payload(tmp_path)
    (payload / "mqtt" / "mosquitto-data.tar").unlink()
    key = write_key(tmp_path / "backup.key")

    with pytest.raises(MODULE.BundleFailure, match="required payload path is missing"):
        MODULE.create_bundle(
            payload_dir=payload,
            key_file=key,
            output=tmp_path / "backup.nxl",
            policy_path=POLICY_PATH,
            repository="eNgine9r/nexolab-platform",
            commit="a" * 40,
        )


def test_missing_local_auth_key_is_rejected(tmp_path: Path) -> None:
    payload = write_payload(tmp_path)
    (payload / "local-auth" / "private.pem").unlink()
    key = write_key(tmp_path / "backup.key")

    with pytest.raises(MODULE.BundleFailure, match="local-auth/private.pem"):
        MODULE.create_bundle(
            payload_dir=payload,
            key_file=key,
            output=tmp_path / "backup.nxl",
            policy_path=POLICY_PATH,
            repository="eNgine9r/nexolab-platform",
            commit="a" * 40,
        )


def test_key_permissions_must_be_private(tmp_path: Path) -> None:
    key = write_key(tmp_path / "backup.key")
    key.chmod(0o644)

    with pytest.raises(MODULE.BundleFailure, match="permissions"):
        MODULE.load_key(key)


def test_key_must_not_be_symlink(tmp_path: Path) -> None:
    target = write_key(tmp_path / "real.key")
    link = tmp_path / "link.key"
    link.symlink_to(target)

    with pytest.raises(MODULE.BundleFailure, match="non-symlink"):
        MODULE.load_key(link)


def test_extract_requires_fresh_destination(tmp_path: Path) -> None:
    _, key, bundle = create_bundle(tmp_path)
    restored = tmp_path / "restored"
    restored.mkdir()

    with pytest.raises(MODULE.BundleFailure, match="already exists"):
        MODULE.extract_bundle(
            bundle=bundle,
            key_file=key,
            policy_path=POLICY_PATH,
            output_dir=restored,
        )
