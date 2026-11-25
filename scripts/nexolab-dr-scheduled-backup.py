#!/usr/bin/env python3
"""#1630 DR-A: scheduled, encrypted, complete NEXOLAB backup of all eight v2 stores.

Safety contract (enforced in code, covered by tests):
* never stops, restarts, pauses, kills or recreates containers; the only Docker
  verb ever executed is ``docker exec`` with an allowlisted read-only command;
* never writes plaintext: every byte goes through nexolab-dr-stream-v1
  (AES-256-GCM STREAM) straight into ``<output_dir>/.<name>.partial``;
* fail-closed capacity: refuses to start unless free space on the output file
  system stays >= the protected reserve (>= 20 GiB) after the configured
  maximum backup size, and aborts mid-run if either limit would be crossed;
* one run at a time (``flock``); an overlapping start exits 75 and is reported;
* never deletes anything except the exact partial file it created itself;
* writes a sanitized receipt (hashes/sizes only, no secrets) and a Prometheus
  textfile for the local Alertmanager. A receipt is NOT restore evidence:
  recoverability is proven only by the isolated restore of #1632.

Exit codes: 0 success, 1 capture/verification failure, 75 overlap, 78 blocked
by configuration or capacity.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable

GiB = 1024**3
MiB = 1024**2
MIN_RESERVE_BYTES = 20 * GiB
EXIT_OK, EXIT_FAILED, EXIT_OVERLAP, EXIT_BLOCKED = 0, 1, 75, 78

V2_STORES = (
    "postgresql",
    "object-storage",
    "mqtt-dynamic-security",
    "edge-sqlite-outbox",
    "local-auth-private-key",
    "local-auth-public-key",
    "central-ingestion-spool",
    "edge-mqtt-persistence",
)
REBUILDABLE = {"central-ingestion-spool", "edge-mqtt-persistence"}
ALLOWED_METHODS = {
    "postgresql": {"docker_exec_stream"},
    "object-storage": {"directory_snapshot"},
    "mqtt-dynamic-security": {"directory_snapshot"},
    "edge-mqtt-persistence": {"directory_snapshot"},
    "edge-sqlite-outbox": {"sqlite_online"},
    "central-ingestion-spool": {"sqlite_online"},
    "local-auth-private-key": {"docker_exec_stream", "file_snapshot"},
    "local-auth-public-key": {"docker_exec_stream", "file_snapshot"},
}
CONSISTENCY = {
    "docker_exec_stream": "online_logical_or_atomic_read",
    "sqlite_online": "sqlite_online_backup_api",
    "directory_snapshot": "verified_unchanged_during_capture",
    "file_snapshot": "verified_unchanged_during_capture",
}
# Capture order: small, quickly verifiable stores first; the long pg_dump last.
# Capture order (review P1-3): object storage is captured AFTER the PostgreSQL snapshot.
# The application writes the object first and commits the referencing `equipment_images`
# row afterwards, and never deletes an object once its row is committed
# (services/telemetry-service/app/refrigeration/api.py). Capturing objects after the pg_dump
# snapshot point therefore contains every object the dump references; objects present before
# the snapshot that disappear before the object capture fail the run (dangling-reference guard).
CAPTURE_SEQUENCE = (
    "local-auth-private-key", "local-auth-public-key", "mqtt-dynamic-security",
    "edge-mqtt-persistence", "edge-sqlite-outbox", "central-ingestion-spool",
    "postgresql", "object-storage",
)
ORDER = {name: index for index, name in enumerate(CAPTURE_SEQUENCE)}
CONTAINER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
FORBIDDEN_DOCKER_TOKENS = {"stop", "restart", "kill", "rm", "pause", "down", "up", "create", "run",
                           "update", "--privileged", "-i", "--interactive", "-t", "--tty", "-e", "--env"}
# Review P2-4: the online backup into ":memory:" plus serialize() holds ~2x the database
# (measured RSS growth 2.25x at 190 MiB, 2.66x at 34 MiB incl. fixed overhead). 192 MiB keeps
# the worst case (~0.5 GiB) well under MemoryMax=768M; larger databases are refused before copying.
SQLITE_MAX_DEFAULT = 192 * MiB


class Blocked(Exception):
    """Configuration or capacity refuses to start (exit 78)."""


class CaptureFailed(Exception):
    """A store could not be captured consistently (exit 1)."""


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


def _load_volume_archive_module():
    """Single source of the volume tar contract (root metadata + user.* xattr records)."""
    path = Path(__file__).with_name("nexolab-volume-archive.py")
    spec = importlib.util.spec_from_file_location("nexolab_volume_archive", path)
    if spec is None or spec.loader is None:
        raise Blocked("nexolab-volume-archive.py is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vat = _load_volume_archive_module()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ----------------------------------------------------------------- configuration


@dataclass(frozen=True)
class StoreConfig:
    id: str
    disposition: str
    method: str | None
    params: dict[str, Any]
    max_bytes: int
    entry_path: str
    content_format: str


@dataclass(frozen=True)
class Config:
    repository: str
    commit: str
    output_dir: Path
    key_file: Path
    lock_file: Path
    metrics_file: Path | None
    reserve_free_bytes: int
    max_backup_bytes: int
    verify_after_capture: bool
    stores: tuple[StoreConfig, ...]


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise Blocked(f"{label} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        raise Blocked(f"{label} must be absolute")
    return path


PG_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
# Strict allowlist: every pg_dump token must match exactly one of these. Anything else
# (-f/--file, -F<other>, --format=, -h/--host, -j, filters, --clean/-c/-C ...) is refused, so
# the dump can only be a custom-format archive written to stdout of the local server.
PG_FLAG_TOKENS = {"-Fc", "-w", "--no-password"}
PG_VALUE_OPTIONS = {
    "-U": lambda value: bool(PG_IDENTIFIER.fullmatch(value)),
    "-d": lambda value: bool(PG_IDENTIFIER.fullmatch(value)),
    "-Z": lambda value: value.isdigit() and 0 <= int(value) <= 9 and value == str(int(value)),
}


def validate_pg_dump_command(command: list[str]) -> None:
    if not command or command[0] != "pg_dump":
        raise Blocked("postgresql: command must start with pg_dump")
    seen: set[str] = set()
    index = 1
    while index < len(command):
        token = command[index]
        if token in seen:
            raise Blocked(f"postgresql: duplicate pg_dump option {token}")
        if token in PG_FLAG_TOKENS:
            seen.add(token)
            index += 1
        elif token in PG_VALUE_OPTIONS:
            if index + 1 >= len(command) or not PG_VALUE_OPTIONS[token](command[index + 1]):
                raise Blocked(f"postgresql: invalid value for pg_dump {token}")
            seen.add(token)
            index += 2
        else:
            raise Blocked(f"postgresql: pg_dump option {token!r} is not allowed (stdout-only custom dump)")
    missing = {"-Fc", "-U", "-d"} - seen
    if missing:
        raise Blocked(f"postgresql: pg_dump requires {', '.join(sorted(missing))}")


def validate_docker_argv(argv: Any, store_id: str) -> list[str]:
    if not isinstance(argv, list) or not all(isinstance(item, str) and item for item in argv):
        raise Blocked(f"{store_id}: argv must be a list of non-empty strings")
    if len(argv) < 4 or Path(argv[0]).name != "docker" or argv[1] != "exec":
        raise Blocked(f"{store_id}: only 'docker exec <container> <command>' is allowed")
    if not CONTAINER.fullmatch(argv[2]):
        raise Blocked(f"{store_id}: container name is invalid (no docker exec options allowed)")
    if any(token in FORBIDDEN_DOCKER_TOKENS for token in argv[1:3]) or any(
        token in {"--privileged", "-i", "--interactive", "-t", "--tty"} for token in argv
    ):
        raise Blocked(f"{store_id}: forbidden docker option")
    command = argv[3:]
    if command[:3] == ["nice", "-n", "19"]:
        command = command[3:]
    if store_id == "postgresql":
        validate_pg_dump_command(command)
    else:
        if len(command) != 2 or command[0] != "cat" or not command[1].startswith("/"):
            raise Blocked(f"{store_id}: command must be 'cat <absolute path>'")
    return list(argv)


def load_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Blocked("backup configuration is unreadable or invalid JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or raw.get("kind") != "nexolab-dr-scheduled-backup":
        raise Blocked("backup configuration schema is unsupported")
    commit = raw.get("source_commit")
    if commit is None and "source_commit_file" in raw:
        try:
            commit = _absolute(raw["source_commit_file"], "source_commit_file").read_text(encoding="ascii").strip()
        except OSError as exc:
            raise Blocked("source_commit_file is unreadable") from exc
    if not isinstance(commit, str) or not drs.COMMIT.fullmatch(commit):
        raise Blocked("source commit must be a full lowercase Git SHA")
    repository = raw.get("repository")
    if not isinstance(repository, str) or not drs.REPOSITORY.fullmatch(repository):
        raise Blocked("repository must use owner/name format")
    reserve = raw.get("reserve_free_bytes", MIN_RESERVE_BYTES)
    maximum = raw.get("max_backup_bytes")
    if type(reserve) is not int or reserve < MIN_RESERVE_BYTES:
        raise Blocked("reserve_free_bytes must be an integer >= 20 GiB")
    if type(maximum) is not int or not 1 * MiB <= maximum <= 512 * GiB:
        raise Blocked("max_backup_bytes must be an integer between 1 MiB and 512 GiB")

    # Review P1-2: a run may only report success after full cryptographic verification.
    if raw.get("verify_after_capture", True) is not True:
        raise Blocked("verify_after_capture cannot be disabled: every bundle must be verified before it is kept")

    stores_raw = raw.get("stores")
    if not isinstance(stores_raw, list):
        raise Blocked("stores must be a list")
    stores: list[StoreConfig] = []
    for item in stores_raw:
        if not isinstance(item, dict):
            raise Blocked("store entries must be objects")
        store_id = item.get("id")
        if store_id not in V2_STORES:
            raise Blocked(f"unknown store: {store_id!r}")
        disposition = item.get("disposition", "capture")
        if disposition == "rebuildable_excluded":
            if store_id not in REBUILDABLE:
                raise Blocked(f"{store_id}: only rebuildable stores may be excluded")
            reason = item.get("reason")
            if not isinstance(reason, str) or len(reason.strip()) < 10:
                raise Blocked(f"{store_id}: exclusion requires an explicit reason")
            stores.append(StoreConfig(store_id, disposition, None, {"reason": reason}, 0, "", ""))
            continue
        if disposition != "capture":
            raise Blocked(f"{store_id}: disposition must be capture or rebuildable_excluded")
        method = item.get("method")
        if method not in ALLOWED_METHODS[store_id]:
            raise Blocked(f"{store_id}: method {method!r} is not allowed")
        max_bytes = item.get("max_bytes")
        if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > maximum:
            raise Blocked(f"{store_id}: max_bytes must be positive and <= max_backup_bytes")
        params: dict[str, Any] = {}
        if method == "docker_exec_stream":
            params["argv"] = validate_docker_argv(item.get("argv"), store_id)
        elif method in {"sqlite_online", "directory_snapshot", "file_snapshot"}:
            params["path"] = str(_absolute(item.get("path"), f"{store_id}.path"))
        entry = drs.safe_entry_path(item.get("entry_path", ""))
        content_format = item.get("format")
        if not isinstance(content_format, str) or not content_format:
            raise Blocked(f"{store_id}: format is required")
        stores.append(StoreConfig(store_id, disposition, method, params, max_bytes, entry, content_format))

    ids = [store.id for store in stores]
    if sorted(ids) != sorted(V2_STORES) or len(set(ids)) != len(ids):
        raise Blocked("configuration must classify each of the eight v2 stores exactly once")
    if sum(store.max_bytes for store in stores) > maximum:
        raise Blocked("sum of per-store caps exceeds max_backup_bytes")
    metrics = raw.get("metrics_file")
    return Config(
        repository=repository,
        commit=commit,
        output_dir=_absolute(raw.get("output_dir"), "output_dir"),
        key_file=_absolute(raw.get("key_file"), "key_file"),
        lock_file=_absolute(raw.get("lock_file"), "lock_file"),
        metrics_file=_absolute(metrics, "metrics_file") if metrics is not None else None,
        reserve_free_bytes=reserve,
        max_backup_bytes=maximum,
        verify_after_capture=True,
        stores=tuple(sorted(stores, key=lambda store: ORDER[store.id])),
    )


# ----------------------------------------------------------------- capacity / lock


def free_bytes(path: Path) -> int:
    """Free bytes of the file system that holds ``path`` (nearest existing ancestor)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def preflight_capacity(config: Config, free: Callable[[Path], int] | None = None) -> int:
    available = (free or free_bytes)(config.output_dir)
    if available - config.max_backup_bytes < config.reserve_free_bytes:
        raise Blocked(
            f"capacity: free {available} - max backup {config.max_backup_bytes} "
            f"< protected reserve {config.reserve_free_bytes}"
        )
    return available


@contextlib.contextmanager
def single_run_lock(path: Path):
    import fcntl  # POSIX only; the service runs on Linux

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OverlapError("another backup run holds the lock") from None
        yield
    finally:
        os.close(descriptor)


class OverlapError(Exception):
    pass


# ----------------------------------------------------------------- store capture


def _xattr_state(path: Path, label: str) -> str:
    """Digest of the user.* xattrs (read-only). Part of the signature: VersityGW rewrites
    metadata (ETag/Content-Type) via setxattr, which changes neither size nor mtime."""
    try:
        return vat.xattr_digest(vat.read_user_xattrs(path, label))
    except vat.VolumeArchiveFailure as exc:
        raise CaptureFailed(str(exc)) from exc


def _signature(root: Path) -> tuple:
    """Metadata signature compared before/after a snapshot: size, mtime, inode, mode and the
    digest of the user.* extended attributes of every entry (and of the root directory)."""
    if root.is_file():
        st = root.stat()
        return (("", st.st_size, st.st_mtime_ns, st.st_ino, st.st_mode, _xattr_state(root, "file")),)
    entries = [("", _xattr_state(root, "root"))]
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        relative = path.relative_to(root).as_posix()
        entries.append((relative, st.st_size, st.st_mtime_ns, st.st_ino, st.st_mode, _xattr_state(path, relative)))
    return tuple(entries)


def object_paths(root: Path) -> set[str]:
    """Relative paths of regular files in an object tree (metadata only, no content read)."""
    if not root.is_dir():
        raise CaptureFailed(f"object tree is missing: {root}")
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def capture_directory(root: Path, sink: Any) -> dict[str, Any]:
    """Streams a deterministic tar compatible with nexolab-volume-archive.py extract.

    The user.* extended attributes of every entry are captured as SCHILY.xattr.* PAX records
    (VersityGW object metadata: ETag, Content-Type, checksums, bucket ACL/ownership) and the
    archive declares NEXOLAB.volume.xattrs=user-v1. Reads are strictly read-only. Returns the
    attribute summary (counts only; names and values never leave the encrypted stream).
    """
    try:
        root_meta = root.lstat()
    except OSError as exc:
        raise CaptureFailed(f"source directory is missing: {root}") from exc
    if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
        raise CaptureFailed("source must be a non-symlink directory")
    before = _signature(root)
    budget = vat.XattrBudget()
    try:
        root_xattrs = vat.read_user_xattrs(root, "root")
        budget.add(root_xattrs, "root")
        pax = vat.global_pax_headers(root_meta, root_xattrs)
    except vat.VolumeArchiveFailure as exc:
        raise CaptureFailed(str(exc)) from exc
    with tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT, pax_headers=pax,
                      encoding=vat.TAR_ENCODING, errors=vat.TAR_ERRORS) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            meta = path.lstat()
            if stat.S_ISLNK(meta.st_mode):
                raise CaptureFailed(f"symlink in source is not allowed: {relative}")
            info = tarfile.TarInfo(relative)
            info.mode, info.uid, info.gid = stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid
            info.uname = info.gname = ""
            info.mtime = 0
            try:
                xattrs = vat.read_user_xattrs(path, relative)
                budget.add(xattrs, relative)
                info.pax_headers = vat.xattr_pax_headers(xattrs)
            except vat.VolumeArchiveFailure as exc:
                raise CaptureFailed(str(exc)) from exc
            if stat.S_ISDIR(meta.st_mode):
                info.type, info.size = tarfile.DIRTYPE, 0
                archive.addfile(info)
            elif stat.S_ISREG(meta.st_mode):
                info.type, info.size = tarfile.REGTYPE, meta.st_size
                with path.open("rb") as content:
                    archive.addfile(info, content)
            else:
                raise CaptureFailed(f"special file in source is not allowed: {relative}")
    if _signature(root) != before:
        raise CaptureFailed("source changed during capture (not a consistent snapshot); run will retry later")
    return budget.summary()


def capture_file(path: Path, sink: Any) -> None:
    try:
        meta = path.lstat()
    except OSError as exc:
        raise CaptureFailed(f"source file is missing: {path}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise CaptureFailed("source must be a regular non-symlink file")
    before = _signature(path)
    with path.open("rb") as source:
        while chunk := source.read(256 * 1024):
            sink.write(chunk)
    if _signature(path) != before:
        raise CaptureFailed("source file changed during capture")


def capture_sqlite(path: Path, sink: Any, max_bytes: int) -> None:
    if not path.is_file():
        raise CaptureFailed(f"sqlite database is missing: {path}")
    try:
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise CaptureFailed("sqlite database cannot be opened read-only") from exc
    try:
        page_count = source.execute("PRAGMA page_count").fetchone()[0]
        page_size = source.execute("PRAGMA page_size").fetchone()[0]
        if page_count * page_size > min(max_bytes, SQLITE_MAX_DEFAULT):
            raise CaptureFailed("sqlite database exceeds the in-memory capture cap")
        memory = sqlite3.connect(":memory:")
        try:
            source.backup(memory, pages=256, sleep=0.05)
            if memory.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CaptureFailed("sqlite online backup failed integrity_check")
            image = memory.serialize()
        finally:
            memory.close()  # free the page cache before streaming: peak is ~2x only during serialize()
    except sqlite3.Error as exc:
        raise CaptureFailed("sqlite online backup failed") from exc
    finally:
        source.close()
    if len(image) > min(max_bytes, SQLITE_MAX_DEFAULT):  # the database may have grown during backup
        raise CaptureFailed("sqlite database exceeds the in-memory capture cap")
    sink.write(image)
    del image


def capture_docker_exec(argv: list[str], sink: Any) -> None:
    stderr_tail = bytearray()

    def drain(stream: BinaryIO) -> None:
        for line in iter(lambda: stream.read(4096), b""):
            stderr_tail.extend(line)
            del stderr_tail[:-4096]

    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise CaptureFailed("cannot start docker exec") from exc
    reader = threading.Thread(target=drain, args=(process.stderr,), daemon=True)
    reader.start()
    try:
        assert process.stdout is not None
        while chunk := process.stdout.read(256 * 1024):
            sink.write(chunk)
    except BaseException:
        process.kill()
        process.wait()
        raise
    code = process.wait()
    reader.join(timeout=5)
    if code != 0:
        message = stderr_tail.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no diagnostics"]
        raise CaptureFailed(f"docker exec exited {code}: {message[0][:200]}")


def capture_store(store: StoreConfig, sink: Any) -> dict[str, Any] | None:
    """Captures one store; directory snapshots return their xattr summary (counts only)."""
    if store.method == "docker_exec_stream":
        capture_docker_exec(store.params["argv"], sink)
    elif store.method == "directory_snapshot":
        return capture_directory(Path(store.params["path"]), sink)
    elif store.method == "file_snapshot":
        capture_file(Path(store.params["path"]), sink)
    elif store.method == "sqlite_online":
        capture_sqlite(Path(store.params["path"]), sink, store.max_bytes)
    else:  # pragma: no cover - rejected by load_config
        raise CaptureFailed("unsupported method")
    return None


# ----------------------------------------------------------------- run


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_metrics(path: Path | None, values: dict[str, float]) -> None:
    if path is None:
        return
    lines = []
    for name, value in sorted(values.items()):
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value:.0f}" if float(value).is_integer() else f"{name} {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="ascii")
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def _state_path(config: Config) -> Path:
    return config.output_dir / "dr-backup-state.json"


def _last_success(config: Config) -> float:
    try:
        return float(json.loads(_state_path(config).read_text(encoding="utf-8")).get("last_success_unix", 0))
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return 0.0


def run_backup(config: Config, *, free: Callable[[Path], int] | None = None,
               clock: Callable[[], float] = time.time,
               capture: Callable[[StoreConfig, Any], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    free = free or free_bytes
    capture = capture or capture_store
    started = clock()
    created_at = utc_now()
    key = drs.load_key(config.key_file)
    config.output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    free_before = preflight_capacity(config, free)
    stamp = datetime.fromtimestamp(started, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"nexolab-dr-{stamp}-{secrets.token_hex(3)}.nxs"
    final_path = config.output_dir / name
    partial_path = config.output_dir / f".{name}.partial"
    if final_path.exists():
        raise Blocked("a bundle with this timestamp already exists")

    check_every = 16 * MiB
    next_check = [check_every]

    def require_reserve(moment: str) -> None:
        if free(config.output_dir) < config.reserve_free_bytes:
            raise CaptureFailed(f"free space fell below the protected reserve {moment}")

    def guard(written: int) -> None:
        # Review P2-6: the bundle cap is exact (ciphertext bytes on disk), no tolerance.
        if written > config.max_backup_bytes:
            raise CaptureFailed("bundle exceeds max_backup_bytes")
        if written >= next_check[0]:
            next_check[0] += check_every
            require_reserve("during capture")

    object_store = next((s for s in config.stores if s.id == "object-storage" and s.disposition == "capture"), None)
    objects_at_db_snapshot: set[str] | None = None

    header = drs.build_header(repository=config.repository, commit=config.commit, created_at=created_at,
                              key=key, chunk_size=drs.DEFAULT_CHUNK_SIZE, nonce_prefix=drs.new_nonce_prefix())
    store_results: list[dict[str, Any]] = []
    descriptor = os.open(partial_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            writer = drs.EncryptedWriter(output, key, header, on_write=guard)
            builder = drs.StreamBuilder(writer)
            for store in config.stores:
                if store.disposition == "rebuildable_excluded":
                    store_results.append({"id": store.id, "disposition": store.disposition,
                                          "reason": store.params["reason"]})
                    continue
                store_started = clock()
                if store.id == "postgresql" and object_store is not None:
                    # Taken before pg_dump starts, i.e. before its MVCC snapshot point.
                    objects_at_db_snapshot = object_paths(Path(object_store.params["path"]))
                sink = builder.begin_entry(path=store.entry_path, store=store.id,
                                           content_format=store.content_format, max_bytes=store.max_bytes)
                try:
                    captured = capture(store, sink)
                except drs.StreamFailure as exc:
                    raise CaptureFailed(f"{store.id}: {exc}") from exc
                except CaptureFailed as exc:
                    raise CaptureFailed(f"{store.id}: {exc}") from exc
                if store is object_store and objects_at_db_snapshot is not None:
                    vanished = objects_at_db_snapshot - object_paths(Path(store.params["path"]))
                    if vanished:
                        raise CaptureFailed(
                            f"object-storage: {len(vanished)} object(s) deleted after the database snapshot; "
                            "the dump may reference missing objects"
                        )
                entry = sink.close()
                result = {
                    "id": store.id, "disposition": "capture", "method": store.method,
                    "consistency": CONSISTENCY[store.method], "entry_path": entry.path,
                    "format": entry.content_format, "size": entry.size, "sha256": entry.sha256,
                    "duration_seconds": round(clock() - store_started, 3),
                }
                if store.method == "directory_snapshot" and isinstance(captured, dict):
                    # Explicit, additive manifest/receipt field (#1630 object-metadata fix): the tar
                    # carries user.* xattrs as SCHILY.xattr.* records (counts only, never values).
                    result["xattrs"] = captured
                store_results.append(result)
            builder.finish({"schema_version": 1, "kind": "nexolab-dr-stream-manifest", "issue": 1630,
                            "created_at": created_at, "commit": config.commit,
                            "stores": [{k: v for k, v in result.items() if k != "duration_seconds"}
                                       for result in store_results]})
            bundle_sha256 = writer.close()
            output.flush()
            os.fsync(output.fileno())
        # Review P2-5/P2-6: re-check the reserve and authenticate the complete partial file
        # BEFORE it becomes a final-looking .nxs; on any failure the partial is removed.
        require_reserve("before finalization")
        drs.verify_file(partial_path, key)
        os.replace(partial_path, final_path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            partial_path.unlink()  # only the exact partial file created above
        raise

    verified = True
    completed = clock()
    receipt = {
        "schema_version": 1,
        "kind": "nexolab-dr-backup-receipt",
        "issue": 1630,
        "status": "CAPTURED_RESTORE_UNVERIFIED",
        "created_at": created_at,
        "completed_at": utc_now(),
        "duration_seconds": round(completed - started, 3),
        "repository": config.repository,
        "commit": config.commit,
        "format": drs.FORMAT,
        "key_fingerprint": drs.key_fingerprint(key),
        "bundle": {"file": final_path.name, "size": final_path.stat().st_size, "sha256": bundle_sha256},
        "self_verified_after_capture": verified,
        "capacity": {"free_before": free_before, "free_after": free(config.output_dir),
                     "reserve": config.reserve_free_bytes, "max_backup_bytes": config.max_backup_bytes},
        "stores": store_results,
        "cross_store_consistency": {
            "postgresql_object_storage": {
                "status": "ORDERED_NO_DELETIONS_RESTORE_REFERENCE_CHECK_UNVERIFIED",
                "method": "object storage captured after the pg_dump snapshot; no object present before "
                          "the snapshot was deleted before the object capture",
                "basis": "application writes the object before committing the referencing row and never "
                         "deletes committed objects (refrigeration/api.py)",
                "residual": "a future code path that deletes committed objects within the dump window "
                            "would not be fully covered; equipment_images.storage_key -> object/checksum "
                            "must be verified on an isolated restore",
                "site_acceptance": "BLOCKED_UNTIL_1632_REFERENCE_CHECK",
            },
        },
        "isolated_restore_verified": False,
        "off_device_copy_verified": False,
    }
    _write_private_json(config.output_dir / f"{final_path.stem}.receipt.json", receipt)
    _write_private_json(_state_path(config), {"last_success_unix": completed, "last_bundle": final_path.name})
    return receipt


def execute(config_path: Path, *, plan_only: bool = False) -> int:
    started = time.time()
    config: Config | None = None
    metrics: dict[str, float] = {"nexolab_dr_backup_last_run_timestamp_seconds": started}
    try:
        config = load_config(config_path)
        if plan_only:
            available = preflight_capacity(config)
            print(json.dumps({"status": "PLAN_OK", "free_bytes": available,
                              "stores": [{"id": s.id, "disposition": s.disposition, "method": s.method,
                                          "max_bytes": s.max_bytes} for s in config.stores],
                              "note": "no data read, nothing written"}, sort_keys=True))
            return EXIT_OK
        with single_run_lock(config.lock_file):
            receipt = run_backup(config)
        metrics.update({
            "nexolab_dr_backup_last_run_ok": 1,
            "nexolab_dr_backup_last_success_timestamp_seconds": time.time(),
            "nexolab_dr_backup_last_bundle_bytes": receipt["bundle"]["size"],
            "nexolab_dr_backup_last_duration_seconds": receipt["duration_seconds"],
            "nexolab_dr_backup_stores_captured": sum(1 for s in receipt["stores"] if s["disposition"] == "capture"),
            "nexolab_dr_backup_free_bytes_after": receipt["capacity"]["free_after"],
        })
        print(json.dumps({"status": receipt["status"], "bundle": receipt["bundle"]}, sort_keys=True))
        code = EXIT_OK
    except OverlapError as exc:
        metrics["nexolab_dr_backup_overlap_skipped"] = 1
        print(json.dumps({"status": "SKIPPED_OVERLAP", "reason": str(exc)}), file=sys.stderr)
        code = EXIT_OVERLAP
    except Blocked as exc:
        metrics["nexolab_dr_backup_last_run_ok"] = 0
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        code = EXIT_BLOCKED
    except (CaptureFailed, drs.StreamFailure, OSError) as exc:
        metrics["nexolab_dr_backup_last_run_ok"] = 0
        print(json.dumps({"status": "FAILED", "reason": str(exc)[:300]}), file=sys.stderr)
        code = EXIT_FAILED
    if config is not None and not plan_only:
        metrics.setdefault("nexolab_dr_backup_last_success_timestamp_seconds", _last_success(config))
        with contextlib.suppress(OSError):
            write_metrics(config.metrics_file, metrics)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", action="store_true",
                        help="validate configuration and capacity only; reads no data, writes nothing")
    args = parser.parse_args(argv)
    return execute(args.config, plan_only=args.plan)


if __name__ == "__main__":
    raise SystemExit(main())
