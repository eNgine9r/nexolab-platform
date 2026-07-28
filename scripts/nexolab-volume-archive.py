#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath


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


class VolumeArchiveFailure(ValueError):
    pass


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
        if key.startswith("NEXOLAB.volume.") and key not in ROOT_METADATA_KEYS
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


def create_archive(source: Path, output: Path) -> None:
    if output.exists():
        raise VolumeArchiveFailure("volume archive output already exists")
    root_metadata, entries = collect(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as destination:
            with tarfile.open(
                fileobj=destination,
                mode="w",
                format=tarfile.PAX_FORMAT,
                pax_headers=root_pax_headers(root_metadata),
            ) as archive:
                for relative, path, metadata in entries:
                    info = tarfile.TarInfo(relative)
                    info.mode = stat.S_IMODE(metadata.st_mode)
                    info.uid = metadata.st_uid
                    info.gid = metadata.st_gid
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
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
    except (OSError, tarfile.TarError) as exc:
        temporary.unlink(missing_ok=True)
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


def extract_archive(archive_path: Path, destination: Path) -> None:
    original_root = destination_is_empty(destination)
    try:
        archive = tarfile.open(archive_path, mode="r:")
    except (OSError, tarfile.TarError) as exc:
        raise VolumeArchiveFailure("volume archive is not readable") from exc
    created: list[Path] = []
    try:
        with archive:
            members = validate_members(archive)
            root_metadata = parse_root_metadata(archive)
            directories = sorted(
                (member for member in members if member.isdir()),
                key=lambda member: len(PurePosixPath(member.name).parts),
            )
            files = [member for member in members if member.isfile()]
            for member in directories:
                target = destination / safe_name(member.name)
                target.mkdir(parents=True, exist_ok=True)
                created.append(target)
            for member in files:
                target = destination / safe_name(member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise VolumeArchiveFailure(
                        f"volume archive entry has no content: {member.name}"
                    )
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                apply_ownership(target, member)
                created.append(target)
            for member in sorted(
                directories,
                key=lambda candidate: len(PurePosixPath(candidate.name).parts),
                reverse=True,
            ):
                apply_ownership(destination / safe_name(member.name), member)
            apply_root_metadata(destination, root_metadata)
    except (OSError, tarfile.TarError, VolumeArchiveFailure):
        for path in sorted(created, key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        restore_original_root(destination, original_root)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "create":
        create_archive(args.source, args.output)
        print(f"Created deterministic volume archive: {args.output}")
    else:
        extract_archive(args.archive, args.destination)
        print(f"Restored deterministic volume archive: {args.destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VolumeArchiveFailure as exc:
        print(f"NEXOLAB volume archive failed: {exc}")
        raise SystemExit(1) from exc
