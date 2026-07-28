from __future__ import annotations

import importlib.util
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "nexolab-volume-archive.py"
SPEC = importlib.util.spec_from_file_location("nexolab_volume_archive", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
volume_archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(volume_archive)


def add_regular_file(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(content))


def write_tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, content in members:
            add_regular_file(archive, name, content)


def ignore_ownership(path: Path, member: tarfile.TarInfo) -> None:
    os.chmod(path, member.mode & 0o777)


def test_archive_is_deterministic_and_round_trips_root_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source.chmod(0o750)
    (source / "dynamic-security.json").write_text('{"clients":[]}\n', encoding="utf-8")
    nested = source / "state"
    nested.mkdir()
    (nested / "mosquitto.db").write_bytes(b"persistent-state")
    source_metadata = source.lstat()

    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    volume_archive.create_archive(source, first)
    volume_archive.create_archive(source, second)
    assert first.read_bytes() == second.read_bytes()

    restored_root: list[tuple[int, int, int]] = []
    monkeypatch.setattr(volume_archive, "apply_ownership", ignore_ownership)
    monkeypatch.setattr(
        volume_archive,
        "apply_root_metadata",
        lambda destination, metadata: restored_root.append(metadata),
    )
    destination = tmp_path / "restore"
    volume_archive.extract_archive(first, destination)
    assert restored_root == [
        (
            stat.S_IMODE(source_metadata.st_mode),
            source_metadata.st_uid,
            source_metadata.st_gid,
        )
    ]
    assert (destination / "dynamic-security.json").read_text(encoding="utf-8") == (
        '{"clients":[]}\n'
    )
    assert (destination / "state" / "mosquitto.db").read_bytes() == b"persistent-state"


def test_create_rejects_source_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    (source / "linked").symlink_to(target)

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="symlink"):
        volume_archive.create_archive(source, tmp_path / "archive.tar")


def test_extract_rejects_path_traversal_without_writing(tmp_path: Path) -> None:
    archive_path = tmp_path / "traversal.tar"
    write_tar(archive_path, [("../escape", b"blocked")])
    destination = tmp_path / "restore"

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="unsafe"):
        volume_archive.extract_archive(archive_path, destination)

    assert not (tmp_path / "escape").exists()
    assert destination.exists()
    assert list(destination.iterdir()) == []


def test_extract_rejects_duplicate_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.tar"
    with tarfile.open(archive_path, "w") as archive:
        add_regular_file(archive, "dynamic-security.json", b"one")
        add_regular_file(archive, "dynamic-security.json", b"two")

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="duplicate"):
        volume_archive.extract_archive(archive_path, tmp_path / "restore")


def test_extract_rejects_symlink_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.tar"
    with tarfile.open(archive_path, "w") as archive:
        link = tarfile.TarInfo("dynamic-security.json")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        archive.addfile(link)
        add_regular_file(archive, "state", b"value")

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="file or directory"):
        volume_archive.extract_archive(archive_path, tmp_path / "restore")


def test_extract_rejects_missing_root_metadata(tmp_path: Path) -> None:
    archive_path = tmp_path / "legacy.tar"
    write_tar(archive_path, [("dynamic-security.json", b"state")])
    destination = tmp_path / "restore"

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="root metadata"):
        volume_archive.extract_archive(archive_path, destination)

    assert destination.exists()
    assert list(destination.iterdir()) == []


def test_extract_rejects_non_empty_destination(tmp_path: Path) -> None:
    archive_path = tmp_path / "valid.tar"
    write_tar(archive_path, [("dynamic-security.json", b"state")])
    destination = tmp_path / "restore"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(volume_archive.VolumeArchiveFailure, match="must be empty"):
        volume_archive.extract_archive(archive_path, destination)

    assert sentinel.read_text(encoding="utf-8") == "preserve"
