#!/usr/bin/env python3
"""NEXOLAB #1437: ONLY synthetic, bounded, isolated offline multi-store DR fixture.

There is NO CLI to point this harness at a production path. Never use its
synthetic successful receipt as an actual site backup or hardware acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tarfile
import tempfile

MAGIC = b"NEXOLAB-DR-FIXTURE-V1\n"
AAD = b"nexolab-site-dr-fixture-v1;site-activation=forbidden"
MAX_TOTAL = 2 * 1024 * 1024
ASSETS = {
    "postgresql": "pg_custom",
    "object-storage": "object_tree",
    "mqtt-dynamic-security": "deterministic_tar",
    "edge-sqlite-outbox": "sqlite_backup",
    "local-auth-private-key": "pem",
    "local-auth-public-key": "pem",
    "central-ingestion-spool": "sqlite_backup",
    "edge-mqtt-persistence": "deterministic_tar",
}


class FixtureBlocked(ValueError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise FixtureBlocked(message)


def canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def require_dir(path: Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise FixtureBlocked(f"{label}: missing directory") from exc
    require(stat.S_ISDIR(mode) and not path.is_symlink(), f"{label}: symlink or non-directory")
    require(stat.S_IMODE(mode) & 0o077 == 0, f"{label}: must be mode 0700")


def require_regular(path: Path, *, label: str) -> bytes:
    try:
        stat_result = path.lstat()
    except OSError as exc:
        raise FixtureBlocked(f"{label}: missing fixture file") from exc
    require(stat.S_ISREG(stat_result.st_mode) and not path.is_symlink(), f"{label}: special or symlink file")
    require(0 < stat_result.st_size <= MAX_TOTAL, f"{label}: invalid or oversized fixture")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FixtureBlocked(f"{label}: unreadable fixture") from exc


def seed_fixture(root: Path) -> None:
    """Populate only a newly allocated isolated fixture workspace."""
    require_dir(root, label="fixture root")
    require(not any(root.iterdir()), "fixture source must be empty")
    # The marker binds the source tree to this synthetic test only.
    (root / ".nexolab-synthetic-only").write_text("not-production\n", encoding="ascii")
    os.chmod(root / ".nexolab-synthetic-only", 0o600)
    for ident in ASSETS:
        payload = canonical({"synthetic": True, "asset": ident, "sequence": 42, "no_site_evidence": True})
        file = root / f"{ident}.fixture"
        file.write_bytes(payload)
        os.chmod(file, 0o600)


def read_fixture(root: Path) -> dict[str, bytes]:
    require_dir(root, label="fixture root")
    marker = require_regular(root / ".nexolab-synthetic-only", label="fixture marker")
    require(marker == b"not-production\n", "non-synthetic fixture source forbidden")
    expected = {".nexolab-synthetic-only"} | {f"{ident}.fixture" for ident in ASSETS}
    require({p.name for p in root.iterdir()} == expected, "missing or unexpected protected fixture asset")
    result = {ident: require_regular(root / f"{ident}.fixture", label=ident) for ident in ASSETS}
    require(sum(map(len, result.values())) <= MAX_TOTAL, "fixture exceeds 2 MiB total")
    for ident, content in result.items():
        try:
            value = json.loads(content)
        except (UnicodeError, ValueError) as exc:
            raise FixtureBlocked(f"{ident}: malformed synthetic fixture") from exc
        require(
            isinstance(value, dict)
            and value.get("synthetic") is True
            and value.get("asset") == ident
            and value.get("no_site_evidence") is True,
            f"{ident}: cannot treat real data as synthetic fixture",
        )
    return result


def archive_content(files: dict[str, bytes]) -> bytes:
    require(set(files) == set(ASSETS), "incomplete asset set")
    epoch = digest(b"nexolab-fixture-consistency-epoch")
    manifest = {
        "format": "nexolab-synthetic-site-dr-fixture-v1",
        "scope": "eight-store-synthetic-only",
        "site_backup": False,
        "hardware_verified": False,
        "capture_epoch_sha256": epoch,
        "assets": [
            {
                "id": ident,
                "format": ASSETS[ident],
                "path": f"{ident}.fixture",
                "bytes": len(files[ident]),
                "sha256": digest(files[ident]),
                "epoch_sha256": epoch,
            }
            for ident in ASSETS
        ],
    }
    data = {"manifest.json": canonical(manifest), **{f"{k}.fixture": v for k, v in files.items()}}
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, payload in sorted(data.items()):
            item = tarfile.TarInfo(name)
            item.size = len(payload)
            item.mode = 0o600
            item.mtime = 0
            tf.addfile(item, io.BytesIO(payload))
    return result.getvalue()


def create_bundle(source: Path, key: bytes) -> bytes:
    require(type(key) is bytes and len(key) == 32, "raw 32-byte AES-256 key required")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    archive = archive_content(read_fixture(source))
    require(len(archive) <= MAX_TOTAL + 32768, "archive exceeded bounded fixture limit")
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, archive, AAD)


def verify_bundle(blob: bytes, key: bytes) -> tuple[dict, dict[str, bytes]]:
    require(type(key) is bytes and len(key) == 32, "raw 32-byte AES-256 key required")
    require(isinstance(blob, bytes) and blob.startswith(MAGIC), "fixture envelope magic mismatch")
    require(len(blob) <= MAX_TOTAL + 32768 + len(MAGIC) + 12 + 16, "oversized fixture envelope")
    ciphertext = blob[len(MAGIC):]
    require(len(ciphertext) >= 28, "truncated fixture envelope")
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        tar_bytes = AESGCM(key).decrypt(ciphertext[:12], ciphertext[12:], AAD)
    except InvalidTag as exc:
        raise FixtureBlocked("fixture authenticated decryption failed") from exc
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
            for entry in tf.getmembers():
                require(entry.isfile() and not entry.issym() and not entry.islnk(), "archive special entry")
                require(
                    entry.name == "manifest.json" or entry.name in {f"{k}.fixture" for k in ASSETS},
                    "unsafe or unexpected archive path",
                )
                require(entry.name not in files, "duplicate archive member")
                require(0 < entry.size <= MAX_TOTAL, "invalid archive entry size")
                fh = tf.extractfile(entry)
                require(fh is not None, "archive entry unreadable")
                files[entry.name] = fh.read()
    except (tarfile.TarError, OSError) as exc:
        raise FixtureBlocked("corrupt synthetic archive") from exc
    require(set(files) == {"manifest.json"} | {f"{k}.fixture" for k in ASSETS}, "incomplete archive")
    try:
        manifest = json.loads(files.pop("manifest.json"))
    except (ValueError, UnicodeError) as exc:
        raise FixtureBlocked("invalid fixture manifest") from exc
    require(isinstance(manifest, dict) and set(manifest) == {
        "format", "scope", "site_backup", "hardware_verified", "capture_epoch_sha256", "assets",
    }, "invalid fixture manifest contract")
    require(manifest["format"] == "nexolab-synthetic-site-dr-fixture-v1", "wrong fixture version")
    require(manifest["scope"] == "eight-store-synthetic-only", "non-synthetic manifest")
    require(manifest["site_backup"] is False and manifest["hardware_verified"] is False, "false site or hardware acceptance")
    require(isinstance(manifest["assets"], list) and len(manifest["assets"]) == len(ASSETS), "missing fixture assets")
    require(manifest["capture_epoch_sha256"] == digest(b"nexolab-fixture-consistency-epoch"), "fixture epoch mismatch")
    for item, (ident, fmt) in zip(manifest["assets"], ASSETS.items(), strict=True):
        require(isinstance(item, dict) and set(item) == {
            "id", "format", "path", "bytes", "sha256", "epoch_sha256",
        }, "unrecognized asset receipt")
        name = f"{ident}.fixture"
        content = files[name]
        require(
            item == {
                "id": ident, "format": fmt, "path": name, "bytes": len(content),
                "sha256": digest(content), "epoch_sha256": manifest["capture_epoch_sha256"],
            },
            f"{ident}: fixture integrity or format mismatch",
        )
    return manifest, files


def restore_isolated(blob: bytes, key: bytes, source: Path, destination: Path) -> dict:
    """Extract only to an ABSENT sibling directory in a private fixture workspace."""
    require_dir(source, label="fixture source")
    require_dir(destination.parent, label="fixture restore parent")
    require(not destination.exists() and not destination.is_symlink(), "restore target already exists")
    require(source.resolve() != destination.resolve(), "source is restore destination")
    require(source.parent.resolve() == destination.parent.resolve(), "restore must be sibling isolated fixture")
    manifest, files = verify_bundle(blob, key)  # Authenticate all bytes BEFORE creating a target.
    temporary = Path(tempfile.mkdtemp(prefix=".nexolab-dr-fixture-restore-", dir=destination.parent))
    try:
        os.chmod(temporary, 0o700)
        for name, payload in sorted(files.items()):
            path = temporary / name
            with path.open("xb") as dest:
                dest.write(payload)
            os.chmod(path, 0o600)
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary)
        raise
    return manifest


def self_test() -> dict:
    # No CLI path parameters; all work stays in OS-managed private temp fixture.
    with tempfile.TemporaryDirectory(prefix="nexolab-dr-synthetic-") as name:
        root = Path(name)
        os.chmod(root, 0o700)
        source = root / "source"
        source.mkdir(mode=0o700)
        seed_fixture(source)
        before = {k: digest(v) for k, v in read_fixture(source).items()}
        key = secrets.token_bytes(32)
        bundle = create_bundle(source, key)
        verified, _ = verify_bundle(bundle, key)
        for corrupt, other_key in ((bundle, secrets.token_bytes(32)), (bundle[:-1] + bytes([bundle[-1] ^ 1]), key)):
            try:
                verify_bundle(corrupt, other_key)
            except FixtureBlocked:
                pass
            else:
                raise FixtureBlocked("negative crypto test accepted invalid bundle")
        restored = root / "restored"
        restore_isolated(bundle, key, source, restored)
        after = {k: digest(v) for k, v in read_fixture(source).items()}
        require(before == after, "source changed during isolated restore")
        require(
            {k: digest((restored / f"{k}.fixture").read_bytes()) for k in ASSETS} == before,
            "isolated fixture restore hashes mismatch",
        )
        require(verified["site_backup"] is False, "fixture cannot authorize site recovery")
        return {
            "status": "SYNTHETIC_ONLY_PASS",
            "asset_count": len(ASSETS),
            "source_untouched": True,
            "encrypted_archive_verified": True,
            "wrong_key_denied": True,
            "tamper_denied": True,
            "isolated_fixture_restore": True,
            "site_backup": "NOT_PERFORMED",
            "off_device_copy": "NOT_PERFORMED",
            "hardware_verified": False,
            "site_activation": "NOT_AUTHORIZED",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check", action="store_true", help="safe default contract review; no files")
    options.add_argument("--self-test", action="store_true", help="synthetic private-temp fixture only")
    args = parser.parse_args()
    if args.check:
        print(json.dumps({"status": "SOURCE_ONLY", "site_backup": "NOT_PERFORMED", "site_activation": "NOT_AUTHORIZED"}, sort_keys=True))
        return 0
    try:
        report = self_test()
    except (FixtureBlocked, OSError, ImportError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__, "site_activation": "NOT_AUTHORIZED"}))
        return 78
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
