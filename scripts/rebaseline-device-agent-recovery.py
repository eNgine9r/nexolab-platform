#!/usr/bin/env python3
"""Establish sanitized Device Agent recovery authority from one running container.

The command is intentionally narrower than a deployment. It never stops, pauses,
restarts, or recreates the production Device Agent. It exports the running
container filesystem, imports it with an explicit non-secret config allowlist,
and publishes ignored local evidence only after every verification succeeds.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn


SCHEMA_VERSION = 1
REPOSITORY = "eNgine9r/nexolab-platform"
EXPECTED_EDGE_VOLUME = "nexolab-edge_edge-data"
EXPECTED_DEPLOYMENT_MODE = "lan"
EXPECTED_PLATFORM = "linux/arm64"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STAMP_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
ALLOWED_DIFF = ["A /host", "A /host/dev"]
SAFE_ENV = [
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONUNBUFFERED=1",
    "PYTHONPATH=/app/site-packages",
]
SAFE_CONFIG: dict[str, Any] = {
    "user": "nonroot",
    "working_dir": "/app",
    "entrypoint": ["/usr/bin/python3.13"],
    "cmd": ["dual_bus_main.py"],
    "exposed_ports": ["8081/tcp"],
    "healthcheck": {
        "Test": [
            "CMD",
            "/usr/bin/python3",
            "-c",
            "import json,urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2))",
        ],
        "Interval": 15_000_000_000,
        "Timeout": 3_000_000_000,
        "StartPeriod": 10_000_000_000,
        "Retries": 3,
    },
    "environment": SAFE_ENV,
}
EDGE_SQLITE_AUDIT = r"""
import hashlib
import json
import sqlite3

path = "/var/lib/nexolab/edge.db"
connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=0", uri=True)
try:
    connection.execute("PRAGMA query_only = ON")
    connection.execute("BEGIN")
    quick_check = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    if quick_check != ["ok"]:
        raise RuntimeError(f"edge SQLite quick_check failed: {quick_check}")
    revision = connection.execute(
        "SELECT revision FROM acquisition_registry_state WHERE singleton = 1"
    ).fetchone()
    queue_count = connection.execute("SELECT COUNT(*) FROM outbound_queue").fetchone()
    queue_high_water = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'outbound_queue'"
    ).fetchone()
    sequences = connection.execute(
        "SELECT stream, last_sequence FROM node_stream_sequences ORDER BY stream"
    ).fetchall()
    if revision is None or queue_count is None:
        raise RuntimeError("required edge SQLite metadata is unavailable")
    serialized = connection.serialize()
    result = {
        "database_name": "edge.db",
        "quick_check": "ok",
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "bytes": len(serialized),
        "registry_revision": int(revision[0]),
        "outbound_queue_count": int(queue_count[0]),
        "outbound_queue_high_water": int(queue_high_water[0]) if queue_high_water else 0,
        "node_stream_sequences": {str(row[0]): int(row[1]) for row in sequences},
        "read_only": True,
    }
    print(json.dumps(result, sort_keys=True))
finally:
    connection.close()
"""


class RebaselineError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise RebaselineError(message)


def run(
    command: list[str],
    *,
    input_text: str | None = None,
    capture_bytes: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        command,
        input=input_text.encode() if input_text is not None and capture_bytes else input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not capture_bytes,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode(errors="replace") if capture_bytes else result.stderr
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else "no diagnostic"
        fail(f"command failed ({command[0]}): {detail}")
    return result


def docker_json(arguments: list[str]) -> Any:
    result = run(["docker", *arguments])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"Docker returned invalid JSON for {arguments[0]}: {error}")


def docker_format_json(object_name: str, expression: str, *, size: bool = False) -> Any:
    command = ["docker", "container", "inspect"]
    if size:
        command.append("--size")
    command.extend(["--format", f"{{{{json {expression}}}}}", object_name])
    result = run(command)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"Docker inspect returned invalid safe-field JSON: {error}")


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


MOUNT_EXPORT_ROOTS = ("var/lib/nexolab", "host/dev")


def verify_export_mount_exclusion(path: Path) -> dict[str, Any]:
    """Prove docker export did not capture mounted runtime/device payloads."""
    unexpected: list[str] = []
    root_types: dict[str, str] = {}
    try:
        with tarfile.open(path, mode="r:*") as archive:
            for member in archive:
                normalized = member.name.lstrip("./").rstrip("/")
                if not normalized:
                    continue
                for root in MOUNT_EXPORT_ROOTS:
                    if normalized == root:
                        root_types[root] = "directory" if member.isdir() else member.type.decode(errors="replace") if isinstance(member.type, bytes) else str(member.type)
                    elif normalized.startswith(root + "/"):
                        unexpected.append(normalized)
    except (OSError, tarfile.TarError) as error:
        fail(f"rootfs export archive could not be audited: {error}")
    non_directories = sorted(root for root, kind in root_types.items() if kind != "directory")
    if non_directories:
        fail(f"rootfs export mounted path is not a directory placeholder: {non_directories}")
    if unexpected:
        sample = sorted(set(unexpected))[:10]
        fail(f"rootfs export unexpectedly contains mounted-path payloads: {sample}")
    return {
        "verified": True,
        "mounted_paths": ["/var/lib/nexolab", "/host/dev"],
        "nested_entry_count": 0,
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def parse_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def valid_stamp(value: str) -> bool:
    if not STAMP_PATTERN.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def restored_deployment_source(directory: Path) -> str | None:
    result_path = directory / "edge-sqlite-restore-result.json"
    if not result_path.exists():
        return None
    metadata_path = directory / "edge-sqlite-pre-cutover.json"
    if (
        result_path.is_symlink()
        or metadata_path.is_symlink()
        or not result_path.is_file()
        or not metadata_path.is_file()
    ):
        fail(f"recovery authority evidence is unsafe: {directory}")
    try:
        restore_result = json.loads(result_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"recovery authority evidence is unreadable: {directory}: {error}")

    matching_fields = (
        "sha256",
        "bytes",
        "registry_revision",
        "outbound_queue_count",
        "outbound_queue_high_water",
        "node_stream_sequences",
        "deployment_evidence_id",
        "deployed_source",
        "deployed_device_agent_image_id",
        "target_source",
    )
    valid_restore = (
        isinstance(restore_result, dict)
        and isinstance(metadata, dict)
        and restore_result.get("schema_version") == 1
        and restore_result.get("kind") == "nexolab-edge-sqlite-restore-result"
        and restore_result.get("status") == "restored"
        and metadata.get("schema_version") == 1
        and metadata.get("kind") == "nexolab-edge-sqlite-pre-cutover"
        and metadata.get("source_quick_check") == "ok"
        and metadata.get("snapshot_quick_check") == "ok"
        and restore_result.get("deployment_evidence_id") == directory.name
        and SHA_PATTERN.fullmatch(str(restore_result.get("deployed_source", "")))
        and SHA_PATTERN.fullmatch(str(restore_result.get("target_source", "")))
        and IMAGE_PATTERN.fullmatch(
            str(restore_result.get("deployed_device_agent_image_id", ""))
        )
        and all(restore_result.get(field) == metadata.get(field) for field in matching_fields)
    )
    if not valid_restore:
        fail(f"recovery authority evidence is inconsistent: {directory}")
    return str(restore_result["deployed_source"])


def authoritative_deployment(
    deployment_root: Path, expected_directory: Path, expected_source: str
) -> dict[str, Any]:
    if expected_directory.is_symlink() or not expected_directory.is_dir():
        fail("deployment evidence directory must be a real directory")
    if expected_directory.parent.resolve() != deployment_root.resolve():
        fail("deployment evidence must be an immediate runtime/deployments child")
    if not valid_stamp(expected_directory.name):
        fail("deployment evidence directory name is not a valid UTC deployment stamp")

    attempts: list[tuple[str, Path, bool, str | None, str | None, str | None]] = []
    legacy_markers = (
        "Starting central backend, MinIO and observability",
        "Starting real-hardware edge stack",
        "Activating verified frontend release",
        "RUNTIME MUTATION STARTED",
    )
    for directory in deployment_root.iterdir():
        if directory.is_symlink() or not directory.is_dir() or not valid_stamp(directory.name):
            continue
        summary_path = directory / "summary.txt"
        final_state_path = directory / "final-state.txt"
        summary = (
            summary_path.read_text(encoding="utf-8", errors="replace")
            if summary_path.is_file() and not summary_path.is_symlink()
            else ""
        )
        source: str | None = None
        runtime_mode: str | None = None
        deployed_at: str | None = None
        if final_state_path.is_file() and not final_state_path.is_symlink():
            final_state = parse_key_values(final_state_path)
            candidate = final_state.get("commit", "")
            if SHA_PATTERN.fullmatch(candidate) and "DEPLOYMENT PASSED" in summary:
                source = candidate
                runtime_mode = final_state.get("runtime_mode")
                deployed_at = final_state.get("deployed_at")
        recovered_source = restored_deployment_source(directory)
        if recovered_source is not None:
            source = recovered_source
            runtime_mode = EXPECTED_DEPLOYMENT_MODE
            deployed_at = None
        mutated = (directory / "runtime-mutation-started").is_file() or any(
            marker in summary for marker in legacy_markers
        )
        attempts.append(
            (directory.name, directory.resolve(), mutated, source, runtime_mode, deployed_at)
        )

    successful = [attempt for attempt in attempts if attempt[3]]
    if not successful:
        fail("no authoritative successful source deployment exists")
    success_stamp, success_directory, _mutated, source, runtime_mode, deployed_at = max(
        successful, key=lambda item: item[0]
    )
    if success_directory != expected_directory.resolve() or source != expected_source:
        fail("supplied deployment evidence is not the latest successful source authority")
    for stamp, directory, mutated, later_source, _runtime_mode, _deployed_at in attempts:
        if stamp > success_stamp and directory != expected_directory.resolve() and mutated and not later_source:
            fail(f"later deployment crossed the mutation boundary without recovery: {directory}")

    if runtime_mode != EXPECTED_DEPLOYMENT_MODE:
        fail("deployment evidence runtime mode is not lan")
    return {
        "evidence_id": expected_directory.name,
        "path": f"runtime/deployments/{expected_directory.name}",
        "source_commit": expected_source,
        "runtime_mode": runtime_mode,
        "deployed_at": deployed_at,
    }


def verify_git_authority(repo: Path, expected_source: str) -> None:
    if run(["git", "-C", str(repo), "cat-file", "-e", f"{expected_source}^{{commit}}"], check=False).returncode:
        fail("deployed source commit is unavailable in the repository")
    if run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", expected_source, "main"],
        check=False,
    ).returncode:
        fail("deployed source is not contained in local main history")


def inspect_container(container: str) -> dict[str, Any]:
    return {
        "id": docker_format_json(container, ".Id"),
        "image_id": docker_format_json(container, ".Image"),
        "name": docker_format_json(container, ".Name"),
        "created": docker_format_json(container, ".Created"),
        "state": {
            "status": docker_format_json(container, ".State.Status"),
            "running": docker_format_json(container, ".State.Running"),
            "paused": docker_format_json(container, ".State.Paused"),
            "restarting": docker_format_json(container, ".State.Restarting"),
            "dead": docker_format_json(container, ".State.Dead"),
            "health": docker_format_json(container, ".State.Health.Status"),
        },
        "config": {
            "user": docker_format_json(container, ".Config.User"),
            "working_dir": docker_format_json(container, ".Config.WorkingDir"),
            "entrypoint": docker_format_json(container, ".Config.Entrypoint"),
            "cmd": docker_format_json(container, ".Config.Cmd"),
            "exposed_ports": sorted(
                (docker_format_json(container, ".Config.ExposedPorts") or {}).keys()
            ),
            "healthcheck": docker_format_json(container, ".Config.Healthcheck"),
        },
        "mounts": docker_format_json(container, ".Mounts"),
        "size_root_fs": docker_format_json(container, ".SizeRootFs", size=True),
    }


def verify_container(
    container: dict[str, Any], expected_container: str | None, lost_image_id: str
) -> dict[str, Any]:
    container_id = container["id"]
    if not isinstance(container_id, str) or not CONTAINER_PATTERN.fullmatch(container_id):
        fail("running Device Agent container ID is invalid")
    if expected_container and not container_id.startswith(expected_container):
        fail("running Device Agent does not match the explicitly expected container")
    if container["image_id"] != lost_image_id:
        fail("running Device Agent image does not match the lost historical image authority")
    expected_state = {
        "status": "running",
        "running": True,
        "paused": False,
        "restarting": False,
        "dead": False,
        "health": "healthy",
    }
    if container["state"] != expected_state:
        fail(f"Device Agent is not in the required healthy running state: {container['state']}")
    if container["config"] != {key: SAFE_CONFIG[key] for key in container["config"]}:
        fail("Device Agent safe image configuration differs from the approved allowlist")

    safe_mounts = [
        {
            "type": mount.get("Type"),
            "name": mount.get("Name") or None,
            "source": mount.get("Source"),
            "destination": mount.get("Destination"),
            "read_write": bool(mount.get("RW")),
        }
        for mount in container["mounts"]
    ]
    safe_mounts.sort(key=lambda item: str(item["destination"]))
    expected_mounts = [
        {
            "type": "bind",
            "name": None,
            "source": "/dev",
            "destination": "/host/dev",
            "read_write": False,
        },
        {
            "type": "volume",
            "name": EXPECTED_EDGE_VOLUME,
            "source": f"/var/lib/docker/volumes/{EXPECTED_EDGE_VOLUME}/_data",
            "destination": "/var/lib/nexolab",
            "read_write": True,
        },
    ]
    if safe_mounts != expected_mounts:
        fail(f"Device Agent mount identity is unexpected: {safe_mounts}")
    rootfs_size = container["size_root_fs"]
    if not isinstance(rootfs_size, int) or rootfs_size <= 0:
        fail("Device Agent root filesystem size is unavailable")
    return {**container, "mounts": safe_mounts}


def matching_device_agent_container() -> str:
    result = run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=nexolab-edge",
            "--filter",
            "label=com.docker.compose.service=device-agent",
        ]
    )
    containers = [line for line in result.stdout.splitlines() if line]
    if len(containers) != 1:
        fail("rebaseline requires exactly one running known Device Agent container")
    return containers[0]


def verify_lost_image(lost_image_id: str) -> None:
    if not IMAGE_PATTERN.fullmatch(lost_image_id):
        fail("lost historical image ID must be an exact sha256 image ID")
    if run(["docker", "image", "inspect", lost_image_id], check=False).returncode == 0:
        fail("historical image is still addressable; explicit rebaseline is not applicable")


def verify_diff(container_id: str) -> list[str]:
    result = run(["docker", "diff", container_id])
    entries = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
    if entries != ALLOWED_DIFF:
        fail(f"Device Agent writable-layer drift is not allowlisted: {entries}")
    return entries


def read_runtime_health() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=5) as response:
            document = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        fail(f"Device Agent health endpoint is unavailable: {error}")
    acquisition = document.get("acquisition") or {}
    scheduler = acquisition.get("scheduler") or document.get("scheduler") or {}
    safe = {
        "status": document.get("status"),
        "node_id": document.get("node_id"),
        "device_mode": document.get("device_mode"),
        "mqtt_connected": document.get("mqtt_connected"),
        "queue_depth": document.get("queue_depth"),
        "cadence_policy_revision": acquisition.get("cadence_policy_revision"),
        "workers_healthy": scheduler.get("workers_healthy"),
    }
    if (
        safe["status"] != "ok"
        or safe["mqtt_connected"] is not True
        or safe["queue_depth"] != 0
        or safe["workers_healthy"] is not True
    ):
        fail(f"Device Agent runtime health is not ready for rebaseline: {safe}")
    return safe


def read_edge_sqlite(container_id: str) -> dict[str, Any]:
    result = run(
        ["docker", "exec", "-i", container_id, "/usr/bin/python3", "-"],
        input_text=EDGE_SQLITE_AUDIT,
    )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"edge SQLite audit returned invalid JSON: {error}")
    if document.get("quick_check") != "ok" or document.get("read_only") is not True:
        fail("edge SQLite read-only integrity audit did not pass")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document.get("sha256", ""))):
        fail("edge SQLite audit hash is invalid")
    return document


def copy_json_from_container(container_id: str, path: str) -> dict[str, Any]:
    result = run(["docker", "cp", f"{container_id}:{path}", "-"], capture_bytes=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r|") as archive:
            member = archive.next()
            if member is None or not member.isfile():
                fail("version authority copy did not contain one regular file")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail("version authority copy could not be read")
            document = json.load(extracted)
            if archive.next() is not None:
                fail("version authority copy contained unexpected extra entries")
    except (tarfile.TarError, json.JSONDecodeError) as error:
        fail(f"version authority record is unreadable: {error}")
    if not isinstance(document, dict):
        fail("version authority record is not an object")
    return document


def runtime_authority(expected_source: str, deployment_path: str) -> dict[str, Any]:
    telemetry = run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=nexolab-central",
            "--filter",
            "label=com.docker.compose.service=telemetry-service",
        ]
    ).stdout.splitlines()
    if len(telemetry) != 1:
        fail("exactly one running Telemetry Service is required for version authority")
    document = copy_json_from_container(
        telemetry[0], "/app/data/version-management/current.json"
    )
    safe = {
        "deployment_authority": document.get("deployment_authority"),
        "source_commit": document.get("source_commit"),
        "schema_head": document.get("schema_head"),
        "platform": document.get("platform"),
        "runtime_mode": document.get("runtime_mode"),
        "health": document.get("health"),
        "known_packaged_release": document.get("known_packaged_release"),
        "source_deployment_evidence": document.get("source_deployment_evidence"),
    }
    expected = {
        "deployment_authority": "controlled_source_deployment",
        "source_commit": expected_source,
        "schema_head": "20260820_0026",
        "platform": EXPECTED_PLATFORM,
        "runtime_mode": EXPECTED_DEPLOYMENT_MODE,
        "health": "ready",
        "known_packaged_release": False,
        "source_deployment_evidence": deployment_path,
    }
    if safe != expected:
        fail(f"controlled-source version authority does not match deployment evidence: {safe}")
    return safe


def postgresql_authority() -> dict[str, Any]:
    result = run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            "label=com.docker.compose.project=nexolab-central",
            "--filter",
            "label=com.docker.compose.service=postgres",
        ]
    )
    containers = [line for line in result.stdout.splitlines() if line]
    if len(containers) != 1:
        fail("exactly one running central PostgreSQL container is required")
    container_id = docker_format_json(containers[0], ".Id")
    health = docker_format_json(containers[0], ".State.Health.Status")
    image_id = docker_format_json(containers[0], ".Image")
    mounts = docker_format_json(containers[0], ".Mounts")
    volumes = sorted(
        (
            {
                "name": mount.get("Name"),
                "destination": mount.get("Destination"),
                "read_write": bool(mount.get("RW")),
            }
            for mount in mounts
            if mount.get("Type") == "volume"
        ),
        key=lambda item: str(item["destination"]),
    )
    if health != "healthy" or not volumes:
        fail("central PostgreSQL health or persistent-volume identity is unavailable")
    return {
        "container_id": container_id,
        "image_id": image_id,
        "health": health,
        "volumes": volumes,
        "mutation": "none",
    }


def import_changes(rebaseline_id: str, expected_source: str, container_id: str) -> list[str]:
    health = SAFE_CONFIG["healthcheck"]
    changes = [
        "ENV PYTHONDONTWRITEBYTECODE=1",
        "ENV PYTHONUNBUFFERED=1",
        "ENV PYTHONPATH=/app/site-packages",
        "WORKDIR /app",
        "USER nonroot",
        'ENTRYPOINT ["/usr/bin/python3.13"]',
        'CMD ["dual_bus_main.py"]',
        "EXPOSE 8081",
        (
            "HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 "
            f"CMD {json.dumps(health['Test'][1:], separators=(',', ':'))}"
        ),
        (
            "LABEL io.nexolab.recovery.kind=device-agent-container-rebaseline "
            f"io.nexolab.recovery.rebaseline-id={rebaseline_id} "
            f"org.opencontainers.image.revision={expected_source} "
            f"io.nexolab.recovery.source-container={container_id}"
        ),
    ]
    return changes


def inspect_imported_image(image: str) -> dict[str, Any]:
    document = docker_json(["image", "inspect", image])[0]
    config = document.get("Config") or {}
    safe = {
        "image_id": document.get("Id"),
        "os": document.get("Os"),
        "architecture": document.get("Architecture"),
        "user": config.get("User"),
        "working_dir": config.get("WorkingDir"),
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "exposed_ports": sorted((config.get("ExposedPorts") or {}).keys()),
        "healthcheck": config.get("Healthcheck"),
        "environment": config.get("Env") or [],
    }
    expected = {
        "image_id": safe["image_id"],
        "os": "linux",
        "architecture": "arm64",
        **SAFE_CONFIG,
    }
    if safe != expected:
        fail(f"imported recovery image config is not the safe allowlist: {safe}")
    if not IMAGE_PATTERN.fullmatch(str(safe["image_id"])):
        fail("imported recovery image ID is invalid")
    return safe


def validate_create(image_id: str, rebaseline_id: str) -> dict[str, Any]:
    name = f"nexolab-device-agent-rebaseline-validation-{rebaseline_id.lower()}"
    created = run(
        [
            "docker",
            "create",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            image_id,
        ]
    ).stdout.strip()
    try:
        if not CONTAINER_PATTERN.fullmatch(created):
            fail("validation docker create returned an invalid container ID")
        state = docker_format_json(created, ".State.Status")
        created_image = docker_format_json(created, ".Image")
        if state != "created" or created_image != image_id:
            fail("validation container did not structurally instantiate the recovery image")
        validation = {
            "container_id": created,
            "state": state,
            "image_id": created_image,
            "network": "none",
            "read_only_rootfs": True,
            "started": False,
            "removed": False,
        }
    finally:
        if created:
            removal = run(["docker", "container", "rm", created], check=False)
            if removal.returncode != 0:
                fail("validation container could not be removed")
    validation["removed"] = True
    return validation


def resolve_current_authority(args: argparse.Namespace) -> dict[str, str]:
    repo = args.repo.resolve()
    authority_root = (repo / "runtime/recovery-authority/device-agent").resolve()
    current = authority_root / "current.json"
    if current.is_symlink() or not current.is_file():
        fail("current Device Agent rebaseline authority is unavailable")
    try:
        document = json.loads(current.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"current Device Agent rebaseline authority is unreadable: {error}")
    if not isinstance(document, dict):
        fail("current Device Agent rebaseline authority is not an object")
    rebaseline_id = document.get("rebaseline_id")
    immutable = authority_root / f"{rebaseline_id}.json"
    evidence_value = document.get("evidence_path")
    if not isinstance(evidence_value, str):
        fail("rebaseline authority evidence path is missing")
    evidence = (repo / evidence_value).resolve()
    expected_evidence_root = (repo / "runtime/evidence").resolve()
    if expected_evidence_root not in evidence.parents:
        fail("rebaseline authority evidence escaped runtime/evidence")
    for path in (immutable, evidence):
        if path.is_symlink() or not path.is_file() or path.read_bytes() != current.read_bytes():
            fail("rebaseline authority copies are missing or inconsistent")

    source = document.get("source_container") or {}
    recovery = document.get("recovery_image") or {}
    deployment = document.get("deployment") or {}
    source_container_id = source.get("id")
    source_image_id = source.get("historical_image_id")
    recovery_image_id = recovery.get("image_id")
    recovery_tag = recovery.get("recovery_tag")
    expected_tag = (
        f"nexolab-device-agent:recovery-{str(recovery_image_id).removeprefix('sha256:')}"
    )
    valid = (
        document.get("schema_version") == SCHEMA_VERSION
        and document.get("kind") == "nexolab-device-agent-recovery-rebaseline"
        and document.get("status") == "established"
        and valid_stamp(str(rebaseline_id))
        and document.get("deployed_source") == args.expected_deployed_source
        and deployment.get("path")
        == f"runtime/deployments/{args.deployment_evidence.resolve().name}"
        and args.deployment_evidence.resolve()
        == (repo / str(deployment.get("path"))).resolve()
        and CONTAINER_PATTERN.fullmatch(str(source_container_id))
        and IMAGE_PATTERN.fullmatch(str(source_image_id))
        and source.get("historical_image_addressable") is False
        and IMAGE_PATTERN.fullmatch(str(recovery_image_id))
        and recovery_tag == expected_tag
        and recovery.get("runtime_environment_imported") is False
        and recovery.get("derived_from_running_container_filesystem") is True
        and document.get("safety", {}).get("production_container_restarted") is False
    )
    if not valid:
        fail("current Device Agent rebaseline authority is inconsistent")

    running = matching_device_agent_container()
    current_id = docker_format_json(running, ".Id")
    current_image = docker_format_json(running, ".Image")
    current_health = docker_format_json(running, ".State.Health.Status")
    current_running = docker_format_json(running, ".State.Running")
    if (
        current_id != source_container_id
        or current_image != source_image_id
        or current_health != "healthy"
        or current_running is not True
    ):
        fail("running Device Agent no longer matches rebaseline source authority")
    inspected_recovery = docker_json(
        ["image", "inspect", "--format", "{{json .Id}}", str(recovery_tag)]
    )
    if inspected_recovery != recovery_image_id:
        fail("rebaseline recovery tag is missing or resolves to a different image")
    return {
        "rebaseline_id": str(rebaseline_id),
        "source_container_id": str(source_container_id),
        "source_container_image_id": str(source_image_id),
        "recovery_image_id": str(recovery_image_id),
        "recovery_tag": str(recovery_tag),
    }


def establish(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        fail("repository root is invalid")
    if not SHA_PATTERN.fullmatch(args.expected_deployed_source):
        fail("expected deployed source must be a full lowercase commit SHA")
    verify_git_authority(repo, args.expected_deployed_source)
    deployment_root = (repo / "runtime/deployments").resolve()
    deployment_directory = args.deployment_evidence.resolve()
    deployment = authoritative_deployment(
        deployment_root, deployment_directory, args.expected_deployed_source
    )

    verify_lost_image(args.lost_image_id)
    selected = matching_device_agent_container()
    container = verify_container(
        inspect_container(selected), args.expected_container, args.lost_image_id
    )
    diff = verify_diff(container["id"])
    health_before = read_runtime_health()
    sqlite_evidence = read_edge_sqlite(container["id"])
    version = runtime_authority(args.expected_deployed_source, deployment["path"])
    postgres = postgresql_authority()

    evidence_root = args.evidence_root.resolve()
    expected_evidence_root = (repo / "runtime/evidence").resolve()
    if evidence_root != expected_evidence_root:
        fail("rebaseline evidence root must be repository runtime/evidence")
    authority_root = (repo / "runtime/recovery-authority/device-agent").resolve()
    rebaseline_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    immutable_record = authority_root / f"{rebaseline_id}.json"
    current_record = authority_root / "current.json"
    if immutable_record.exists():
        fail("rebaseline evidence ID already exists")
    if current_record.exists():
        fail("a current Device Agent rebaseline authority already exists; refusing replacement")

    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(evidence_root, 0o700)
    required_free = container["size_root_fs"] * 3 + 512 * 1024 * 1024
    free_bytes = shutil.disk_usage(evidence_root).free
    if free_bytes < required_free:
        fail(
            f"insufficient free space for export/import: free={free_bytes} required={required_free}"
        )
    if args.check_only:
        return {
            "preconditions_passed": True,
            "deployed_source": args.expected_deployed_source,
            "deployment": deployment,
            "source_container": {
                "id": container["id"],
                "historical_image_id": container["image_id"],
                "state": container["state"],
                "writable_layer_diff": diff,
                "mounts": container["mounts"],
            },
            "runtime_health": health_before,
            "edge_sqlite": sqlite_evidence,
            "controlled_source_authority": version,
            "postgresql_authority": postgres,
            "capacity": {"free_bytes": free_bytes, "required_bytes": required_free},
            "mutation": "none",
        }

    tar_path: Path | None = None
    validation: dict[str, Any]
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".issue-768-device-agent-rootfs-", suffix=".tar", dir=evidence_root
        )
        os.close(descriptor)
        tar_path = Path(temporary)
        os.chmod(tar_path, 0o600)
        run(["docker", "export", "--output", str(tar_path), container["id"]])
        export_bytes = tar_path.stat().st_size
        export_sha256 = file_sha256(tar_path)
        if export_bytes <= 0:
            fail("running-container root filesystem export is empty")
        mount_exclusion = verify_export_mount_exclusion(tar_path)

        rebaseline_tag = (
            "nexolab-device-agent:rebaseline-"
            f"{args.expected_deployed_source[:12]}-{rebaseline_id.lower()}"
        )
        command = [
            "docker",
            "import",
            "--platform",
            EXPECTED_PLATFORM,
            "--message",
            f"NEXOLAB Issue 768 sanitized recovery rebaseline {rebaseline_id}",
        ]
        for change in import_changes(
            rebaseline_id, args.expected_deployed_source, container["id"]
        ):
            command.extend(["--change", change])
        command.extend([str(tar_path), rebaseline_tag])
        imported_id = run(command).stdout.strip()
        imported = inspect_imported_image(rebaseline_tag)
        if imported_id != imported["image_id"]:
            fail("docker import result does not match inspected recovery image ID")
        recovery_tag = f"nexolab-device-agent:recovery-{imported_id.removeprefix('sha256:')}"
        run(["docker", "image", "tag", imported_id, recovery_tag])
        for tag in (rebaseline_tag, recovery_tag):
            resolved = docker_json(["image", "inspect", "--format", "{{json .Id}}", tag])
            if resolved != imported_id:
                fail(f"immutable recovery tag does not resolve to the imported image: {tag}")
        validation = validate_create(imported_id, rebaseline_id)
    finally:
        if tar_path is not None:
            tar_path.unlink(missing_ok=True)
            fsync_directory(evidence_root)

    container_after = verify_container(
        inspect_container(container["id"]), args.expected_container, args.lost_image_id
    )
    if container_after["id"] != container["id"] or container_after["created"] != container["created"]:
        fail("production Device Agent identity changed during rebaseline")
    if verify_diff(container["id"]) != diff:
        fail("production Device Agent writable-layer drift changed during rebaseline")
    health_after = read_runtime_health()

    created_at = datetime.now(UTC).isoformat()
    safe_config = {**SAFE_CONFIG, "safe_config_sha256": canonical_sha256(SAFE_CONFIG)}
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nexolab-device-agent-recovery-rebaseline",
        "status": "established",
        "rebaseline_id": rebaseline_id,
        "created_at": created_at,
        "repository": REPOSITORY,
        "deployed_source": args.expected_deployed_source,
        "deployment": deployment,
        "source_container": {
            "id": container["id"],
            "name": container["name"],
            "created": container["created"],
            "historical_image_id": container["image_id"],
            "historical_image_addressable": False,
            "state_before": container["state"],
            "state_after": container_after["state"],
            "writable_layer_diff": diff,
            "mounts": container["mounts"],
            "safe_config": safe_config,
        },
        "runtime_health_before": health_before,
        "runtime_health_after": health_after,
        "edge_sqlite": sqlite_evidence,
        "controlled_source_authority": version,
        "postgresql_authority": postgres,
        "rootfs_export": {
            "sha256": export_sha256,
            "bytes": export_bytes,
            "persisted": False,
            "mounted_volume_contents_included": False,
            "mount_exclusion": mount_exclusion,
            "runtime_environment_included": False,
        },
        "recovery_image": {
            "image_id": imported["image_id"],
            "recovery_tag": recovery_tag,
            "rebaseline_tag": rebaseline_tag,
            "platform": EXPECTED_PLATFORM,
            "safe_config": safe_config,
            "derived_from_running_container_filesystem": True,
            "fresh_source_rebuild": False,
            "runtime_environment_imported": False,
        },
        "structural_validation": validation,
        "safety": {
            "production_container_restarted": False,
            "production_container_stopped": False,
            "production_container_paused": False,
            "modbus_access": "none",
            "hardware_write": "none",
            "edge_sqlite_mutation": "none",
            "postgresql_mutation": "none",
            "named_volume_deletion": "none",
            "product_data_deletion": "none",
            "runtime_environment_values_recorded": False,
            "embraco_activation": "none",
        },
    }
    immutable_evidence = evidence_root / f"issue-768-device-agent-rebaseline-{rebaseline_id}"
    immutable_evidence.mkdir(mode=0o700)
    atomic_json(immutable_evidence / "rebaseline.json", document)
    document["evidence_path"] = str(
        (immutable_evidence / "rebaseline.json").relative_to(repo)
    )
    atomic_json(immutable_evidence / "rebaseline.json", document)
    atomic_json(immutable_record, document)
    atomic_json(current_record, document)
    if immutable_record.read_bytes() != current_record.read_bytes():
        fail("current rebaseline pointer does not exactly match immutable authority evidence")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--expected-deployed-source", required=True)
    parser.add_argument("--lost-image-id")
    parser.add_argument("--expected-container")
    parser.add_argument(
        "--resolve-current",
        action="store_true",
        help="validate and print the established current authority without mutation",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize the export/import rebaseline operation",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="run every read-only precondition without exporting or importing",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "runtime/evidence",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    lock_path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "nexolab-device-agent-rebaseline.lock"
    try:
        with lock_path.open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("another Device Agent rebaseline is already running")
            if args.resolve_current:
                if args.execute or args.check_only or args.lost_image_id or args.expected_container:
                    fail("--resolve-current cannot be combined with execution-only arguments")
                resolved = resolve_current_authority(args)
                for key, value in resolved.items():
                    print(f"{key}={value}")
                return 0
            if args.execute and args.check_only:
                fail("choose exactly one of --check-only or --execute")
            if not args.execute and not args.check_only:
                fail("rebaseline requires the explicit --execute acknowledgement")
            if not args.lost_image_id:
                fail("rebaseline requires --lost-image-id")
            document = establish(args)
    except RebaselineError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.check_only:
        print("RECOVERY REBASELINE PRECONDITIONS PASSED")
        print(f"deployed_source={document['deployed_source']}")
        print(f"source_container_id={document['source_container']['id']}")
        print(f"historical_image_id={document['source_container']['historical_image_id']}")
        print(f"edge_sqlite_quick_check={document['edge_sqlite']['quick_check']}")
        print(f"edge_sqlite_registry_revision={document['edge_sqlite']['registry_revision']}")
        print(f"edge_sqlite_queue_depth={document['edge_sqlite']['outbound_queue_count']}")
        return 0
    print("RECOVERY REBASELINE ESTABLISHED")
    print(f"rebaseline_id={document['rebaseline_id']}")
    print(f"deployed_source={document['deployed_source']}")
    print(f"source_container_id={document['source_container']['id']}")
    print(f"historical_image_id={document['source_container']['historical_image_id']}")
    print(f"recovery_image_id={document['recovery_image']['image_id']}")
    print(f"recovery_tag={document['recovery_image']['recovery_tag']}")
    print(f"evidence_path={document['evidence_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
