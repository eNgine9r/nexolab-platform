#!/usr/bin/env python3
"""Capture and explicitly restore NEXOLAB edge SQLite state for controlled deployment.

This helper intentionally operates only on filesystem paths. Deployment tooling
is responsible for ensuring capture runs in the live Device Agent container and
restore runs only after that Device Agent is stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")


class SnapshotError(RuntimeError):
    pass


def _quick_check(path: Path) -> None:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise SnapshotError(f"SQLite quick_check failed for {path}: {error}") from error
    if rows != ["ok"]:
        raise SnapshotError(f"SQLite quick_check failed for {path}: {rows}")


def _quick_check_connection(connection: sqlite3.Connection, label: str) -> None:
    try:
        rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    except sqlite3.Error as error:
        raise SnapshotError(f"SQLite quick_check failed for {label}: {error}") from error
    if rows != ["ok"]:
        raise SnapshotError(f"SQLite quick_check failed for {label}: {rows}")


def _read_runtime_metadata(path: Path) -> tuple[int, int, int, dict[str, int]]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            revision_row = connection.execute(
                "SELECT revision FROM acquisition_registry_state WHERE singleton = 1"
            ).fetchone()
            if revision_row is None:
                raise SnapshotError("acquisition_registry_state singleton is missing")
            queue_row = connection.execute("SELECT COUNT(*) FROM outbound_queue").fetchone()
            if queue_row is None:
                raise SnapshotError("outbound_queue count is unavailable")
            queue_high_water_row = connection.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = 'outbound_queue'"
            ).fetchone()
            queue_high_water = int(queue_high_water_row[0]) if queue_high_water_row else 0
            sequence_rows = connection.execute(
                "SELECT stream, last_sequence FROM node_stream_sequences ORDER BY stream"
            ).fetchall()
            sequences = {str(row[0]): int(row[1]) for row in sequence_rows}
            return int(revision_row[0]), int(queue_row[0]), queue_high_water, sequences
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise SnapshotError(f"required edge SQLite metadata is unavailable: {error}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def capture(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source.resolve()
    snapshot = args.snapshot.resolve()
    metadata = args.metadata.resolve()
    if not source.is_file():
        raise SnapshotError(f"edge SQLite source does not exist: {source}")
    if snapshot == source or metadata in {source, snapshot}:
        raise SnapshotError("source, snapshot and metadata paths must be distinct")
    if snapshot.exists() or metadata.exists():
        raise SnapshotError("snapshot/metadata destination already exists")
    if not SHA_PATTERN.fullmatch(args.deployed_source) or not SHA_PATTERN.fullmatch(
        args.target_source
    ):
        raise SnapshotError("deployed and target source must be exact commit SHAs")
    if not EVIDENCE_ID_PATTERN.fullmatch(args.deployment_evidence_id):
        raise SnapshotError("deployment evidence id must be a UTC deployment timestamp")
    if not IMAGE_ID_PATTERN.fullmatch(args.deployed_device_agent_image_id):
        raise SnapshotError("deployed Device Agent image must be an immutable SHA-256 image id")

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    completed = False
    try:
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(snapshot)
        try:
            _quick_check_connection(source_connection, str(source))
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        os.chmod(snapshot, 0o600)
        _quick_check(snapshot)
        _fsync_file(snapshot)
        _fsync_directory(snapshot.parent)
        registry_revision, queue_count, queue_high_water, stream_sequences = (
            _read_runtime_metadata(snapshot)
        )

        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "kind": "nexolab-edge-sqlite-pre-cutover",
            "captured_at": datetime.now(UTC).isoformat(),
            "database_name": source.name,
            "snapshot_name": snapshot.name,
            "sha256": _sha256(snapshot),
            "bytes": snapshot.stat().st_size,
            "registry_revision": registry_revision,
            "outbound_queue_count": queue_count,
            "outbound_queue_high_water": queue_high_water,
            "node_stream_sequences": stream_sequences,
            "deployed_source": args.deployed_source,
            "target_source": args.target_source,
            "deployment_evidence_id": args.deployment_evidence_id,
            "deployed_device_agent_image_id": args.deployed_device_agent_image_id,
            "source_quick_check": "ok",
            "snapshot_quick_check": "ok",
        }
        _atomic_json(metadata, document)
        completed = True
        return document
    except sqlite3.Error as error:
        raise SnapshotError(f"SQLite backup API failed: {error}") from error
    finally:
        if not completed:
            snapshot.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotError(f"snapshot metadata is unreadable: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError("snapshot metadata schema is unsupported")
    if document.get("kind") != "nexolab-edge-sqlite-pre-cutover":
        raise SnapshotError("snapshot metadata kind is invalid")
    if document.get("source_quick_check") != "ok" or document.get(
        "snapshot_quick_check"
    ) != "ok":
        raise SnapshotError("snapshot metadata does not record both integrity checks")
    image_id = document.get("deployed_device_agent_image_id")
    if not isinstance(image_id, str) or not IMAGE_ID_PATTERN.fullmatch(image_id):
        raise SnapshotError("snapshot metadata Device Agent image id is invalid")
    return document


def restore(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = args.snapshot.resolve()
    metadata = args.metadata.resolve()
    destination = args.destination.resolve()
    if not snapshot.is_file() or not metadata.is_file():
        raise SnapshotError("snapshot and metadata files are required")
    document = _load_metadata(metadata)
    if document.get("deployed_source") != args.expected_deployed_source:
        raise SnapshotError("snapshot deployed source does not match the requested rollback evidence")
    if document.get("target_source") != args.expected_target_source:
        raise SnapshotError("snapshot target source does not match the requested rollback evidence")
    if document.get("deployment_evidence_id") != args.expected_deployment_evidence_id:
        raise SnapshotError("snapshot deployment evidence id does not match")
    if snapshot.name != document.get("snapshot_name"):
        raise SnapshotError("snapshot filename does not match metadata")
    if snapshot.stat().st_size != document.get("bytes"):
        raise SnapshotError("snapshot byte size does not match metadata")
    if _sha256(snapshot) != document.get("sha256"):
        raise SnapshotError("snapshot SHA-256 does not match metadata")
    _quick_check(snapshot)
    revision, queue_count, queue_high_water, stream_sequences = _read_runtime_metadata(snapshot)
    if (
        revision != document.get("registry_revision")
        or queue_count != document.get("outbound_queue_count")
        or queue_high_water != document.get("outbound_queue_high_water")
        or stream_sequences != document.get("node_stream_sequences")
    ):
        raise SnapshotError("snapshot registry/queue metadata does not match")

    if not destination.is_file():
        raise SnapshotError("existing edge SQLite destination is required for guarded restore")
    sidecars = [
        destination.with_name(destination.name + suffix)
        for suffix in ("-wal", "-shm", "-journal")
    ]
    if any(path.exists() for path in sidecars):
        raise SnapshotError(
            "edge SQLite sidecar exists after Device Agent stop; refusing to discard newer state"
        )
    _, current_queue_count, current_queue_high_water, current_stream_sequences = (
        _read_runtime_metadata(destination)
    )
    if (
        current_queue_count != queue_count
        or current_queue_high_water != queue_high_water
        or current_stream_sequences != stream_sequences
    ):
        raise SnapshotError(
            "stopped edge SQLite queue/sequence state advanced after snapshot; "
            "refusing to discard newer state"
        )
    destination_stat = destination.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore-{os.getpid()}")
    try:
        with snapshot.open("rb") as source_stream, temporary.open("xb") as destination_stream:
            for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                destination_stream.write(chunk)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())
        os.chown(temporary, destination_stat.st_uid, destination_stat.st_gid)
        os.chmod(temporary, destination_stat.st_mode & 0o777)
        _quick_check(temporary)
        restored_revision, restored_queue, restored_high_water, restored_sequences = (
            _read_runtime_metadata(temporary)
        )
        if (
            restored_revision != revision
            or restored_queue != queue_count
            or restored_high_water != queue_high_water
            or restored_sequences != stream_sequences
        ):
            raise SnapshotError("restored temporary database metadata changed")
        if _sha256(temporary) != document["sha256"]:
            raise SnapshotError("restored temporary database SHA-256 changed")
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _quick_check(destination)
        final_revision, final_queue, final_high_water, final_sequences = (
            _read_runtime_metadata(destination)
        )
        if (
            final_revision != revision
            or final_queue != queue_count
            or final_high_water != queue_high_water
            or final_sequences != stream_sequences
        ):
            raise SnapshotError("restored database metadata does not match snapshot")
        if _sha256(destination) != document["sha256"]:
            raise SnapshotError("restored database SHA-256 does not match snapshot")
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "nexolab-edge-sqlite-restore-result",
        "status": "restored",
        "sha256": document["sha256"],
        "bytes": document["bytes"],
        "registry_revision": revision,
        "outbound_queue_count": queue_count,
        "outbound_queue_high_water": queue_high_water,
        "node_stream_sequences": stream_sequences,
        "deployment_evidence_id": document["deployment_evidence_id"],
        "deployed_source": document["deployed_source"],
        "deployed_device_agent_image_id": document["deployed_device_agent_image_id"],
        "target_source": document["target_source"],
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture")
    capture_parser.add_argument("--source", type=Path, required=True)
    capture_parser.add_argument("--snapshot", type=Path, required=True)
    capture_parser.add_argument("--metadata", type=Path, required=True)
    capture_parser.add_argument("--deployed-source", required=True)
    capture_parser.add_argument("--target-source", required=True)
    capture_parser.add_argument("--deployment-evidence-id", required=True)
    capture_parser.add_argument("--deployed-device-agent-image-id", required=True)
    capture_parser.set_defaults(handler=capture)

    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("--snapshot", type=Path, required=True)
    restore_parser.add_argument("--metadata", type=Path, required=True)
    restore_parser.add_argument("--destination", type=Path, required=True)
    restore_parser.add_argument("--expected-deployed-source", required=True)
    restore_parser.add_argument("--expected-target-source", required=True)
    restore_parser.add_argument("--expected-deployment-evidence-id", required=True)
    restore_parser.set_defaults(handler=restore)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = args.handler(args)
    except SnapshotError as error:
        print(f"NEXOLAB edge SQLite snapshot stopped safely: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
