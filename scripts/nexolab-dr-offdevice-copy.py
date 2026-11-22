#!/usr/bin/env python3
"""#1631 DR-C: verified off-device copy of a leaf-A bundle with a custody receipt.

Destination-agnostic: the destination is a directory on a mounted, owner-enrolled
medium (``dedicated_media``: a USB SSD) or an offline-reachable LAN share
(``independent_host``). No cloud, no network API, no Docker, no hardware writes.

Safety contract (enforced in code, covered by tests/test_ci_dr_offdevice_copy.py):
* the bundle is cryptographically authenticated with the existing
  ``nexolab-dr-stream.py`` reader BEFORE anything is copied; a missing, unsafe or
  wrong key, or any tampering, refuses the copy. The key is read only to verify:
  it is never copied, printed or written; only ``sha256(key file bytes)`` is recorded;
* the destination must be enrolled (``NEXOLAB-DR-DESTINATION.json``) and must not
  share a file system or a physical disk with the source tree, the root file system
  or the key file, and must not lie inside the source tree (or contain it);
* only encrypted bytes are streamed, into ``.<name>.partial`` (0600, fsync). The
  DESTINATION file is then re-read and its size and SHA-256 compared with the
  verified source BEFORE the atomic rename. Any mismatch, short write, error or
  interruption removes the partial: an unverified file never gets the final name;
* a canonical ``nexolab-dr-custody-receipt-v1`` (0600) is written next to the
  bundle on the destination and into a local receipts directory;
* retention on the destination is report-only unless ``--apply``; it keeps at least
  the newest two verified bundles, never deletes the newest verified bundle and
  never touches unverified files or anything outside the destination directory.

A custody receipt is NOT restore evidence; recoverability is proven only by the
isolated restore of #1632. Exit codes: 0 success, 1 verification/copy failure,
78 blocked by configuration, key, destination identity or capacity.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable

VERSION = "1.0.0"
COPIER = f"nexolab-dr-offdevice-copy.py/{VERSION}"
RECEIPT_KIND = "nexolab-dr-custody-receipt"
RECEIPT_SCHEMA = "nexolab-dr-custody-receipt-v1"
RECEIPT_SUFFIX = ".custody-receipt.json"
MARKER_NAME = "NEXOLAB-DR-DESTINATION.json"
MARKER_KIND = "nexolab-dr-destination"
DESTINATION_KINDS = ("dedicated_media", "independent_host")
EXIT_OK, EXIT_FAILED, EXIT_BLOCKED = 0, 1, 78
MiB = 1024**2
COPY_CHUNK = 1 * MiB
CAPACITY_MARGIN_BYTES = 64 * MiB
MIN_KEEP = 2
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p"}
O_BINARY = getattr(os, "O_BINARY", 0)

RECEIPT_FIELDS = (
    "schema_version", "kind", "bundle_name", "bundle_sha256", "bundle_bytes",
    "source_manifest_sha256", "destination_kind", "destination_identity_sha256",
    "source_disk_independent", "readback_sha256", "readback_bytes",
    "key_fingerprint_sha256", "copied_at", "copier", "free_after_bytes",
)
MARKER_FIELDS = {"schema_version", "kind", "destination_kind", "destination_id", "label", "volume_uuid"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_NAME = re.compile(r"^nexolab-dr-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}\.nxs$")
UTC_SECONDS = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
COPIER_PATTERN = re.compile(r"^nexolab-dr-offdevice-copy\.py/[0-9]+\.[0-9]+\.[0-9]+$")
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
DESTINATION_ID = re.compile(r"^[0-9a-f]{32}$")


class Blocked(Exception):
    """Refused before copying: configuration, key, destination identity or capacity (exit 78)."""


class CopyFailed(Exception):
    """Verification, copy or read-back failed; nothing was accepted (exit 1)."""


def _load_stream_module():
    path = Path(__file__).with_name("nexolab-dr-stream.py")
    spec = importlib.util.spec_from_file_location("nexolab_dr_stream", path)
    if spec is None or spec.loader is None:
        raise Blocked("nexolab-dr-stream.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


drs = _load_stream_module()
canonical_json = drs.canonical_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


# ----------------------------------------------------------------- device identity


@dataclass(frozen=True)
class Volume:
    """Identity of the storage that holds a path.

    ``filesystem``: the mounted file system (``st_dev``). ``physical_disk``: the
    whole underlying device(s) (``block:sda`` for /dev/sda2, ``remote:<source>`` for
    a network share) or ``""`` when unresolvable. ``volume_uuid``: stable file-system
    UUID (block) or mount source (network); ``None`` when unknown.
    """

    filesystem: str
    physical_disk: str
    remote: bool
    volume_uuid: str | None


def _mountinfo_for(major: int, minor: int) -> tuple[str, str] | None:
    """(fstype, mount source) of the last mount of device major:minor."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        left, _, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if len(fields) >= 3 and len(tail) >= 2 and fields[2] == f"{major}:{minor}":
            found = (tail[0], tail[1])
    return found


def _block_disks(major: int, minor: int, depth: int = 0) -> list[str]:
    """Whole physical disks under a block device (partition -> disk, loop/dm -> backing)."""
    if depth > 8:
        return []
    try:
        node = Path(os.path.realpath(f"/sys/dev/block/{major}:{minor}"))
    except OSError:
        return []
    if not node.exists():
        return []
    if (node / "partition").exists():
        node = node.parent
    name = node.name
    if name.startswith("loop"):
        try:
            backing = (node / "loop" / "backing_file").read_text(encoding="utf-8").strip()
            dev = os.stat(backing).st_dev
        except OSError:
            return []
        return _block_disks(os.major(dev), os.minor(dev), depth + 1)
    slaves = node / "slaves"
    if slaves.is_dir() and any(slaves.iterdir()):
        disks: list[str] = []
        for slave in sorted(slaves.iterdir()):
            try:
                major_s, minor_s = (slave / "dev").read_text(encoding="ascii").strip().split(":")
            except (OSError, ValueError):
                return []
            disks.extend(_block_disks(int(major_s), int(minor_s), depth + 1))
        return sorted(set(disks))
    return [name]


def _filesystem_uuid(device: int) -> str | None:
    by_uuid = Path("/dev/disk/by-uuid")
    try:
        for entry in sorted(by_uuid.iterdir()):
            with contextlib.suppress(OSError):
                if os.stat(entry).st_rdev == device:
                    return entry.name
    except OSError:
        return None
    return None


def probe_volume(path: Path) -> Volume:
    """Default Linux probe (read-only: stat, /proc/self/mountinfo, /sys, /dev/disk/by-uuid)."""
    if not sys.platform.startswith("linux"):
        raise Blocked("device identity probe is implemented for Linux only; refusing")
    try:
        device = os.stat(path).st_dev
    except OSError as exc:
        raise Blocked(f"cannot stat {path}") from exc
    major, minor = os.major(device), os.minor(device)
    mount = _mountinfo_for(major, minor)
    fstype, source = mount if mount else ("", "")
    if fstype in NETWORK_FS:
        return Volume(f"dev:{major}:{minor}", f"remote:{source}", True, f"remote:{source}")
    disks = _block_disks(major, minor) if major != 0 else []
    physical = "block:" + "+".join(disks) if disks else ""
    return Volume(f"dev:{major}:{minor}", physical, False, _filesystem_uuid(device))


def _resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise Blocked(f"path does not exist: {path}") from exc


def _within(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def check_independence(destination: Path, source_tree: Path, protected: list[Path],
                       probe: Callable[[Path], Volume]) -> Volume:
    """Refuses a destination that is not physically independent of every protected path."""
    dest_real, source_real = _resolve(destination), _resolve(source_tree)
    if _within(dest_real, source_real) or _within(source_real, dest_real):
        raise Blocked("destination is inside the source tree (or contains it)")
    dest = probe(dest_real)
    if not dest.physical_disk:
        raise Blocked("destination physical device cannot be identified; refusing")
    for path in [source_real, *protected]:
        other = probe(_resolve(path))
        if not other.physical_disk:
            raise Blocked("source physical device cannot be identified; refusing")
        if other.filesystem == dest.filesystem:
            raise Blocked("destination is on the same file system as the source, root or key")
        if other.physical_disk == dest.physical_disk:
            raise Blocked("destination is on the same physical disk as the source, root or key")
    return dest


# ----------------------------------------------------------------- destination marker


def destination_identity_sha256(marker: dict[str, Any]) -> str:
    """Stable identity of an enrolled medium: random enrolment id + kind + label + volume UUID."""
    return hashlib.sha256(canonical_json({
        "destination_id": marker["destination_id"], "destination_kind": marker["destination_kind"],
        "label": marker["label"], "volume_uuid": marker["volume_uuid"],
    })).hexdigest()


def read_marker(destination: Path) -> dict[str, Any]:
    path = destination / MARKER_NAME
    try:
        meta = path.lstat()
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size > 4096:
            raise Blocked("destination marker must be a small regular file")
        marker = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Blocked("destination is not enrolled (missing or invalid NEXOLAB-DR-DESTINATION.json)") from exc
    if not isinstance(marker, dict) or set(marker) != MARKER_FIELDS:
        raise Blocked("destination marker has unexpected fields")
    if marker["schema_version"] != 1 or marker["kind"] != MARKER_KIND:
        raise Blocked("destination marker version is unsupported")
    if marker["destination_kind"] not in DESTINATION_KINDS:
        raise Blocked("destination kind must be dedicated_media or independent_host")
    if not isinstance(marker["destination_id"], str) or not DESTINATION_ID.fullmatch(marker["destination_id"]):
        raise Blocked("destination id is invalid")
    if not isinstance(marker["label"], str) or not LABEL.fullmatch(marker["label"]):
        raise Blocked("destination label is invalid")
    if not isinstance(marker["volume_uuid"], str) or not 0 < len(marker["volume_uuid"]) <= 256:
        raise Blocked("destination volume identity is invalid")
    return marker


def check_marker_binding(marker: dict[str, Any], volume: Volume) -> None:
    """The marker must belong to the volume it is found on (a copied marker is refused)."""
    if volume.volume_uuid is None:
        raise Blocked("destination volume UUID cannot be determined; refusing")
    if marker["volume_uuid"] != volume.volume_uuid:
        raise Blocked("destination marker belongs to another volume (moved or cloned marker)")
    if marker["destination_kind"] == "dedicated_media" and volume.remote:
        raise Blocked("dedicated_media destination is a network file system")
    if marker["destination_kind"] == "independent_host" and not volume.remote:
        raise Blocked("independent_host destination is not a network share")


def enroll(destination: Path, kind: str, label: str, *, probe: Callable[[Path], Volume] | None = None) -> dict:
    """Owner step, once per medium: writes the 0600 marker; never overwrites one."""
    probe = probe or probe_volume
    if kind not in DESTINATION_KINDS:
        raise Blocked("destination kind must be dedicated_media or independent_host")
    if not LABEL.fullmatch(label):
        raise Blocked("label must be 1-64 characters [A-Za-z0-9_.-]")
    volume = probe(_resolve(destination))
    if volume.volume_uuid is None or not volume.physical_disk:
        raise Blocked("destination volume cannot be identified; refusing to enroll")
    marker = {"schema_version": 1, "kind": MARKER_KIND, "destination_kind": kind,
              "destination_id": secrets.token_hex(16), "label": label, "volume_uuid": volume.volume_uuid}
    check_marker_binding(marker, volume)
    path = destination / MARKER_NAME
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    except FileExistsError as exc:
        raise Blocked("destination is already enrolled; the marker is never overwritten") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_json(marker))
        handle.flush()
        os.fsync(handle.fileno())
    return {"status": "ENROLLED", "destination_kind": kind, "label": label,
            "destination_identity_sha256": destination_identity_sha256(marker)}


# ----------------------------------------------------------------- hashing / io


class _HashingReader:
    def __init__(self, source: BinaryIO) -> None:
        self._source = source
        self._sha = hashlib.sha256()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size)
        self._sha.update(data)
        self.count += len(data)
        return data

    def hexdigest(self) -> str:
        return self._sha.hexdigest()


def hash_file(path: Path) -> tuple[str, int]:
    """SHA-256 and size of a file, re-read from storage (page cache dropped when possible)."""
    sha, size = hashlib.sha256(), 0
    descriptor = os.open(path, os.O_RDONLY | O_BINARY)
    with os.fdopen(descriptor, "rb") as handle:
        if hasattr(os, "posix_fadvise"):
            with contextlib.suppress(OSError):
                os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        while chunk := handle.read(COPY_CHUNK):
            sha.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), size


def _write_chunk(handle: BinaryIO, data: bytes) -> int:
    return handle.write(data)


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    _fsync_dir(path.parent)


# ----------------------------------------------------------------- receipt contract


def validate_custody_receipt(receipt: object) -> dict[str, Any]:
    """Exact nexolab-dr-custody-receipt-v1 contract (shared with #1632 and the health probe)."""
    if not isinstance(receipt, dict) or set(receipt) != set(RECEIPT_FIELDS):
        raise CopyFailed("custody receipt: missing or unexpected fields")

    def need(condition: bool, message: str) -> None:
        if not condition:
            raise CopyFailed(f"custody receipt: {message}")

    def count(value: object) -> bool:
        return type(value) is int and value >= 0

    need(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1, "schema_version must be 1")
    need(receipt["kind"] == RECEIPT_KIND, "invalid kind")
    need(isinstance(receipt["bundle_name"], str) and bool(BUNDLE_NAME.fullmatch(receipt["bundle_name"])),
         "invalid bundle_name")
    for name in ("bundle_sha256", "source_manifest_sha256", "destination_identity_sha256",
                 "readback_sha256", "key_fingerprint_sha256"):
        need(isinstance(receipt[name], str) and bool(SHA256.fullmatch(receipt[name])), f"invalid {name}")
    need(count(receipt["bundle_bytes"]) and receipt["bundle_bytes"] > 0, "invalid bundle_bytes")
    need(count(receipt["readback_bytes"]) and count(receipt["free_after_bytes"]), "invalid byte counts")
    need(receipt["destination_kind"] in DESTINATION_KINDS, "invalid destination_kind")
    need(receipt["source_disk_independent"] is True, "source disk independence not established")
    need(receipt["readback_sha256"] == receipt["bundle_sha256"]
         and receipt["readback_bytes"] == receipt["bundle_bytes"], "read-back does not equal the bundle")
    need(isinstance(receipt["copied_at"], str) and bool(UTC_SECONDS.fullmatch(receipt["copied_at"])),
         "copied_at must be UTC seconds with Z")
    need(isinstance(receipt["copier"], str) and bool(COPIER_PATTERN.fullmatch(receipt["copier"])), "invalid copier")
    return receipt


def receipt_name(bundle_name: str) -> str:
    return bundle_name[: -len(".nxs")] + RECEIPT_SUFFIX


def read_receipt(path: Path) -> dict[str, Any]:
    try:
        meta = path.lstat()
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size > 64 * 1024:
            raise CopyFailed("custody receipt must be a small regular file")
        raw = path.read_bytes()
        receipt = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CopyFailed("custody receipt is unreadable or invalid JSON") from exc
    validate_custody_receipt(receipt)
    if canonical_json(receipt) != raw:
        raise CopyFailed("custody receipt is not canonical")
    return receipt


# ----------------------------------------------------------------- copy


def _check_source_receipt(path: Path, name: str, sha: str, size: int, header_fingerprint: str) -> None:
    """Optional cross-check against the leaf-A receipt (nexolab-dr-backup-receipt)."""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        bundle = receipt["bundle"]
        ok = (receipt.get("kind") == "nexolab-dr-backup-receipt" and bundle.get("file") == name
              and bundle.get("size") == size and bundle.get("sha256") == sha
              and receipt.get("key_fingerprint") == header_fingerprint)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CopyFailed("leaf-A source receipt is unreadable") from exc
    if not ok:
        raise CopyFailed("bundle does not match its leaf-A source receipt")


def copy_bundle(bundle: Path, key_file: Path, destination: Path, receipts_dir: Path, *,
                source_receipt: Path | None = None,
                probe: Callable[[Path], Volume] | None = None,
                free: Callable[[Path], int] | None = None,
                now: Callable[[], str] = utc_now) -> dict[str, Any]:
    probe = probe or probe_volume
    free = free or disk_free
    name = bundle.name
    if not BUNDLE_NAME.fullmatch(name):
        raise Blocked("bundle name is not a leaf-A nexolab-dr-*.nxs name")
    try:
        meta = bundle.lstat()
    except OSError as exc:
        raise Blocked("bundle is not readable") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise Blocked("bundle must be a regular non-symlink file")
    try:
        key = drs.load_key(key_file)
    except drs.StreamFailure as exc:
        raise Blocked(f"key: {exc}") from exc
    key_fingerprint_sha256 = hashlib.sha256(key).hexdigest()

    receipts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _within(_resolve(receipts_dir), _resolve(destination)):
        raise Blocked("local receipts directory must not be on the destination")
    marker = read_marker(destination)
    root = Path(os.path.abspath(os.sep))
    volume = check_independence(destination, bundle.parent, [root, key_file], probe)
    check_marker_binding(marker, volume)
    identity = destination_identity_sha256(marker)

    # (a) authenticate the complete bundle and hash exactly the bytes that were authenticated.
    try:
        with bundle.open("rb") as source:
            reader = _HashingReader(source)
            result = drs.walk(reader, key)
    except (drs.StreamFailure, OSError) as exc:
        raise CopyFailed(f"bundle failed cryptographic verification; nothing copied ({exc})") from exc
    source_sha, source_bytes = reader.hexdigest(), reader.count
    manifest_sha = hashlib.sha256(canonical_json(result.manifest)).hexdigest()
    if source_receipt is not None:
        _check_source_receipt(source_receipt, name, source_sha, source_bytes, result.header["key_fingerprint"])
    del key

    final = destination / name
    partial = destination / f".{name}.partial"
    dest_receipt = destination / receipt_name(name)
    local_receipt = receipts_dir / receipt_name(name)

    def issue_receipt(readback_sha: str, readback_bytes: int) -> dict[str, Any]:
        receipt = {
            "schema_version": 1,
            "kind": RECEIPT_KIND,
            "bundle_name": name,
            "bundle_sha256": source_sha,
            "bundle_bytes": source_bytes,
            "source_manifest_sha256": manifest_sha,
            "destination_kind": marker["destination_kind"],
            "destination_identity_sha256": identity,
            "source_disk_independent": True,
            "readback_sha256": readback_sha,
            "readback_bytes": readback_bytes,
            "key_fingerprint_sha256": key_fingerprint_sha256,
            "copied_at": now(),
            "copier": COPIER,
            "free_after_bytes": free(destination),
        }
        validate_custody_receipt(receipt)
        data = canonical_json(receipt)
        write_private_bytes(dest_receipt, data)
        write_private_bytes(local_receipt, data)
        return receipt

    if final.exists() or final.is_symlink():
        return _already_present(final, dest_receipt, local_receipt, source_sha, source_bytes, identity,
                                issue_receipt)
    if partial.exists() or partial.is_symlink():
        raise Blocked(f"stale partial from an interrupted run exists: {partial.name}; inspect and remove it")
    available = free(destination)
    if available < source_bytes + CAPACITY_MARGIN_BYTES:
        raise Blocked(f"destination free {available} < bundle {source_bytes} + margin {CAPACITY_MARGIN_BYTES}")

    # (c) stream encrypted bytes to the partial, re-read the destination, then rename.
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_BINARY, 0o600)
    try:
        copied, digest = 0, hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output, bundle.open("rb") as source:
            while chunk := source.read(COPY_CHUNK):
                written = _write_chunk(output, chunk)
                if written != len(chunk):
                    raise CopyFailed("short write to the destination")
                digest.update(chunk)
                copied += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        if (digest.hexdigest(), copied) != (source_sha, source_bytes):
            raise CopyFailed("source changed after verification; copy discarded")
        readback_sha, readback_bytes = hash_file(partial)
        if (readback_sha, readback_bytes) != (source_sha, source_bytes):
            raise CopyFailed("destination read-back size/SHA-256 mismatch; copy discarded")
        if final.exists() or final.is_symlink():
            raise CopyFailed("final name appeared during the copy; refusing to overwrite")
        os.replace(partial, final)
        _fsync_dir(destination)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()  # only the exact partial created above
        raise

    return {"status": "COPIED_READBACK_VERIFIED", "receipt": issue_receipt(readback_sha, readback_bytes)}


def _already_present(final: Path, dest_receipt: Path, local_receipt: Path, sha: str, size: int,
                     identity: str, issue_receipt: Callable[[str, int], dict[str, Any]]) -> dict[str, Any]:
    """Idempotent re-run: accept an existing final file only after a fresh read-back."""
    if final.is_symlink() or not final.is_file():
        raise CopyFailed("final name exists but is not a regular file")
    readback = hash_file(final)
    if readback != (sha, size):
        raise CopyFailed("a different file already has the final name; refusing to overwrite")
    if not dest_receipt.exists() and not dest_receipt.is_symlink():
        # e.g. interrupted after the rename: the fresh read-back above is the evidence.
        return {"status": "ALREADY_PRESENT_VERIFIED", "receipt": issue_receipt(*readback)}
    receipt = read_receipt(dest_receipt)
    if (receipt["bundle_sha256"], receipt["bundle_bytes"], receipt["destination_identity_sha256"]) != (
        sha, size, identity
    ):
        raise CopyFailed("existing custody receipt does not match this bundle and destination")
    data = canonical_json(receipt)
    if not local_receipt.exists() or local_receipt.read_bytes() != data:
        write_private_bytes(local_receipt, data)
    return {"status": "ALREADY_PRESENT_VERIFIED", "receipt": receipt}


# ----------------------------------------------------------------- destination scan / retention


def scan_destination(destination: Path, identity: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-reads every bundle on the destination: (verified receipts newest first, unverified names)."""
    verified: list[dict[str, Any]] = []
    unverified: list[str] = []
    for path in sorted(destination.iterdir()):
        if not BUNDLE_NAME.fullmatch(path.name):
            continue
        try:
            if path.is_symlink() or not path.is_file():
                raise CopyFailed("not a regular file")
            receipt = read_receipt(destination / receipt_name(path.name))
            if receipt["bundle_name"] != path.name or receipt["destination_identity_sha256"] != identity:
                raise CopyFailed("receipt belongs to another bundle or destination")
            if hash_file(path) != (receipt["bundle_sha256"], receipt["bundle_bytes"]):
                raise CopyFailed("read-back mismatch")
        except (CopyFailed, OSError):
            unverified.append(path.name)
            continue
        verified.append(receipt)
    verified.sort(key=lambda item: (item["copied_at"], item["bundle_name"]), reverse=True)
    return verified, unverified


def _open_destination(destination: Path, probe: Callable[[Path], Volume] | None) -> str:
    probe = probe or probe_volume
    marker = read_marker(destination)
    dest = _resolve(destination)
    volume = probe(dest)
    check_marker_binding(marker, volume)
    root = probe(_resolve(Path(os.path.abspath(os.sep))))
    if not volume.physical_disk or volume.filesystem == root.filesystem or volume.physical_disk == root.physical_disk:
        raise Blocked("destination is not independent of the root file system/disk")
    return destination_identity_sha256(marker)


def retention(destination: Path, *, keep: int = MIN_KEEP, apply: bool = False,
              probe: Callable[[Path], Volume] | None = None) -> dict[str, Any]:
    """Report-only by default. Deletes only verified bundles beyond the newest ``keep``."""
    if type(keep) is not int or keep < MIN_KEEP:
        raise Blocked(f"keep must be an integer >= {MIN_KEEP}")
    identity = _open_destination(destination, probe)
    verified, unverified = scan_destination(destination, identity)
    kept = [item["bundle_name"] for item in verified[:keep]]
    candidates = [item["bundle_name"] for item in verified[keep:]]
    deleted: list[str] = []
    if apply and candidates:
        newest = verified[0]["bundle_name"]
        for name in candidates:
            if name == newest or name in kept or len(kept) < keep:
                raise Blocked("retention invariant violated; nothing deleted")
            (destination / name).unlink()
            with contextlib.suppress(FileNotFoundError):
                (destination / receipt_name(name)).unlink()
            deleted.append(name)
        _fsync_dir(destination)
    return {
        "status": "APPLIED" if apply else "REPORT_ONLY",
        "keep": keep,
        "verified_kept": kept,
        "deletion_candidates": [] if apply else candidates,
        "deleted": deleted,
        "unverified_untouched": unverified,
    }


def reverify_destination(destination: Path, *, probe: Callable[[Path], Volume] | None = None) -> dict[str, Any]:
    """Read-only: the newest bundle on a readable, enrolled, independent destination must
    re-hash to its custody receipt. Used by nexolab-dr-readonly-health.py. Needs no key."""
    identity = _open_destination(destination, probe)
    verified, unverified = scan_destination(destination, identity)
    if not verified:
        raise CopyFailed("no bundle on the destination re-verifies against its custody receipt")
    newest = verified[0]
    return {"status": "READBACK_REVERIFIED", "bundle_name": newest["bundle_name"],
            "bundle_sha256": newest["bundle_sha256"], "copied_at": newest["copied_at"],
            "destination_kind": newest["destination_kind"],
            "destination_identity_sha256": identity, "verified_bundles": len(verified),
            "unverified_files": len(unverified)}


# ----------------------------------------------------------------- CLI


def _terminate(signum, _frame):  # SIGTERM -> normal unwinding, so the partial is removed
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    copy = sub.add_parser("copy", help="verify, copy, read back and write the custody receipt")
    copy.add_argument("--bundle", type=Path, required=True)
    copy.add_argument("--key-file", type=Path, required=True)
    copy.add_argument("--destination", type=Path, required=True)
    copy.add_argument("--receipts-dir", type=Path, required=True)
    copy.add_argument("--source-receipt", type=Path, help="optional leaf-A receipt to cross-check")
    enrol = sub.add_parser("enroll", help="owner step: mark a medium as an approved destination")
    enrol.add_argument("--destination", type=Path, required=True)
    enrol.add_argument("--kind", choices=DESTINATION_KINDS, required=True)
    enrol.add_argument("--label", required=True)
    keep = sub.add_parser("retention", help="report (default) or apply destination retention")
    keep.add_argument("--destination", type=Path, required=True)
    keep.add_argument("--keep", type=int, default=MIN_KEEP)
    keep.add_argument("--apply", action="store_true", help="actually delete; default is report-only")
    check = sub.add_parser("verify-destination", help="read-only re-hash of the newest copy (no key)")
    check.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    with contextlib.suppress(ValueError, AttributeError):
        signal.signal(signal.SIGTERM, _terminate)
    try:
        if args.command == "copy":
            result = copy_bundle(args.bundle, args.key_file, args.destination, args.receipts_dir,
                                 source_receipt=args.source_receipt)
        elif args.command == "enroll":
            result = enroll(args.destination, args.kind, args.label)
        elif args.command == "retention":
            result = retention(args.destination, keep=args.keep, apply=args.apply)
        else:
            result = reverify_destination(args.destination)
    except Blocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)[:300]}, sort_keys=True), file=sys.stderr)
        return EXIT_BLOCKED
    except (CopyFailed, OSError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)[:300]}, sort_keys=True), file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
