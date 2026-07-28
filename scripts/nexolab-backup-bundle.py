#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"NEXOLAB-DR-1\n"
HEADER_LENGTH = struct.Struct(">I")
KEY_BYTES = 32
NONCE_BYTES = 12
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BundleFailure(ValueError):
    pass


@dataclass(frozen=True)
class PayloadFile:
    path: str
    source: Path
    size: int
    sha256: str


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise BundleFailure(f"cannot read payload file: {path}") from exc
    return digest.hexdigest()


def parse_timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BundleFailure("created-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BundleFailure("created-at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_relative_path(value: str, label: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise BundleFailure(f"{label} is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleFailure(f"{label} is unsafe")
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BundleFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise BundleFailure(f"{path} must contain a JSON object")
    return payload


def load_key(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BundleFailure("encryption key file is not readable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BundleFailure("encryption key must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise BundleFailure("encryption key file permissions must be 0600 or stricter")
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise BundleFailure("encryption key file is not readable") from exc
    if len(key) != KEY_BYTES:
        raise BundleFailure("encryption key file must contain exactly 32 raw bytes")
    return key


def load_policy(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema_version") != 1:
        raise BundleFailure("disaster-recovery policy schema_version must be 1")
    bundle = payload.get("bundle")
    assets = payload.get("assets")
    if not isinstance(bundle, dict) or bundle.get("format") != "nexolab-dr-v1":
        raise BundleFailure("unsupported disaster-recovery bundle policy")
    if bundle.get("encryption") != "aes-256-gcm":
        raise BundleFailure("unsupported disaster-recovery encryption policy")
    if not isinstance(assets, list) or not assets:
        raise BundleFailure("disaster-recovery policy has no assets")
    return payload


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BundleFailure(f"required payload path is missing: {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise BundleFailure(f"required payload path must be a regular file: {label}")


def collect_payload_files(payload_dir: Path, policy: dict[str, Any]) -> list[PayloadFile]:
    try:
        root_metadata = payload_dir.lstat()
    except OSError as exc:
        raise BundleFailure("payload directory is not readable") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise BundleFailure("payload directory must be a non-symlink directory")

    declared_paths: set[str] = set()
    for asset in policy["assets"]:
        asset_id = str(asset.get("id") or "unknown")
        backup_path = safe_relative_path(
            str(asset.get("backup_path") or ""),
            f"asset {asset_id} backup_path",
        )
        declared_paths.add(backup_path)
        candidate = payload_dir / backup_path
        if asset.get("backup_format") == "object_tree":
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                raise BundleFailure(
                    f"required object tree is missing: {backup_path}"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise BundleFailure(
                    f"object tree must be a non-symlink directory: {backup_path}"
                )
            metadata_path = safe_relative_path(
                str(asset.get("metadata_path") or ""),
                f"asset {asset_id} metadata_path",
            )
            declared_paths.add(metadata_path)
            require_regular_file(payload_dir / metadata_path, metadata_path)
        else:
            require_regular_file(candidate, backup_path)

    files: list[PayloadFile] = []
    for path in sorted(payload_dir.rglob("*")):
        relative = path.relative_to(payload_dir).as_posix()
        safe_relative_path(relative, "payload path")
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise BundleFailure(f"payload symlink is forbidden: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise BundleFailure(f"payload special file is forbidden: {relative}")
        files.append(
            PayloadFile(
                path=relative,
                source=path,
                size=metadata.st_size,
                sha256=sha256_file(path),
            )
        )

    if not files:
        raise BundleFailure("payload contains no files")
    file_paths = {item.path for item in files}
    for declared in declared_paths:
        candidate = payload_dir / declared
        if candidate.is_dir():
            continue
        if declared not in file_paths:
            raise BundleFailure(f"declared payload file is missing: {declared}")
    if "manifest.json" in file_paths:
        raise BundleFailure("payload must not provide its own manifest.json")
    return files


def tree_digest(files: list[PayloadFile]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda candidate: candidate.path):
        digest.update(item.path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(item.size).encode("ascii"))
        digest.update(b"\x00")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def asset_manifest(
    payload_dir: Path,
    files: list[PayloadFile],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for asset in policy["assets"]:
        asset_id = str(asset["id"])
        backup_path = str(asset["backup_path"])
        candidate = payload_dir / backup_path
        if candidate.is_dir():
            prefix = backup_path.rstrip("/") + "/"
            selected = [item for item in files if item.path.startswith(prefix)]
        else:
            selected = [item for item in files if item.path == backup_path]
        metadata_path = asset.get("metadata_path")
        if isinstance(metadata_path, str):
            selected.extend(item for item in files if item.path == metadata_path)
        unique = {item.path: item for item in selected}
        ordered = [unique[path] for path in sorted(unique)]
        result.append(
            {
                "id": asset_id,
                "backup_format": asset["backup_format"],
                "file_count": len(ordered),
                "total_bytes": sum(item.size for item in ordered),
                "tree_sha256": tree_digest(ordered),
            }
        )
    return result


def build_manifest(
    *,
    repository: str,
    commit: str,
    created_at: str,
    payload_dir: Path,
    files: list[PayloadFile],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository):
        raise BundleFailure("repository must use owner/name format")
    if not COMMIT.fullmatch(commit):
        raise BundleFailure("commit must be a full lowercase Git SHA")
    return {
        "schema_version": 1,
        "format": "nexolab-dr-v1",
        "repository": repository,
        "commit": commit,
        "created_at": parse_timestamp(created_at),
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in sorted(files, key=lambda candidate: candidate.path)
        ],
        "assets": asset_manifest(payload_dir, files, policy),
    }


def deterministic_tar(manifest: dict[str, Any], files: list[PayloadFile]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        manifest_content = canonical_json(manifest) + b"\n"
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_content)
        manifest_info.mode = 0o600
        manifest_info.mtime = 0
        manifest_info.uid = 0
        manifest_info.gid = 0
        manifest_info.uname = ""
        manifest_info.gname = ""
        archive.addfile(manifest_info, io.BytesIO(manifest_content))
        for item in sorted(files, key=lambda candidate: candidate.path):
            info = tarfile.TarInfo(item.path)
            info.size = item.size
            info.mode = 0o600
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with item.source.open("rb") as source:
                archive.addfile(info, source)
    return output.getvalue()


def build_header(manifest: dict[str, Any], nonce: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "format": "nexolab-dr-v1",
        "encryption": "aes-256-gcm",
        "repository": manifest["repository"],
        "commit": manifest["commit"],
        "created_at": manifest["created_at"],
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }


def encrypt_archive(archive: bytes, key: bytes, header: dict[str, Any]) -> bytes:
    header_bytes = canonical_json(header)
    ciphertext = AESGCM(key).encrypt(
        base64.b64decode(header["nonce"], validate=True),
        archive,
        header_bytes,
    )
    return MAGIC + HEADER_LENGTH.pack(len(header_bytes)) + header_bytes + ciphertext


def parse_bundle(content: bytes, key: bytes) -> tuple[dict[str, Any], bytes]:
    minimum = len(MAGIC) + HEADER_LENGTH.size + 1
    if len(content) < minimum or not content.startswith(MAGIC):
        raise BundleFailure("bundle has an invalid magic header")
    offset = len(MAGIC)
    (header_length,) = HEADER_LENGTH.unpack(
        content[offset : offset + HEADER_LENGTH.size]
    )
    offset += HEADER_LENGTH.size
    if header_length <= 0 or header_length > 65536:
        raise BundleFailure("bundle header length is invalid")
    header_bytes = content[offset : offset + header_length]
    ciphertext = content[offset + header_length :]
    if len(header_bytes) != header_length or len(ciphertext) < 16:
        raise BundleFailure("bundle is truncated")
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BundleFailure("bundle header is invalid") from exc
    if not isinstance(header, dict):
        raise BundleFailure("bundle header must be an object")
    required = {
        "schema_version",
        "format",
        "encryption",
        "repository",
        "commit",
        "created_at",
        "nonce",
    }
    if set(header) != required:
        raise BundleFailure("bundle header has unexpected fields")
    if header["schema_version"] != 1 or header["format"] != "nexolab-dr-v1":
        raise BundleFailure("bundle header version is unsupported")
    if header["encryption"] != "aes-256-gcm":
        raise BundleFailure("bundle encryption is unsupported")
    if not REPOSITORY.fullmatch(str(header["repository"])):
        raise BundleFailure("bundle repository is invalid")
    if not COMMIT.fullmatch(str(header["commit"])):
        raise BundleFailure("bundle commit is invalid")
    parse_timestamp(str(header["created_at"]))
    try:
        nonce = base64.b64decode(str(header["nonce"]), validate=True)
    except (ValueError, TypeError) as exc:
        raise BundleFailure("bundle nonce is invalid") from exc
    if len(nonce) != NONCE_BYTES:
        raise BundleFailure("bundle nonce length is invalid")
    try:
        archive = AESGCM(key).decrypt(nonce, ciphertext, header_bytes)
    except InvalidTag as exc:
        raise BundleFailure("bundle authentication failed") from exc
    return header, archive


def read_regular_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    source = archive.extractfile(member)
    if source is None:
        raise BundleFailure(f"archive entry has no content: {member.name}")
    return source.read()


def validate_archive(
    archive_content: bytes,
    header: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    files: dict[str, bytes] = {}
    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_content), mode="r:")
    except tarfile.TarError as exc:
        raise BundleFailure("decrypted payload is not a valid tar archive") from exc
    with archive:
        for member in archive.getmembers():
            name = safe_relative_path(member.name, "archive entry")
            if name in files:
                raise BundleFailure(f"duplicate archive entry: {name}")
            if not member.isfile() or member.issym() or member.islnk():
                raise BundleFailure(f"archive entry must be a regular file: {name}")
            files[name] = read_regular_member(archive, member)

    if "manifest.json" not in files:
        raise BundleFailure("archive is missing manifest.json")
    try:
        manifest = json.loads(files.pop("manifest.json").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BundleFailure("archive manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise BundleFailure("archive manifest must be an object")
    if manifest.get("schema_version") != 1 or manifest.get("format") != "nexolab-dr-v1":
        raise BundleFailure("archive manifest version is unsupported")
    for field in ("repository", "commit", "created_at"):
        if manifest.get(field) != header.get(field):
            raise BundleFailure(f"archive manifest {field} does not match header")

    declared = manifest.get("files")
    if not isinstance(declared, list):
        raise BundleFailure("archive manifest files must be a list")
    declared_paths: set[str] = set()
    for index, item in enumerate(declared):
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise BundleFailure(f"manifest files[{index}] is invalid")
        path = safe_relative_path(str(item["path"]), f"manifest files[{index}].path")
        if path in declared_paths:
            raise BundleFailure(f"duplicate manifest file: {path}")
        declared_paths.add(path)
        content = files.get(path)
        if content is None:
            raise BundleFailure(f"archive is missing declared file: {path}")
        if not isinstance(item["size"], int) or item["size"] < 0:
            raise BundleFailure(f"manifest file size is invalid: {path}")
        if len(content) != item["size"]:
            raise BundleFailure(f"manifest file size mismatch: {path}")
        expected = str(item["sha256"])
        if not SHA256.fullmatch(expected) or sha256_bytes(content) != expected:
            raise BundleFailure(f"manifest file hash mismatch: {path}")
    unexpected = sorted(set(files) - declared_paths)
    if unexpected:
        raise BundleFailure("archive contains unexpected files: " + ", ".join(unexpected))

    manifest_assets = manifest.get("assets")
    if not isinstance(manifest_assets, list):
        raise BundleFailure("archive manifest assets must be a list")
    expected_ids = [str(asset["id"]) for asset in policy["assets"]]
    actual_ids = [str(asset.get("id")) for asset in manifest_assets if isinstance(asset, dict)]
    if actual_ids != expected_ids:
        raise BundleFailure("archive manifest assets do not match recovery policy")

    for policy_asset, manifest_asset in zip(policy["assets"], manifest_assets, strict=True):
        if not isinstance(manifest_asset, dict):
            raise BundleFailure("archive manifest asset is invalid")
        backup_path = str(policy_asset["backup_path"])
        if policy_asset["backup_format"] == "object_tree":
            prefix = backup_path.rstrip("/") + "/"
            selected_paths = [path for path in files if path.startswith(prefix)]
        else:
            selected_paths = [path for path in files if path == backup_path]
        metadata_path = policy_asset.get("metadata_path")
        if isinstance(metadata_path, str):
            selected_paths.append(metadata_path)
        selected_paths = sorted(set(selected_paths))
        selected = [
            PayloadFile(
                path=path,
                source=Path(path),
                size=len(files[path]),
                sha256=sha256_bytes(files[path]),
            )
            for path in selected_paths
        ]
        expected_asset = {
            "id": policy_asset["id"],
            "backup_format": policy_asset["backup_format"],
            "file_count": len(selected),
            "total_bytes": sum(item.size for item in selected),
            "tree_sha256": tree_digest(selected),
        }
        if manifest_asset != expected_asset:
            raise BundleFailure(
                f"archive manifest asset summary mismatch: {policy_asset['id']}"
            )
    return manifest, files


def create_bundle(
    *,
    payload_dir: Path,
    key_file: Path,
    output: Path,
    policy_path: Path,
    repository: str,
    commit: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise BundleFailure("output bundle already exists")
    policy = load_policy(policy_path)
    files = collect_payload_files(payload_dir, policy)
    manifest = build_manifest(
        repository=repository,
        commit=commit,
        created_at=parse_timestamp(created_at),
        payload_dir=payload_dir,
        files=files,
        policy=policy,
    )
    archive = deterministic_tar(manifest, files)
    key = load_key(key_file)
    nonce = os.urandom(NONCE_BYTES)
    content = encrypt_archive(archive, key, build_header(manifest, nonce))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(output)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BundleFailure("could not write encrypted backup bundle") from exc
    return manifest


def verify_bundle(
    *,
    bundle: Path,
    key_file: Path,
    policy_path: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    try:
        content = bundle.read_bytes()
    except OSError as exc:
        raise BundleFailure("backup bundle is not readable") from exc
    key = load_key(key_file)
    policy = load_policy(policy_path)
    header, archive = parse_bundle(content, key)
    return validate_archive(archive, header, policy)


def extract_bundle(
    *,
    bundle: Path,
    key_file: Path,
    policy_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists():
        raise BundleFailure("restore output directory already exists")
    manifest, files = verify_bundle(
        bundle=bundle,
        key_file=key_file,
        policy_path=policy_path,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.",
            dir=output_dir.parent,
        )
    )
    try:
        for relative, content in sorted(files.items()):
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                target.write(content)
            os.chmod(destination, 0o600)
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(canonical_json(manifest) + b"\n")
        os.chmod(manifest_path, 0o600)
        temporary.replace(output_dir)
    except OSError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise BundleFailure("could not extract verified backup bundle") from exc
    return manifest


def print_summary(manifest: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "format": manifest["format"],
                "repository": manifest["repository"],
                "commit": manifest["commit"],
                "created_at": manifest["created_at"],
                "file_count": len(manifest["files"]),
                "assets": manifest["assets"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("security/disaster-recovery-assets.json"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--payload-dir", type=Path, required=True)
    create.add_argument("--key-file", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--repository", required=True)
    create.add_argument("--commit", required=True)
    create.add_argument("--created-at")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--key-file", type=Path, required=True)

    extract = subparsers.add_parser("extract")
    extract.add_argument("--bundle", type=Path, required=True)
    extract.add_argument("--key-file", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "create":
        manifest = create_bundle(
            payload_dir=args.payload_dir,
            key_file=args.key_file,
            output=args.output,
            policy_path=args.policy,
            repository=args.repository,
            commit=args.commit,
            created_at=args.created_at,
        )
    elif args.command == "verify":
        manifest, _ = verify_bundle(
            bundle=args.bundle,
            key_file=args.key_file,
            policy_path=args.policy,
        )
    else:
        manifest = extract_bundle(
            bundle=args.bundle,
            key_file=args.key_file,
            policy_path=args.policy,
            output_dir=args.output_dir,
        )
    print_summary(manifest)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleFailure as exc:
        print(f"NEXOLAB backup bundle failed: {exc}")
        raise SystemExit(1) from exc
