#!/usr/bin/env python3
"""Guarded release of the protected HTTPS frontend (Funnel :443 -> OAuth -> 127.0.0.1:3105).

OWNER-RUN with sudo. The agent prepares and verifies the artifact; it never runs this tool.

    sudo python3 -I nexolab-https-frontend-release.py plan     --artifact ZIP --expect-zip-sha256 HEX \\
        --expect-source SHA --expect-build ID
    sudo python3 -I nexolab-https-frontend-release.py prepare  (same arguments)
    sudo python3 -I nexolab-https-frontend-release.py execute  (same arguments) \\
        --expect-current-source SHA --expect-current-build ID
    sudo python3 -I nexolab-https-frontend-release.py rollback --expect-current-source SHA --expect-current-build ID
    sudo python3 -I nexolab-https-frontend-release.py recover

plan      read-only: verifies the artifact and prints what prepare/execute would change.
prepare   verifies the ZIP SHA-256, its internal checksums and the HTTPS contract, extracts the
          runtime into a NEW release directory (never overwriting one), verifies every runtime
          file hash, writes the runtime identity, keeps >= 20 GiB free, and proves the release in an
          isolated preview on 127.0.0.1:3127. The live service is not touched.
execute   consecutive upgrades A -> B -> C (#1863). Requires the prepared release, the expected live
          identity on :3105 and a consistent recorded release stack (the managed drop-in on disk is
          exactly the recorded one, byte for byte). It records the transition, replaces the ONE
          managed drop-in `999-https-release.conf` (fixed name: its precedence never depends on a
          source hash; a legacy `999-https-release-<sha12>.conf` is migrated), restarts and verifies
          the identity, the routes and the anonymous OAuth gate. Any failure re-installs the exact
          previous drop-in bytes, restarts and verifies the previous identity, routes and gate.
rollback  returns to the IMMEDIATE predecessor recorded in the stack (C -> B, then B -> A), with
          the same verification; it fails closed when the live identity is not the recorded top.
recover   completes an interrupted execute/rollback (power loss, kill): restores the recorded
          "from" configuration, or confirms the switch when it had already been recorded GREEN.

Markers: HTTPS_FRONTEND_PLAN, HTTPS_FRONTEND_PREPARE_PASS, HTTPS_FRONTEND_GREEN,
HTTPS_FRONTEND_ROLLED_BACK_VERIFIED, HTTPS_FRONTEND_RECOVERED_VERIFIED, HTTPS_FRONTEND_FAILED.
Release directories are never deleted; every replaced drop-in is kept byte for byte in the state.
Nothing outside the release directory, the managed drop-in and the state directory changes.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

RELEASES_DIR = Path("/opt/nexolab-external/releases")
STATE_DIR = Path("/var/lib/nexolab-https-frontend-release")
UNIT = "nexolab-external-ui-1569.service"
SERVICE_USER = "nexolab"
LIVE_PORT = 3105
PREVIEW_PORT = 3127
PUBLIC_URL = "https://nexolab-edge-01.tail7f9b04.ts.net"
MIN_FREE_BYTES = 20 * 1024**3
# Sorts after every existing "99-..." release drop-in, so this one decides ExecStart/WorkingDirectory.
DROPIN_PREFIX = "999-https-release-"
# #1863: one fixed managed drop-in name, so its precedence never depends on a source hash. "999-"
# sorts after the historic "99-release-*" drop-ins; the post-reload DropInPaths check proves it.
MANAGED_DROPIN = "999-https-release.conf"
STATE_SCHEMA = 2
IDENTITY_SCHEMA = "nexolab-runtime-identity-v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
BUILD_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
ROUTES = ("/", "/live", "/api/runtime-identity")


class ReleaseError(Exception):
    """A gate failed; nothing further is done."""


@dataclass
class Expectation:
    zip_sha256: str
    source: str
    build: str


@dataclass
class Host:
    """Side effects, injectable for tests."""

    run: Callable[[list[str]], subprocess.CompletedProcess] = lambda argv: subprocess.run(
        argv, capture_output=True, text=True, timeout=180, check=False
    )
    http_get: Callable[[str, float], tuple[int, str]] = field(default=None)  # type: ignore[assignment]
    free_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    log: Callable[[str], None] = lambda line: print(line, flush=True)

    def __post_init__(self) -> None:
        if self.http_get is None:
            self.http_get = _http_get


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 - urllib signature
        return None


def _http_get(url: str, timeout: float) -> tuple[int, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
            return response.status, response.read(256 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, OSError):
        return 0, ""


# ---------------------------------------------------------------- artifact verification


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def verify_artifact(zip_path: Path, expected: Expectation) -> dict[str, str]:
    """ZIP digest, internal checksums and the protected-HTTPS contract; returns the contract."""
    if not HEX64.fullmatch(expected.zip_sha256) or not SHA40.fullmatch(expected.source):
        raise ReleaseError("expected ZIP SHA-256 / source SHA are malformed")
    if not BUILD_ID.fullmatch(expected.build):
        raise ReleaseError("expected build id is malformed")
    actual = sha256_file(zip_path)
    if actual != expected.zip_sha256:
        raise ReleaseError(f"ZIP SHA-256 {actual} != expected {expected.zip_sha256}")
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for required in (
            "frontend-artifact-sha256.txt",
            "frontend-runtime.tar.gz",
            "frontend-runtime-files-sha256.txt",
            "frontend-public-contract.txt",
            "frontend-runtime-contract.txt",
            "frontend-source-sha.txt",
            "frontend-build-id.txt",
        ):
            if required not in names:
                raise ReleaseError(f"artifact lacks {required}")
        for line in archive.read("frontend-artifact-sha256.txt").decode().splitlines():
            if not line.strip():
                continue
            digest, name = line.split(None, 1)
            name = name.strip()
            if name not in names:
                raise ReleaseError(f"checksum list names a missing member {name}")
            member = hashlib.sha256()
            with archive.open(name) as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    member.update(chunk)
            if member.hexdigest() != digest:
                raise ReleaseError(f"internal checksum mismatch for {name}")
        source = archive.read("frontend-source-sha.txt").decode().strip()
        build = archive.read("frontend-build-id.txt").decode().strip()
        public = parse_key_values(archive.read("frontend-public-contract.txt").decode())
        runtime = parse_key_values(archive.read("frontend-runtime-contract.txt").decode())
    if source != expected.source or build != expected.build:
        raise ReleaseError(f"artifact identity {source}/{build} != expected {expected.source}/{expected.build}")
    if public.get("status") != "PASS" or public.get("build_id") != build:
        raise ReleaseError("public contract is not PASS for this build")
    if runtime.get("external_https_stage") != "true":
        raise ReleaseError("not a protected-HTTPS build (external_https_stage != true)")
    if not runtime.get("api_base_url", "").startswith("https://"):
        raise ReleaseError("protected-HTTPS build must use an https API origin")
    if runtime.get("auth_provider") != "local":
        raise ReleaseError("unexpected auth provider")
    return {**public, **{f"runtime.{key}": value for key, value in runtime.items()}}


def safe_member(member: tarfile.TarInfo) -> bool:
    """Regular files, directories and symlinks that stay inside the release directory."""
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not member.name or member.name.startswith("/"):
        return False
    if member.isdir() or member.isfile():
        return True
    if member.issym():
        target = PurePosixPath(member.linkname)
        if target.is_absolute():
            return False
        depth = len(path.parent.parts)
        ups = 0
        for part in target.parts:
            if part == "..":
                ups += 1
                if ups > depth:
                    return False
            else:
                break
        return True
    return False


def release_directory(source: str, build: str) -> Path:
    # The runtime identity reader takes the source from the directory name prefix.
    return RELEASES_DIR / f"{source}-https-{build}"


def extract_runtime(zip_path: Path, destination: Path, host: Host) -> int:
    """Extracts into `<destination>.partial`, verifies every file hash, then renames. Returns bytes."""
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists():
        raise ReleaseError(f"{destination} already exists; a release directory is never overwritten")
    if partial.exists():
        raise ReleaseError(f"{partial} exists from an earlier attempt; inspect it before retrying")
    with zipfile.ZipFile(zip_path) as archive:
        expected_hashes = {}
        for line in archive.read("frontend-runtime-files-sha256.txt").decode().splitlines():
            if line.strip():
                digest, name = line.split(None, 1)
                expected_hashes[name.strip().removeprefix("./")] = digest
        total = 0
        with archive.open("frontend-runtime.tar.gz") as raw:
            with tarfile.open(fileobj=raw, mode="r|gz") as tar:
                members = []
                for member in tar:
                    if not safe_member(member):
                        raise ReleaseError(f"unsafe archive member {member.name}")
                    total += member.size
                    members.append(member)
        if host.free_bytes(RELEASES_DIR) - total < MIN_FREE_BYTES:
            raise ReleaseError(
                f"extraction ({total} bytes) would leave less than the protected 20 GiB free; nothing extracted"
            )
        partial.mkdir(mode=0o755, parents=False)
        with archive.open("frontend-runtime.tar.gz") as raw:
            with tarfile.open(fileobj=raw, mode="r|gz") as tar:
                tar.extractall(partial, filter="data")
    seen = 0
    for name, digest in expected_hashes.items():
        path = partial / name
        if not path.is_file() or sha256_file(path) != digest:
            raise ReleaseError(f"runtime file hash mismatch for {name}; {partial} left for inspection")
        seen += 1
    if seen != len(expected_hashes) or seen == 0:
        raise ReleaseError("runtime file list is empty or incomplete")
    # Readable by the service account, writable by root only (the cache directory is added later).
    for root, directories, files in os.walk(partial):
        for name in directories:
            os.chmod(os.path.join(root, name), 0o755)
        for name in files:
            path = os.path.join(root, name)
            if not os.path.islink(path):
                os.chmod(path, 0o755 if os.stat(path).st_mode & 0o111 else 0o644)
    os.chmod(partial, 0o755)
    os.rename(partial, destination)
    return total


def verify_release_files(zip_path: Path, release: Path) -> int:
    """Every runtime file of the artifact manifest exists in `release` with its exact hash."""
    with zipfile.ZipFile(zip_path) as archive:
        manifest = archive.read("frontend-runtime-files-sha256.txt").decode().splitlines()
    checked = 0
    for line in manifest:
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        path = release / name.strip().removeprefix("./")
        if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
            raise ReleaseError(f"{release} does not match the artifact at {name.strip()}; nothing marked prepared")
        checked += 1
    if checked == 0:
        raise ReleaseError("the artifact runtime manifest is empty")
    return checked


def write_identity(release: Path, source: str, build: str) -> Path:
    if (release / ".next" / "BUILD_ID").read_text().strip() != build:
        raise ReleaseError(".next/BUILD_ID does not match the expected build")
    identity = release / ".nexolab-runtime-identity.json"
    identity.write_text(
        json.dumps(
            {
                "schema_version": IDENTITY_SCHEMA,
                "service": "dashboard",
                "source_commit": source,
                "build_id": build,
                "deployed_at": None,
                "identity_source": "offline_image_manifest",
            },
            sort_keys=True,
        )
        + "\n"
    )
    identity.chmod(0o644)
    return identity


# ---------------------------------------------------------------- systemd user unit


def user_systemctl(host: Host, *args: str) -> subprocess.CompletedProcess:
    return host.run(["systemctl", "--user", "-M", f"{SERVICE_USER}@", *args])


def show(host: Host, *properties: str) -> dict[str, str]:
    result = user_systemctl(host, "show", UNIT, *[f"--property={name}" for name in properties])
    if result.returncode != 0:
        raise ReleaseError(f"cannot read {UNIT}: {result.stderr.strip()}")
    return parse_key_values(result.stdout)


def execstart_argv(value: str) -> list[str]:
    """argv of `systemctl show -p ExecStart` (`{ path=... ; argv[]=a b c ; ... }`)."""
    match = re.search(r"argv\[\]=(.*?) ;", value)
    if not match:
        raise ReleaseError("cannot parse the unit's ExecStart")
    argv = match.group(1).split()
    if not argv:
        raise ReleaseError("the unit's ExecStart is empty")
    return argv


def render_dropin(argv: list[str], working_directory: str, release: Path, port: int) -> str:
    """Points the unit at `release`: same node binary and arguments, new release paths and port."""
    old = working_directory.rstrip("/")
    if not old or not any(part.startswith(old + "/") for part in argv):
        raise ReleaseError("the unit's ExecStart does not run from its WorkingDirectory release")
    new_argv = [str(release) + part[len(old):] if part.startswith(old + "/") else part for part in argv]
    if "--port" in new_argv:
        new_argv[new_argv.index("--port") + 1] = str(port)
    else:
        raise ReleaseError("the unit's ExecStart has no --port")
    return (
        "# Added by nexolab-https-frontend-release.py; remove it (and restart) to roll back.\n"
        "[Service]\n"
        f"WorkingDirectory={release}\n"
        f"Environment=NEXOLAB_RUNTIME_IDENTITY_FILE={release}/.nexolab-runtime-identity.json\n"
        "ExecStart=\n"
        f"ExecStart={' '.join(new_argv)}\n"
    )


def unit_dropin_dir() -> Path:
    home = Path(pwd.getpwnam(SERVICE_USER).pw_dir)
    return home / ".config" / "systemd" / "user" / f"{UNIT}.d"


def dropin_path(source: str) -> Path:  # noqa: ARG001 - kept for the v1 call sites; one fixed name
    """The single managed drop-in (#1863); the source no longer takes part in its name."""
    return unit_dropin_dir() / MANAGED_DROPIN


def open_directory_nofollow(path: Path) -> int:
    """A descriptor of `path`, walked from "/" one component at a time with O_NOFOLLOW (#1863
    review): a symlink anywhere fails, and later renames of any component cannot redirect what is
    done through the returned descriptor (no check-then-use race)."""
    if not path.is_absolute():
        raise ReleaseError(f"{path} is not absolute")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except OSError as error:
                raise ReleaseError(f"{path}: {part} is not a plain directory ({error.strerror}); nothing changed") from error
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def managed_dropins() -> list[Path]:
    directory = unit_dropin_dir()
    if not directory.exists() and not directory.is_symlink():
        return []
    descriptor = open_directory_nofollow(directory)
    try:
        names = sorted(name for name in os.listdir(descriptor) if MANAGED_NAME.fullmatch(name))
    finally:
        os.close(descriptor)
    return [directory / name for name in names]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


MANAGED_NAME = re.compile(r"^999-https-release(-[0-9a-f]{12})?\.conf$")


def read_nofollow(path: Path) -> str:
    directory = open_directory_nofollow(path.parent)
    try:
        # O_NONBLOCK: a FIFO planted by the service account cannot hang the root tool (review).
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError as error:
        raise ReleaseError(f"cannot read {path} ({error.strerror}); nothing changed") from error
    finally:
        os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReleaseError(f"{path} is not a regular file; nothing changed")
        with os.fdopen(descriptor, "r") as handle:
            descriptor = -1
            return handle.read()
    except OSError as error:
        raise ReleaseError(f"cannot read {path} ({error.strerror}); nothing changed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def identity_at(host: Host, port: int) -> tuple[str | None, str | None]:
    status, body = host.http_get(f"http://127.0.0.1:{port}/api/runtime-identity", 5.0)
    if status != 200:
        return None, None
    try:
        data = json.loads(body)
    except ValueError:
        return None, None
    return data.get("source_commit"), data.get("build_id")


def wait_identity(host: Host, port: int, source: str, build: str, timeout: float = 120.0) -> bool:
    deadline = host.now() + timeout
    while host.now() < deadline:
        if identity_at(host, port) == (source, build):
            return True
        host.sleep(2.0)
    return False


def routes_ok(host: Host, port: int) -> list[str]:
    failures = []
    for route in ROUTES:
        status, _ = host.http_get(f"http://127.0.0.1:{port}{route}", 10.0)
        if status not in (200, 307, 308):
            failures.append(f"{route}={status}")
    return failures


# ---------------------------------------------------------------- phases


def phase_plan(zip_path: Path, expected: Expectation, host: Host) -> dict:
    contract = verify_artifact(zip_path, expected)
    release = release_directory(expected.source, expected.build)
    unit = show(host, "WorkingDirectory", "ExecStart")
    argv = execstart_argv(unit.get("ExecStart", ""))
    dropin = render_dropin(argv, unit.get("WorkingDirectory", ""), release, LIVE_PORT)
    live = identity_at(host, LIVE_PORT)
    # Read-only preflight of the release stack (#1863): a v1 state or drop-in that execute would
    # refuse is reported here, before prepare, without changing anything.
    stack = load_stack(live)
    check_current_effective(host, stack[-1])
    host.log(
        "HTTPS_FRONTEND_STACK "
        + " -> ".join(f"{item['source'][:12]}/{item['build']}" for item in stack)
        + f" (rollback target after execute: {stack[-1]['source'][:12]}/{stack[-1]['build']})"
    )
    host.log(f"HTTPS_FRONTEND_PLAN live={live[0]}/{live[1]} release={release} exists={release.exists()}")
    host.log(f"drop-in {dropin_path(expected.source)}:\n{dropin}")
    return {"contract": contract, "release": str(release), "dropin": dropin, "live": live}


def phase_prepare(zip_path: Path, expected: Expectation, host: Host) -> dict:
    with StateLock():
        return _prepare(zip_path, expected, host)


def _prepare(zip_path: Path, expected: Expectation, host: Host) -> dict:
    verify_artifact(zip_path, expected)
    release = release_directory(expected.source, expected.build)
    # A previous "prepared" marker never outlives a new preparation: it is recreated only after every
    # check below passes, so a rejected release can never be executed on an old marker (review).
    (release / ".nexolab-https-prepared").unlink(missing_ok=True)
    if not release.exists():
        extract_runtime(zip_path, release, host)
    else:
        # A retry re-proves an existing directory file by file; a modified or corrupted runtime is
        # never certified as this artifact (review).
        verify_release_files(zip_path, release)
    write_identity(release, expected.source, expected.build)
    cache = release / ".next" / "cache"
    cache.mkdir(exist_ok=True)
    user = pwd.getpwnam(SERVICE_USER)
    os.chown(cache, user.pw_uid, user.pw_gid)
    if host.free_bytes(RELEASES_DIR) < MIN_FREE_BYTES:
        raise ReleaseError("less than the protected 20 GiB free after extraction")
    unit = show(host, "WorkingDirectory", "ExecStart", "Environment")
    argv = execstart_argv(unit.get("ExecStart", ""))
    old = unit.get("WorkingDirectory", "").rstrip("/")
    preview_argv = [str(release) + part[len(old):] if old and part.startswith(old + "/") else part for part in argv]
    preview_argv[preview_argv.index("--port") + 1] = str(PREVIEW_PORT)
    environment = [
        f"--setenv={item}"
        for item in unit.get("Environment", "").split()
        if "=" in item and not item.startswith("NEXOLAB_RUNTIME_IDENTITY_FILE=")
    ]
    preview_unit = f"nexolab-https-release-preview-{expected.source[:12]}"
    started = host.run(
        [
            "systemd-run",
            f"--uid={SERVICE_USER}",
            f"--unit={preview_unit}",
            "--collect",
            "--property=MemoryMax=805306368",
            f"--working-directory={release}",
            *environment,
            f"--setenv=NEXOLAB_RUNTIME_IDENTITY_FILE={release}/.nexolab-runtime-identity.json",
            *preview_argv,
        ]
    )
    if started.returncode != 0:
        raise ReleaseError(f"preview did not start: {started.stderr.strip()}")
    try:
        if not wait_identity(host, PREVIEW_PORT, expected.source, expected.build):
            raise ReleaseError("preview did not report the expected identity")
        failures = routes_ok(host, PREVIEW_PORT)
        if failures:
            raise ReleaseError(f"preview routes failed: {', '.join(failures)}")
    finally:
        host.run(["systemctl", "stop", f"{preview_unit}.service"])
    (release / ".nexolab-https-prepared").write_text(f"{expected.zip_sha256}\n")
    host.log(f"HTTPS_FRONTEND_PREPARE_PASS release={release} source={expected.source} build={expected.build}")
    return {"release": str(release)}


def write_journal(state: dict) -> None:
    """A timestamped record of every attempt, written before anything changes."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = STATE_DIR / f"journal-{stamp}.json"
    index = 1
    while path.exists():
        path = STATE_DIR / f"journal-{stamp}-{index}.json"
        index += 1
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _atomic_write(path: Path, payload: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def write_state(state: dict) -> None:
    """The release stack, written atomically and only after the switch is verified GREEN (review)."""
    _atomic_write(STATE_DIR / "state.json", state)


def transition_file() -> Path:
    return STATE_DIR / "transition.json"


class StateLock:
    """One execute/rollback/recover at a time (#1863): a second invocation is refused, not queued."""

    def __enter__(self) -> "StateLock":
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.handle = (STATE_DIR / "lock").open("w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            raise ReleaseError("another release operation is running; nothing changed") from error
        return self

    def __exit__(self, *exc: object) -> None:
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def entry(source: str, build: str, dropin: Path | None, text: str | None) -> dict:
    return {
        "source": source,
        "build": build,
        "dropin": str(dropin) if dropin else None,
        "dropin_text": text,
        "dropin_sha256": text_sha256(text) if text is not None else None,
    }


def validate_entry(item: dict) -> None:
    """Every recorded release: identity formats, a managed drop-in path inside the unit's drop-in
    directory, and text matching its hash; root never writes to a path taken from a tampered state."""
    if not SHA40.fullmatch(str(item.get("source"))) or not BUILD_ID.fullmatch(str(item.get("build"))):
        raise ReleaseError("recorded release identity is malformed; nothing changed")
    if item.get("dropin") is None:
        if item.get("dropin_text") is not None:
            raise ReleaseError("recorded release has drop-in text without a path; nothing changed")
        return
    path = Path(item["dropin"])
    if path.parent != unit_dropin_dir() or not MANAGED_NAME.fullmatch(path.name):
        raise ReleaseError(f"recorded drop-in {path} is not a managed drop-in of {UNIT}; nothing changed")
    if not isinstance(item.get("dropin_text"), str) or text_sha256(item["dropin_text"]) != item.get("dropin_sha256"):
        raise ReleaseError("recorded drop-in text does not match its hash; nothing changed")


def load_stack(live: tuple[str | None, str | None]) -> list[dict]:
    """The recorded release stack, proven consistent with the disk and the live service.

    No state: the unit runs its base configuration, so no managed drop-in may exist. A v1 state
    (#1837: dropin/previous/target) is converted, keeping the v1 drop-in bytes. The top entry must be
    the live identity and the only managed drop-in on disk must be the top's, byte for byte; any
    unrecorded, extra or modified managed drop-in is refused (nothing is deleted to "fix" it).
    """
    state_path = STATE_DIR / "state.json"
    on_disk = managed_dropins()
    if not state_path.is_file():
        if on_disk:
            raise ReleaseError(f"unrecorded managed drop-in {on_disk[0]}; nothing changed")
        if live[0] is None or live[1] is None:
            raise ReleaseError("the live service reports no identity; nothing changed")
        return [entry(live[0], live[1], None, None)]
    state = json.loads(state_path.read_text())
    if state.get("schema") == STATE_SCHEMA:
        stack = state["stack"]
    elif {"dropin", "previous", "target"} <= set(state):
        legacy = Path(state["dropin"])
        if not legacy.is_file():
            raise ReleaseError(f"recorded drop-in {legacy} is missing; nothing changed")
        legacy_text = read_nofollow(legacy)
        # The v1 drop-in must point at the v1 target release, not merely exist (review).
        target_release = release_directory(state["target"][0], state["target"][1])
        if f"WorkingDirectory={target_release}\n" not in legacy_text:
            raise ReleaseError(f"{legacy} does not point at the recorded release {target_release}; nothing changed")
        stack = [
            entry(state["previous"][0], state["previous"][1], None, None),
            entry(state["target"][0], state["target"][1], legacy, legacy_text),
        ]
    else:
        raise ReleaseError("unrecognised release state; nothing changed")
    if not stack:
        raise ReleaseError("empty release stack; nothing changed")
    for item in stack:
        validate_entry(item)
    top = stack[-1]
    if (top["source"], top["build"]) != tuple(live):
        raise ReleaseError(f"live identity {live} != recorded release {top['source']}/{top['build']}; nothing changed")
    expected = [Path(top["dropin"])] if top["dropin"] else []
    if on_disk != expected:
        raise ReleaseError(f"managed drop-ins {on_disk} != recorded {expected}; nothing changed")
    if top["dropin"] and text_sha256(read_nofollow(Path(top["dropin"]))) != top["dropin_sha256"]:
        raise ReleaseError(f"{top['dropin']} was modified outside this tool; nothing changed")
    return stack


def install_config(target: dict) -> None:
    """Exactly the target's managed drop-in (or none): every other managed drop-in is removed.

    #1863 review: everything is done relative to ONE descriptor of the unit's drop-in directory,
    opened component by component with O_NOFOLLOW, so the service account cannot redirect a root
    write by swapping a directory for a symlink. The drop-in is ROOT-owned 0644 (readable by the user
    manager, not modifiable by the service account), written through an O_EXCL|O_NOFOLLOW temporary
    with a random name, fsynced, renamed within the same directory, and the directory is fsynced."""
    directory = unit_dropin_dir()
    if not directory.exists() and not directory.is_symlink() and target["dropin"] is not None:
        parent = open_directory_nofollow(directory.parent)
        try:
            os.mkdir(directory.name, 0o755, dir_fd=parent)
        finally:
            os.close(parent)
    if not directory.exists() and not directory.is_symlink():
        return
    descriptor = open_directory_nofollow(directory)
    try:
        keep = Path(target["dropin"]).name if target["dropin"] else None
        for name in os.listdir(descriptor):
            if MANAGED_NAME.fullmatch(name) and name != keep:
                os.unlink(name, dir_fd=descriptor)
        if keep is not None:
            temporary = f".{MANAGED_DROPIN}.{os.urandom(8).hex()}.tmp"
            handle_fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=descriptor
            )
            try:
                with os.fdopen(handle_fd, "w") as handle:
                    handle.write(target["dropin_text"])
                    handle.flush()
                    os.fchmod(handle.fileno(), 0o644)
                    os.fsync(handle.fileno())
                os.replace(temporary, keep, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            except BaseException:
                try:
                    os.unlink(temporary, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
                raise
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def check_current_effective(host: Host, top: dict) -> None:
    """Before any change (#1863 review): the LOADED unit already applies exactly the recorded top
    drop-in, last; otherwise a later restore could not pass either, and nothing is touched."""
    paths = show(host, "DropInPaths").get("DropInPaths", "").split()
    managed = [path for path in paths if MANAGED_NAME.fullmatch(Path(path).name)]
    if top["dropin"] is None:
        if managed:
            raise ReleaseError(f"systemd applies managed drop-ins {managed} that are not recorded; nothing changed")
        return
    if managed != [top["dropin"]] or paths[-1] != top["dropin"]:
        raise ReleaseError(f"systemd does not apply {top['dropin']} last: {paths}; nothing changed")


def restart(host: Host) -> None:
    for args in (("daemon-reload",), ("restart", UNIT)):
        result = user_systemctl(host, *args)
        if result.returncode != 0:
            raise ReleaseError(f"systemctl --user {' '.join(args)} failed: {result.stderr.strip()}")


def check_effective(host: Host, target: dict) -> None:
    """After daemon-reload: the target's drop-in is the LAST one applied and the only managed one."""
    reload = user_systemctl(host, "daemon-reload")
    if reload.returncode != 0:
        raise ReleaseError(f"systemctl --user daemon-reload failed: {reload.stderr.strip()}")
    paths = show(host, "DropInPaths").get("DropInPaths", "").split()
    managed = [path for path in paths if MANAGED_NAME.fullmatch(Path(path).name)]
    if target["dropin"] is None:
        if managed:
            raise ReleaseError(f"a managed drop-in is still applied: {managed}")
        return
    if managed != [target["dropin"]] or paths[-1] != target["dropin"]:
        raise ReleaseError(f"the release drop-in is not the last one applied: {paths}")


def verify_live(host: Host, target: dict, require_gate: bool = True) -> None:
    if not wait_identity(host, LIVE_PORT, target["source"], target["build"]):
        raise ReleaseError(f"{target['source']}/{target['build']} did not report its identity on :3105")
    failures = routes_ok(host, LIVE_PORT)
    if failures:
        raise ReleaseError(f"routes failed after the switch: {', '.join(failures)}")
    status, _ = host.http_get(f"{PUBLIC_URL}/", 15.0)
    if status not in (302, 401, 403):
        message = f"anonymous public request answered {status}, expected the OAuth gate (302)"
        if require_gate:
            raise ReleaseError(message)
        # Restoring the predecessor cannot repair an OAuth outage outside the frontend; it is named,
        # never hidden, and the owner investigates the gate separately.
        host.log(f"HTTPS_FRONTEND_OAUTH_GATE_NOT_VERIFIED {message}")


def switch(host: Host, target: dict, require_gate: bool = True) -> None:
    install_config(target)
    check_effective(host, target)
    restart(host)
    verify_live(host, target, require_gate)


def restore(host: Host, target: dict) -> bool:
    """Back to `target` (the configuration before the attempt): exact bytes, identity, routes, gate."""
    try:
        switch(host, target, require_gate=False)
    except Exception as error:  # noqa: BLE001 - report, never raise from recovery
        host.log(f"HTTPS_FRONTEND_FAILED restore to {target['source']}/{target['build']}: {error}")
        return False
    host.log(f"HTTPS_FRONTEND_ROLLED_BACK_VERIFIED source={target['source']} build={target['build']}")
    return True


def transition(
    host: Host, kind: str, stack: list[dict], target: dict, new_stack: list[dict], require_gate: bool = True
) -> None:
    """Journal + transition record, switch, then the new stack; any failure restores the top."""
    current = stack[-1]
    record = {"kind": kind, "from": current, "to": target, "stack_before": stack, "stack_after": new_stack}
    write_journal(record)
    _atomic_write(transition_file(), record)
    try:
        switch(host, target, require_gate)
        # Inside the recovery boundary: without a recorded stack the switch is not kept (review).
        write_state({"schema": STATE_SCHEMA, "stack": new_stack})
    except Exception as error:  # noqa: BLE001 - any failure, including a systemctl timeout, restores
        host.log(f"HTTPS_FRONTEND_FAILED {error}; restoring {current['source']}/{current['build']}")
        if restore(host, current):
            # The new stack may already be on disk (e.g. the directory fsync failed after the
            # rename): the durable stack goes back with the configuration (review). Only then is the
            # record removed; if this write fails too, `recover` finishes it.
            try:
                write_state({"schema": STATE_SCHEMA, "stack": stack})
            except Exception as state_error:  # noqa: BLE001 - keep the record for `recover`
                host.log(f"HTTPS_FRONTEND_FAILED restoring the recorded stack: {state_error}; run recover")
            else:
                transition_file().unlink(missing_ok=True)
        if isinstance(error, ReleaseError):
            raise
        raise ReleaseError(f"activation failed: {error}") from error
    transition_file().unlink(missing_ok=True)


def refuse_pending_transition() -> None:
    if transition_file().is_file():
        raise ReleaseError("an interrupted release operation is recorded: run `recover` first; nothing changed")


def phase_execute(zip_path: Path, expected: Expectation, current: tuple[str, str], host: Host) -> dict:
    verify_artifact(zip_path, expected)
    release = release_directory(expected.source, expected.build)
    marker = release / ".nexolab-https-prepared"
    if not marker.is_file() or marker.read_text().strip() != expected.zip_sha256:
        raise ReleaseError("release is not prepared from this artifact: run prepare first")
    # The installed files are re-proven at activation too, not only trusted through the marker.
    verify_release_files(zip_path, release)
    if host.free_bytes(RELEASES_DIR) < MIN_FREE_BYTES:
        raise ReleaseError("less than the protected 20 GiB free; nothing changed")
    with StateLock():
        refuse_pending_transition()
        live = identity_at(host, LIVE_PORT)
        if live != current:
            raise ReleaseError(f"live identity {live} != expected current {current}; nothing changed")
        stack = load_stack(live)
        check_current_effective(host, stack[-1])
        if (expected.source, expected.build) == current:
            raise ReleaseError("the target release is already live; nothing changed")
        unit = show(host, "WorkingDirectory", "ExecStart")
        text = render_dropin(
            execstart_argv(unit.get("ExecStart", "")), unit.get("WorkingDirectory", ""), release, LIVE_PORT
        )
        target = entry(expected.source, expected.build, dropin_path(expected.source), text)
        transition(host, "execute", stack, target, [*stack, target])
    host.log(f"HTTPS_FRONTEND_GREEN source={expected.source} build={expected.build} dropin={target['dropin']}")
    return {"dropin": target["dropin"]}


def phase_rollback(host: Host, current: tuple[str, str] | None = None) -> bool:
    """To the immediate predecessor; fails closed unless the live identity is the recorded top."""
    with StateLock():
        refuse_pending_transition()
        live = identity_at(host, LIVE_PORT)
        if current is not None and live != current:
            raise ReleaseError(f"live identity {live} != expected current {current}; nothing changed")
        stack = load_stack(live)
        check_current_effective(host, stack[-1])
        if len(stack) < 2:
            raise ReleaseError("no recorded predecessor: nothing to roll back")
        previous = stack[-2]
        # An explicit rollback must stay possible during an OAuth outage outside the frontend; the
        # gate is then reported (HTTPS_FRONTEND_OAUTH_GATE_NOT_VERIFIED), never hidden (review).
        transition(host, "rollback", stack, previous, stack[:-1], require_gate=False)
    host.log(f"HTTPS_FRONTEND_ROLLED_BACK_VERIFIED source={previous['source']} build={previous['build']}")
    return True


def phase_recover(host: Host) -> bool:
    """Completes an interrupted execute/rollback recorded in transition.json.

    The switch counts as completed only when its stack was written AND the target reports its
    identity within the normal start timeout; otherwise the "from" configuration is restored and the
    durable stack is set back to the one before the attempt, atomically, before the record is removed.
    """
    with StateLock():
        if not transition_file().is_file():
            host.log("HTTPS_FRONTEND_NOTHING_TO_RECOVER")
            return True
        record = json.loads(transition_file().read_text())
        for item in (record["from"], record["to"], *record["stack_before"], *record["stack_after"]):
            validate_entry(item)
        state_path = STATE_DIR / "state.json"
        recorded = json.loads(state_path.read_text()) if state_path.is_file() else None
        target = record["to"]
        if (
            recorded
            and recorded.get("stack") == record["stack_after"]
            and wait_identity(host, LIVE_PORT, target["source"], target["build"])
        ):
            transition_file().unlink()
            host.log(f"HTTPS_FRONTEND_RECOVERED_VERIFIED switch had completed: {target['source']}/{target['build']}")
            return True
        if not restore(host, record["from"]):
            return False
        write_state({"schema": STATE_SCHEMA, "stack": record["stack_before"]})
        transition_file().unlink()
        host.log(f"HTTPS_FRONTEND_RECOVERED_VERIFIED restored {record['from']['source']}/{record['from']['build']}")
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=("plan", "prepare", "execute", "rollback", "recover"))
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--expect-zip-sha256")
    parser.add_argument("--expect-source")
    parser.add_argument("--expect-build")
    parser.add_argument("--expect-current-source")
    parser.add_argument("--expect-current-build")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        print("HTTPS_FRONTEND_FAILED run with sudo (root is needed for /opt and the user unit)")
        return 2
    host = Host()
    try:
        if args.phase == "recover":
            return 0 if phase_recover(host) else 1
        if args.phase == "rollback":
            current = (
                (args.expect_current_source, args.expect_current_build)
                if args.expect_current_source and args.expect_current_build
                else None
            )
            return 0 if phase_rollback(host, current) else 1
        if not (args.artifact and args.expect_zip_sha256 and args.expect_source and args.expect_build):
            raise ReleaseError("--artifact, --expect-zip-sha256, --expect-source and --expect-build are required")
        expected = Expectation(args.expect_zip_sha256, args.expect_source, args.expect_build)
        if args.phase == "plan":
            phase_plan(args.artifact, expected, host)
        elif args.phase == "prepare":
            phase_prepare(args.artifact, expected, host)
        else:
            if not (args.expect_current_source and args.expect_current_build):
                raise ReleaseError("execute needs --expect-current-source and --expect-current-build")
            phase_execute(args.artifact, expected, (args.expect_current_source, args.expect_current_build), host)
        return 0
    except ReleaseError as error:
        print(f"HTTPS_FRONTEND_FAILED {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
