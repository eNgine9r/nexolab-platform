#!/usr/bin/env python3
"""Guarded release of the protected HTTPS frontend (Funnel :443 -> OAuth -> 127.0.0.1:3105).

OWNER-RUN with sudo. The agent prepares and verifies the artifact; it never runs this tool.

    sudo python3 -I nexolab-https-frontend-release.py plan     --artifact ZIP --expect-zip-sha256 HEX \\
        --expect-source SHA --expect-build ID
    sudo python3 -I nexolab-https-frontend-release.py prepare  (same arguments)
    sudo python3 -I nexolab-https-frontend-release.py execute  (same arguments) \\
        --expect-current-source SHA --expect-current-build ID
    sudo python3 -I nexolab-https-frontend-release.py rollback

plan      read-only: verifies the artifact and prints what prepare/execute would change.
prepare   verifies the ZIP SHA-256, its internal checksums and the HTTPS contract, extracts the
          runtime into a NEW release directory (never overwriting one), verifies every runtime
          file hash, writes the runtime identity, keeps >= 20 GiB free, and proves the release in an
          isolated preview on 127.0.0.1:3127. The live service is not touched.
execute   requires the prepared release and the expected live identity on :3105, records the
          rollback state, adds one systemd drop-in to the user unit that points it at the new
          release, restarts it and verifies the identity, the routes and the anonymous OAuth gate.
          Any failure removes the drop-in, restarts and verifies the previous identity.
rollback  removes the drop-in this tool added and verifies the previous identity.

Markers: HTTPS_FRONTEND_PLAN, HTTPS_FRONTEND_PREPARE_PASS, HTTPS_FRONTEND_GREEN,
HTTPS_FRONTEND_ROLLED_BACK_VERIFIED, HTTPS_FRONTEND_FAILED. Previous releases and drop-ins are
never deleted. Nothing outside the release directory, the drop-in and the state directory changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
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


def dropin_path(source: str) -> Path:
    home = Path(pwd.getpwnam(SERVICE_USER).pw_dir)
    return home / ".config" / "systemd" / "user" / f"{UNIT}.d" / f"{DROPIN_PREFIX}{source[:12]}.conf"


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
    host.log(f"HTTPS_FRONTEND_PLAN live={live[0]}/{live[1]} release={release} exists={release.exists()}")
    host.log(f"drop-in {dropin_path(expected.source)}:\n{dropin}")
    return {"contract": contract, "release": str(release), "dropin": dropin, "live": live}


def phase_prepare(zip_path: Path, expected: Expectation, host: Host) -> dict:
    verify_artifact(zip_path, expected)
    release = release_directory(expected.source, expected.build)
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
    (STATE_DIR / f"journal-{stamp}.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def write_state(state: dict) -> None:
    """The installed release, written atomically and only after it is verified GREEN (review)."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE_DIR / "state.json.tmp"
    with temporary.open("w") as handle:
        handle.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, STATE_DIR / "state.json")


def restart(host: Host) -> None:
    for args in (("daemon-reload",), ("restart", UNIT)):
        result = user_systemctl(host, *args)
        if result.returncode != 0:
            raise ReleaseError(f"systemctl --user {' '.join(args)} failed: {result.stderr.strip()}")


def restore(host: Host, dropin: Path, previous: tuple[str, str]) -> bool:
    if dropin.exists():
        dropin.unlink()
    try:
        restart(host)
    except Exception as error:  # noqa: BLE001 - report, never raise from recovery
        host.log(f"HTTPS_FRONTEND_FAILED restart during rollback: {error}")
        return False
    ok = wait_identity(host, LIVE_PORT, previous[0], previous[1])
    host.log(
        "HTTPS_FRONTEND_ROLLED_BACK_VERIFIED" if ok else "HTTPS_FRONTEND_FAILED rollback identity not verified"
    )
    return ok


def phase_execute(zip_path: Path, expected: Expectation, current: tuple[str, str], host: Host) -> dict:
    verify_artifact(zip_path, expected)
    release = release_directory(expected.source, expected.build)
    marker = release / ".nexolab-https-prepared"
    if not marker.is_file() or marker.read_text().strip() != expected.zip_sha256:
        raise ReleaseError("release is not prepared from this artifact: run prepare first")
    live = identity_at(host, LIVE_PORT)
    if live != current:
        raise ReleaseError(f"live identity {live} != expected current {current}; nothing changed")
    unit = show(host, "WorkingDirectory", "ExecStart")
    dropin_text = render_dropin(execstart_argv(unit.get("ExecStart", "")), unit.get("WorkingDirectory", ""), release, LIVE_PORT)
    dropin = dropin_path(expected.source)
    # One release drop-in of this tool at a time: overwriting or stacking one would lose the drop-in
    # the recorded previous identity depends on, and a later rollback would activate an older
    # underlying release (review). Roll back first.
    installed = sorted(dropin.parent.glob(f"{DROPIN_PREFIX}*.conf")) if dropin.parent.is_dir() else []
    if installed:
        raise ReleaseError(f"{installed[0]} is already installed; run rollback first; nothing changed")
    user = pwd.getpwnam(SERVICE_USER)
    state = {"dropin": str(dropin), "previous": list(current), "release": str(release), "target": [expected.source, expected.build]}
    write_journal(state)
    dropin.parent.mkdir(parents=True, exist_ok=True)
    os.chown(dropin.parent, user.pw_uid, user.pw_gid)
    dropin.write_text(dropin_text)
    os.chown(dropin, user.pw_uid, user.pw_gid)
    dropin.chmod(0o644)
    try:
        reload = user_systemctl(host, "daemon-reload")
        if reload.returncode != 0:
            raise ReleaseError(f"systemctl --user daemon-reload failed: {reload.stderr.strip()}")
        paths = show(host, "DropInPaths").get("DropInPaths", "").split()
        if not paths or paths[-1] != str(dropin):
            raise ReleaseError(f"the release drop-in is not the last one applied: {paths}")
        restart(host)
        if not wait_identity(host, LIVE_PORT, expected.source, expected.build):
            raise ReleaseError("new release did not report its identity on :3105")
        failures = routes_ok(host, LIVE_PORT)
        if failures:
            raise ReleaseError(f"routes failed after the switch: {', '.join(failures)}")
        status, _ = host.http_get(f"{PUBLIC_URL}/", 15.0)
        if status not in (302, 401, 403):
            raise ReleaseError(f"anonymous public request answered {status}, expected the OAuth gate (302)")
        # Inside the recovery boundary: without a rollback record the release is not kept (review).
        write_state(state)
    except Exception as error:  # noqa: BLE001 - any failure, including a systemctl timeout, rolls back
        host.log(f"HTTPS_FRONTEND_FAILED {error}; rolling back")
        restore(host, dropin, current)
        if isinstance(error, ReleaseError):
            raise
        raise ReleaseError(f"activation failed: {error}") from error
    host.log(f"HTTPS_FRONTEND_GREEN source={expected.source} build={expected.build} dropin={dropin}")
    return {"dropin": str(dropin)}


def phase_rollback(host: Host) -> bool:
    state_file = STATE_DIR / "state.json"
    if not state_file.is_file():
        raise ReleaseError("no recorded release state: nothing to roll back")
    state = json.loads(state_file.read_text())
    previous = tuple(state["previous"])
    return restore(host, Path(state["dropin"]), (previous[0], previous[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=("plan", "prepare", "execute", "rollback"))
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
        if args.phase == "rollback":
            return 0 if phase_rollback(host) else 1
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
