#!/usr/bin/env python3
"""Deterministic NEXOLAB volume archive (PAX tar) with root metadata and ``user.*`` xattrs.

Extended attributes (#1630 object-metadata fix): VersityGW's posix backend keeps object
metadata (ETag, Content-Type, checksums, user metadata, bucket ACL/ownership) in ``user.*``
extended attributes. Archives written by this module (and by the leaf-A directory snapshot of
``nexolab-dr-scheduled-backup.py``) declare ``NEXOLAB.volume.xattrs=user-v1`` in the global PAX
header and carry each entry's ``user.*`` attributes as GNU-tar compatible ``SCHILY.xattr.<name>``
records (values are raw bytes). Only the ``user.`` namespace is ever read or written; size caps
bound every attribute, every entry and the whole archive. Archives without the declaration
(written before this change) extract exactly as before and report ``scheme: none``. Extraction of
an archive that carries attributes onto a file system that cannot store them fails closed unless
the caller explicitly allows the loss, in which case the loss is reported (never silent).
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT_SCHEMA_KEY = "NEXOLAB.volume.schema"
ROOT_MODE_KEY = "NEXOLAB.volume.root.mode"
ROOT_UID_KEY = "NEXOLAB.volume.root.uid"
ROOT_GID_KEY = "NEXOLAB.volume.root.gid"
ROOT_METADATA_KEYS = {
    ROOT_SCHEMA_KEY,
    ROOT_MODE_KEY,
    ROOT_UID_KEY,
    ROOT_GID_KEY,
}

# Extended attributes. The declaration key is optional so archives written before the
# change stay valid; extractors older than this change reject it as an unsupported
# NEXOLAB.volume.* key instead of silently dropping the metadata.
XATTRS_KEY = "NEXOLAB.volume.xattrs"
XATTRS_SCHEME = "user-v1"
ROOT_XATTR_PREFIX = "NEXOLAB.volume.root.xattr."
XATTR_PAX_PREFIX = "SCHILY.xattr."
XATTR_NAMESPACE = "user."
# Metadata records of other tar dialects that this extractor cannot apply: refused, never ignored.
FOREIGN_METADATA_PREFIXES = ("LIBARCHIVE.xattr.", "SCHILY.acl.", "RHT.security.", "SCHILY.fflags")
MAX_XATTR_NAME_BYTES = 255
MAX_XATTR_VALUE_BYTES = 64 * 1024
MAX_XATTRS_PER_ENTRY = 64
MAX_XATTR_BYTES_PER_ENTRY = 256 * 1024
MAX_XATTR_BYTES_TOTAL = 64 * 1024 * 1024
TAR_ENCODING = "utf-8"
TAR_ERRORS = "surrogateescape"


class VolumeArchiveFailure(ValueError):
    pass


# ----------------------------------------------------------------- extended attributes


def _validate_xattr_name(name: str) -> str:
    if not isinstance(name, str) or not name.startswith(XATTR_NAMESPACE) or name == XATTR_NAMESPACE:
        raise VolumeArchiveFailure("extended attribute outside the user. namespace is not allowed")
    try:
        encoded = name.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise VolumeArchiveFailure("extended attribute name is not valid UTF-8") from exc
    if len(encoded) > MAX_XATTR_NAME_BYTES or any(ch in name for ch in ("\x00", "=", "\n")):
        raise VolumeArchiveFailure("extended attribute name is invalid")
    return name


def _check_xattr_caps(xattrs: dict[str, bytes], label: str) -> int:
    if len(xattrs) > MAX_XATTRS_PER_ENTRY:
        raise VolumeArchiveFailure(f"{label}: too many extended attributes (cap {MAX_XATTRS_PER_ENTRY})")
    total = 0
    for name, value in xattrs.items():
        if len(value) > MAX_XATTR_VALUE_BYTES:
            raise VolumeArchiveFailure(
                f"{label}: extended attribute value exceeds {MAX_XATTR_VALUE_BYTES} bytes")
        total += len(name.encode("utf-8")) + len(value)
    if total > MAX_XATTR_BYTES_PER_ENTRY:
        raise VolumeArchiveFailure(
            f"{label}: extended attributes exceed {MAX_XATTR_BYTES_PER_ENTRY} bytes per entry")
    return total


def read_user_xattrs(path: Path, label: str = "entry") -> dict[str, bytes]:
    """Read-only: the ``user.*`` extended attributes of ``path`` (symlinks are not followed).

    Other namespaces (security.*, trusted.*, system.*) are never read. A file system without
    xattr support yields no attributes. Cap violations fail closed (no silent truncation).
    """
    if not hasattr(os, "listxattr"):
        return {}
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError as exc:
        if exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
            return {}
        raise VolumeArchiveFailure(f"{label}: extended attributes are not readable") from exc
    result: dict[str, bytes] = {}
    for name in sorted(names):
        if not name.startswith(XATTR_NAMESPACE):
            continue
        _validate_xattr_name(name)
        try:
            result[name] = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            if exc.errno == errno.ENODATA:  # removed meanwhile; the capture signature detects it
                continue
            raise VolumeArchiveFailure(f"{label}: extended attribute is not readable") from exc
    _check_xattr_caps(result, label)
    return result


def xattr_digest(xattrs: dict[str, bytes]) -> str:
    """Stable digest of an attribute set (used in the 'unchanged during capture' signature)."""
    digest = hashlib.sha256()
    for name in sorted(xattrs):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big") + encoded)
        digest.update(len(xattrs[name]).to_bytes(4, "big") + xattrs[name])
    return digest.hexdigest()


def xattr_pax_headers(xattrs: dict[str, bytes], prefix: str = XATTR_PAX_PREFIX) -> dict[str, str]:
    """PAX records for an attribute set; bytes survive via surrogateescape (hdrcharset=BINARY)."""
    return {prefix + _validate_xattr_name(name): value.decode(TAR_ENCODING, TAR_ERRORS)
            for name, value in sorted(xattrs.items())}


def _decode_xattr_records(headers: dict[str, str], prefix: str, label: str) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for key, value in headers.items():
        if key.startswith(prefix):
            name = _validate_xattr_name(key[len(prefix):])
            result[name] = value.encode(TAR_ENCODING, TAR_ERRORS)
    _check_xattr_caps(result, label)
    return result


class XattrBudget:
    """Total cap across one archive (capture and extract)."""

    def __init__(self) -> None:
        self.entries = 0
        self.attributes = 0
        self.bytes = 0

    def add(self, xattrs: dict[str, bytes], label: str) -> None:
        if not xattrs:
            return
        size = _check_xattr_caps(xattrs, label)
        if self.bytes + size > MAX_XATTR_BYTES_TOTAL:
            raise VolumeArchiveFailure(f"extended attributes exceed the archive cap of {MAX_XATTR_BYTES_TOTAL} bytes")
        self.entries += 1
        self.attributes += len(xattrs)
        self.bytes += size

    def summary(self) -> dict[str, Any]:
        return {"scheme": XATTRS_SCHEME, "entries": self.entries, "attributes": self.attributes,
                "bytes": self.bytes}


def global_pax_headers(metadata: os.stat_result, root_xattrs: dict[str, bytes]) -> dict[str, str]:
    """Root metadata plus the xattr declaration (and root attributes, never SCHILY.* globally)."""
    headers = root_pax_headers(metadata)
    headers[XATTRS_KEY] = XATTRS_SCHEME
    headers.update(xattr_pax_headers(root_xattrs, ROOT_XATTR_PREFIX))
    return headers


def member_xattrs(member: tarfile.TarInfo, scheme_declared: bool) -> dict[str, bytes]:
    """Validated ``user.*`` attributes of one member (refuses foreign or undeclared records)."""
    headers = member.pax_headers or {}
    for key in headers:
        if key.startswith(FOREIGN_METADATA_PREFIXES):
            raise VolumeArchiveFailure(f"volume archive entry carries unsupported metadata records: {member.name}")
    xattrs = _decode_xattr_records(headers, XATTR_PAX_PREFIX, member.name)
    if xattrs and not scheme_declared:
        raise VolumeArchiveFailure("volume archive carries xattr records without declaring the xattr scheme")
    return xattrs


def parse_xattr_scheme(archive: tarfile.TarFile) -> tuple[bool, dict[str, bytes]]:
    """Returns (scheme declared, root attributes) from the global PAX header."""
    headers = archive.pax_headers
    for key in headers:
        if key.startswith(XATTR_PAX_PREFIX) or key.startswith(FOREIGN_METADATA_PREFIXES):
            raise VolumeArchiveFailure("volume archive global header must not carry per-entry metadata records")
    declared = XATTRS_KEY in headers
    if declared and headers[XATTRS_KEY] != XATTRS_SCHEME:
        raise VolumeArchiveFailure("volume archive xattr scheme is unsupported")
    root = _decode_xattr_records(headers, ROOT_XATTR_PREFIX, "volume root")
    if root and not declared:
        raise VolumeArchiveFailure("volume archive carries xattr records without declaring the xattr scheme")
    return declared, root


class XattrApplier:
    """Applies attributes on extract; fails closed when the destination cannot store them."""

    def __init__(self, allow_loss: bool) -> None:
        self.allow_loss = allow_loss
        self.applied = 0
        self.dropped = 0
        self.dropped_entries = 0
        self.unsupported_reason: str | None = None

    def apply(self, path: Path, xattrs: dict[str, bytes], label: str) -> list[str]:
        applied: list[str] = []
        lost = 0
        for name, value in sorted(xattrs.items()):
            reason = None
            if not hasattr(os, "setxattr"):
                reason = "this platform has no extended attribute support"
            else:
                try:
                    os.setxattr(path, name, value, follow_symlinks=False)
                    if os.getxattr(path, name, follow_symlinks=False) != value:
                        reason = "extended attribute read-back differs"
                    else:
                        applied.append(name)
                except OSError as exc:
                    reason = f"destination cannot store user extended attributes ({errno.errorcode.get(exc.errno, exc.errno)})"
            if reason is not None:
                if not self.allow_loss:
                    raise VolumeArchiveFailure(
                        f"{reason}: object metadata of {label} would be lost; restore onto a file system with "
                        "user xattr support (e.g. ext4/xfs) or pass --allow-xattr-loss to accept the loss explicitly")
                self.unsupported_reason = reason
                lost += 1
        self.applied += len(applied)
        self.dropped += lost
        self.dropped_entries += 1 if lost else 0
        return applied


def safe_name(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise VolumeArchiveFailure("archive path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VolumeArchiveFailure("archive path is unsafe")
    return path.as_posix()


def inspect_root(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise VolumeArchiveFailure(f"{label} is not accessible") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise VolumeArchiveFailure(f"{label} must be a non-symlink directory")
    return metadata


def root_pax_headers(metadata: os.stat_result) -> dict[str, str]:
    return {
        ROOT_SCHEMA_KEY: "1",
        ROOT_MODE_KEY: f"{stat.S_IMODE(metadata.st_mode):04o}",
        ROOT_UID_KEY: str(metadata.st_uid),
        ROOT_GID_KEY: str(metadata.st_gid),
    }


def parse_root_metadata(archive: tarfile.TarFile) -> tuple[int, int, int]:
    headers = archive.pax_headers
    missing = ROOT_METADATA_KEYS - set(headers)
    if missing:
        raise VolumeArchiveFailure(
            "volume archive root metadata is incomplete: " + ", ".join(sorted(missing))
        )
    unexpected = {
        key
        for key in headers
        if key.startswith("NEXOLAB.volume.")
        and key not in ROOT_METADATA_KEYS
        and key != XATTRS_KEY
        and not key.startswith(ROOT_XATTR_PREFIX)
    }
    if unexpected:
        raise VolumeArchiveFailure(
            "volume archive root metadata contains unsupported keys"
        )
    if headers[ROOT_SCHEMA_KEY] != "1":
        raise VolumeArchiveFailure("volume archive root metadata schema is unsupported")
    try:
        mode = int(headers[ROOT_MODE_KEY], 8)
        uid = int(headers[ROOT_UID_KEY], 10)
        gid = int(headers[ROOT_GID_KEY], 10)
    except ValueError as exc:
        raise VolumeArchiveFailure("volume archive root metadata is invalid") from exc
    if not 0 <= mode <= 0o7777 or uid < 0 or gid < 0:
        raise VolumeArchiveFailure("volume archive root metadata is out of range")
    if headers[ROOT_MODE_KEY] != f"{mode:04o}":
        raise VolumeArchiveFailure("volume archive root mode is not canonical")
    if headers[ROOT_UID_KEY] != str(uid) or headers[ROOT_GID_KEY] != str(gid):
        raise VolumeArchiveFailure("volume archive root ownership is not canonical")
    return mode, uid, gid


def collect(source: Path) -> tuple[os.stat_result, list[tuple[str, Path, os.stat_result]]]:
    root_metadata = inspect_root(source, "source volume")
    entries: list[tuple[str, Path, os.stat_result]] = []
    for path in sorted(source.rglob("*")):
        relative = safe_name(path.relative_to(source).as_posix())
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise VolumeArchiveFailure(f"volume symlink is forbidden: {relative}")
        if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise VolumeArchiveFailure(f"volume special file is forbidden: {relative}")
        entries.append((relative, path, metadata))
    if not any(stat.S_ISREG(metadata.st_mode) for _, _, metadata in entries):
        raise VolumeArchiveFailure("source volume contains no files")
    return root_metadata, entries


def create_archive(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise VolumeArchiveFailure("volume archive output already exists")
    root_metadata, entries = collect(source)
    budget = XattrBudget()
    root_xattrs = read_user_xattrs(source, "volume root")
    budget.add(root_xattrs, "volume root")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as destination:
            with tarfile.open(
                fileobj=destination,
                mode="w",
                format=tarfile.PAX_FORMAT,
                pax_headers=global_pax_headers(root_metadata, root_xattrs),
                encoding=TAR_ENCODING,
                errors=TAR_ERRORS,
            ) as archive:
                for relative, path, metadata in entries:
                    info = tarfile.TarInfo(relative)
                    info.mode = stat.S_IMODE(metadata.st_mode)
                    info.uid = metadata.st_uid
                    info.gid = metadata.st_gid
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    xattrs = read_user_xattrs(path, relative)
                    budget.add(xattrs, relative)
                    info.pax_headers = xattr_pax_headers(xattrs)
                    if stat.S_ISDIR(metadata.st_mode):
                        info.type = tarfile.DIRTYPE
                        info.size = 0
                        archive.addfile(info)
                    else:
                        info.type = tarfile.REGTYPE
                        info.size = metadata.st_size
                        with path.open("rb") as content:
                            archive.addfile(info, content)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(output)
        return budget.summary()
    except (OSError, tarfile.TarError, VolumeArchiveFailure) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, VolumeArchiveFailure):
            raise
        raise VolumeArchiveFailure("could not create deterministic volume archive") from exc


def validate_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    names: set[str] = set()
    for member in archive.getmembers():
        name = safe_name(member.name)
        if name in names:
            raise VolumeArchiveFailure(f"duplicate volume archive entry: {name}")
        names.add(name)
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise VolumeArchiveFailure(
                f"volume archive entry must be file or directory: {name}"
            )
        members.append(member)
    if not any(member.isfile() for member in members):
        raise VolumeArchiveFailure("volume archive contains no files")
    return members


def destination_is_empty(destination: Path) -> os.stat_result:
    if destination.exists():
        metadata = inspect_root(destination, "restore volume")
        try:
            if next(destination.iterdir(), None) is not None:
                raise VolumeArchiveFailure("restore volume must be empty")
        except OSError as exc:
            raise VolumeArchiveFailure("restore volume is not accessible") from exc
        return metadata
    destination.mkdir(parents=True, mode=0o700)
    return inspect_root(destination, "restore volume")


def apply_path_metadata(path: Path, *, mode: int, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)
        os.chmod(path, mode & 0o7777)
    except PermissionError as exc:
        raise VolumeArchiveFailure("restoring volume ownership requires root") from exc


def apply_ownership(path: Path, member: tarfile.TarInfo) -> None:
    apply_path_metadata(path, mode=member.mode, uid=member.uid, gid=member.gid)


def apply_root_metadata(destination: Path, metadata: tuple[int, int, int]) -> None:
    mode, uid, gid = metadata
    apply_path_metadata(destination, mode=mode, uid=uid, gid=gid)


def restore_original_root(destination: Path, metadata: os.stat_result) -> None:
    try:
        os.chown(destination, metadata.st_uid, metadata.st_gid)
        os.chmod(destination, stat.S_IMODE(metadata.st_mode))
    except OSError:
        pass


def _make_directories(target: Path, destination: Path, created: list[Path]) -> None:
    """mkdir -p below ``destination``, recording every directory this call created."""
    missing = []
    probe = target
    while probe != destination and not probe.exists():
        missing.append(probe)
        probe = probe.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def extract_archive(archive_path: Path, destination: Path, *, allow_xattr_loss: bool = False) -> dict[str, Any]:
    """Extracts into an empty destination; returns a report (counts only, no names or values).

    ``report["xattrs"]["scheme"]`` is ``none`` for archives written before xattr capture
    (nothing to restore, extraction unchanged) and ``user-v1`` otherwise. With
    ``allow_xattr_loss`` a destination without xattr support is reported as ``dropped`` > 0
    instead of failing; the default fails closed.
    """
    original_root = destination_is_empty(destination)
    try:
        archive = tarfile.open(archive_path, mode="r:", encoding=TAR_ENCODING, errors=TAR_ERRORS)
    except (OSError, tarfile.TarError) as exc:
        raise VolumeArchiveFailure("volume archive is not readable") from exc
    created: list[Path] = []
    root_xattrs_applied: list[str] = []
    applier = XattrApplier(allow_xattr_loss)
    budget = XattrBudget()
    declared = False
    try:
        with archive:
            members = validate_members(archive)
            root_metadata = parse_root_metadata(archive)
            declared, root_xattrs = parse_xattr_scheme(archive)
            budget.add(root_xattrs, "volume root")
            xattrs_by_member = {}
            for member in members:
                xattrs = member_xattrs(member, declared)
                budget.add(xattrs, member.name)
                xattrs_by_member[member.name] = xattrs
            directories = sorted(
                (member for member in members if member.isdir()),
                key=lambda member: len(PurePosixPath(member.name).parts),
            )
            files = [member for member in members if member.isfile()]
            for member in directories:
                target = destination / safe_name(member.name)
                _make_directories(target, destination, created)
            for member in files:
                target = destination / safe_name(member.name)
                # Track implicitly created parents too, so a failed extract leaves nothing behind.
                _make_directories(target.parent, destination, created)
                source = archive.extractfile(member)
                if source is None:
                    raise VolumeArchiveFailure(
                        f"volume archive entry has no content: {member.name}"
                    )
                with target.open("xb") as output:
                    created.append(target)
                    shutil.copyfileobj(source, output)
                # Before ownership/mode: the extracting user still owns the new file.
                applier.apply(target, xattrs_by_member[member.name], member.name)
                apply_ownership(target, member)
            for member in sorted(
                directories,
                key=lambda candidate: len(PurePosixPath(candidate.name).parts),
                reverse=True,
            ):
                target = destination / safe_name(member.name)
                applier.apply(target, xattrs_by_member[member.name], member.name)
                apply_ownership(target, member)
            root_xattrs_applied = applier.apply(destination, root_xattrs, "volume root")
            apply_root_metadata(destination, root_metadata)
    except (OSError, tarfile.TarError, VolumeArchiveFailure):
        for path in sorted(created, key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        for name in root_xattrs_applied:
            try:
                os.removexattr(destination, name, follow_symlinks=False)
            except OSError:
                pass
        restore_original_root(destination, original_root)
        raise
    report: dict[str, Any] = {"scheme": XATTRS_SCHEME if declared else "none",
                              "entries": budget.entries, "attributes": budget.attributes,
                              "applied": applier.applied, "dropped": applier.dropped,
                              "dropped_entries": applier.dropped_entries}
    if applier.dropped:
        report["loss_reason"] = applier.unsupported_reason
    return {"xattrs": report}


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, required=True)
    extract.add_argument(
        "--allow-xattr-loss",
        action="store_true",
        help="do not fail when the destination cannot store user.* xattrs; the loss is reported",
    )
    args = parser.parse_args()

    if args.command == "create":
        summary = create_archive(args.source, args.output)
        print(f"Created deterministic volume archive: {args.output}")
        print(json.dumps({"xattrs": summary}, sort_keys=True))
    else:
        report = extract_archive(args.archive, args.destination, allow_xattr_loss=args.allow_xattr_loss)
        print(f"Restored deterministic volume archive: {args.destination}")
        if report["xattrs"]["dropped"]:
            print(
                f"WARNING: {report['xattrs']['dropped']} extended attribute(s) were NOT restored "
                f"({report['xattrs'].get('loss_reason')}); object metadata is degraded",
                file=sys.stderr,
            )
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VolumeArchiveFailure as exc:
        print(f"NEXOLAB volume archive failed: {exc}")
        raise SystemExit(1) from exc
