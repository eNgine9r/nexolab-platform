#!/usr/bin/env python3
"""Guarded owner-operated gateway update; never log identities or credentials.

Default mode only checks readiness. --execute is a separate explicit action.
Protected backups support recovery after process or power interruption.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from pathlib import Path

OLD_SHA = "ff1ddd7f96a67790f897f0c2a1450e864fd4a918c13e2fa66d8dbeb4682f0a1d"
NEW_SHA = "1856f7622531f7b0f5e12d56815717f5bdaf1a49d5f69d952704bd30f6de6794"
UNIT = "nexolab-google-oauth-stage.service"
LAUNCHER = Path("/opt/nexolab-external/bin/launch-google-oauth.py")
ALLOWLIST = Path("/etc/nexolab-external/allowed-emails.txt")
CANDIDATE = Path("/home/nexolab/commander-workspaces/nexolab-platform/nexolab-1523-launcher-candidate.py")
ROOT = Path("/var/lib/nexolab/version-management")
BACKUP_PARENT = Path("/etc/nexolab-external")
PROXY_BINARY = Path("/opt/nexolab-external/bin/oauth2-proxy")
EMAIL = re.compile(rb"[a-z0-9_.+%-]+@[a-z0-9.-]+\.[a-z]{2,}\Z")
DEPLOYMENT_LOCKS = (
    Path("/tmp/nexolab-current-head-launch.lock"),
    Path("/run/user/1000/nexolab-current-head-launch.lock"),
)


class GuardError(Exception):
    pass


def read_regular(path: Path, *, uid: int | tuple[int, ...] | None = None, mode: int | None = None) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        permitted = (uid,) if isinstance(uid, int) else uid
        if not stat.S_ISREG(info.st_mode) or (permitted is not None and info.st_uid not in permitted):
            raise GuardError("file type or owner rejected")
        if mode is not None and stat.S_IMODE(info.st_mode) != mode:
            raise GuardError("file mode rejected")
        if info.st_size > 100_000:
            raise GuardError("file exceeds size limit")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read(100_001)
    finally:
        os.close(fd)


def validate_identities(current: bytes, additions: bytes) -> bytes:
    old, extra = current.splitlines(), additions.splitlines()
    values = old + extra
    if (
        len(old) != 1 or len(extra) != 5 or len(set(values)) != 6
        or any(len(value) > 254 or not EMAIL.fullmatch(value) for value in values)
    ):
        raise GuardError("expected one existing and five distinct named identities")
    return b"\n".join(values) + b"\n"


def verify_version_plane(root: Path) -> None:
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, 10001) or info.st_mode & 0o022:
        raise GuardError("version authority directory is unsafe")
    current = json.loads(read_regular(root / "current.json", uid=(0, 10001)))
    if not isinstance(current, dict) or current.get("runtime_state_known") is not True or current.get("health") != "ready":
        raise GuardError("version authority is not ready")
    for name in ("requests", "update-check-requests", "operations"):
        directory = root / name
        try:
            metadata = directory.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid not in (0, 10001) or metadata.st_mode & 0o022:
            raise GuardError("version queue directory is unsafe")
        if name != "operations" and any(directory.glob("*.json")):
            raise GuardError("version operation is queued")
    for path in (root / "operations").glob("*.json"):
        operation = json.loads(read_regular(path, uid=(0, 10001)))
        if not isinstance(operation, dict) or operation.get("status") in {"queued", "running"}:
            raise GuardError("version operation is active or malformed")


def acquire_existing_deployment_locks(stack: contextlib.ExitStack, paths: tuple[Path, ...], *,
                                      owner_uids: tuple[int, ...] = (0, 1000),
                                      prepare_user_lock: bool = False,
                                      allow_missing_user_lock: bool = False,
                                      user_uid: int = 1000) -> bool:
    """Lock both contexts; only the missing user-runtime lock may be created."""
    if len(paths) != 2 or paths[0] == paths[1]:
        raise GuardError("both distinct deployment lock paths must be verified")
    identities = set()
    missing_user_lock = False
    for index, path in enumerate(paths):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if index != 1 or not (prepare_user_lock or allow_missing_user_lock):
                raise
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent_fd)
            parent = os.fstat(parent_fd)
            if parent.st_uid != user_uid or stat.S_IMODE(parent.st_mode) != 0o700:
                raise GuardError("user runtime directory is unsafe")
            if not prepare_user_lock:
                missing_user_lock = True
                continue
            try:
                fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent_fd)
            except FileExistsError:
                raise GuardError("user deployment lock appeared during preparation; retry") from None
            try:
                os.fchown(fd, user_uid, parent.st_gid)
                os.fchmod(fd, 0o600)
                os.fsync(fd)
                os.fsync(parent_fd)
            except Exception:
                os.close(fd)
                raise
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in owner_uids
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise GuardError("deployment lock is unsafe")
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            raise GuardError("deployment locks unexpectedly share an inode")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        named = path.lstat()
        if (named.st_dev, named.st_ino) != identity:
            raise GuardError("deployment lock identity changed")
        identities.add(identity)
    return missing_user_lock


def assert_no_deleted_deployment_locks(paths: tuple[Path, ...], proc: Path = Path("/proc")) -> None:
    """Refuse to create or use a replacement while any process holds an unlinked lock."""
    deleted = {str(path) + " (deleted)" for path in paths}
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise GuardError("cannot inspect active deployment lock descriptors") from None
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                raise GuardError("cannot inspect active deployment lock descriptors") from None
            if target in deleted:
                raise GuardError("an unlinked deployment lock is still open")


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, temp = tempfile.mkstemp(prefix=".nexolab-oauth-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temp).unlink(missing_ok=True)


def save_backup(directory: Path, old_launcher: bytes, old_list: bytes, new_list: bytes) -> None:
    """Persist and verify both sides before any changes to a running gateway."""
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise GuardError("backup directory is unsafe")
    for name, data in (("launcher", old_launcher), ("allowlist", old_list), ("proposed-list", new_list)):
        target = directory / name
        if target.exists() or target.is_symlink():
            raise GuardError("backup destination already exists")
        atomic_write(target, data, 0o600)
        if read_regular(target, uid=os.geteuid(), mode=0o600) != data:
            raise GuardError("backup readback mismatch")
    parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def recover_from_backup(launcher: Path, allowlist: Path, directory: Path,
                        old_sha: str, new_sha: str, restart) -> None:
    """Restore only a known pre-activation state, never an unrelated update."""
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise GuardError("backup directory is unsafe")
    original = read_regular(directory / "launcher", uid=os.geteuid(), mode=0o600)
    previous_list = read_regular(directory / "allowlist", uid=os.geteuid(), mode=0o600)
    proposed = read_regular(directory / "proposed-list", uid=os.geteuid(), mode=0o600)
    if hashlib.sha256(original).hexdigest() != old_sha:
        raise GuardError("backup launcher checksum mismatch")
    old_lines, proposed_lines = previous_list.splitlines(), proposed.splitlines()
    if len(proposed_lines) != 6 or proposed_lines[:1] != old_lines or validate_identities(previous_list, b"\n".join(proposed_lines[1:]) + b"\n") != proposed:
        raise GuardError("backup identity lists do not match rollout contract")
    active_launcher = read_regular(launcher)
    active_list = read_regular(allowlist)
    if hashlib.sha256(active_launcher).hexdigest() not in (old_sha, new_sha) or active_list not in (previous_list, proposed):
        raise GuardError("site state is not part of the backed up rollout")
    atomic_write(allowlist, previous_list, 0o600)
    atomic_write(launcher, original, 0o755)
    if read_regular(launcher) != original or read_regular(allowlist) != previous_list:
        raise GuardError("restored file readback mismatch")
    restart()


def run_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/systemctl", *args], capture_output=True, text=True,
        check=False, timeout=30,
    )


def verify_service() -> None:
    state = run_systemctl("is-active", "--quiet", UNIT)
    pid = run_systemctl("show", UNIT, "-p", "MainPID", "--value")
    if state.returncode or pid.returncode or not pid.stdout.strip().isdigit():
        raise GuardError("gateway service is not active")
    if not os.path.samefile(Path("/proc", pid.stdout.strip(), "exe"), PROXY_BINARY):
        raise GuardError("gateway process is not the expected proxy binary")
    args = Path("/proc", pid.stdout.strip(), "cmdline").read_bytes().split(b"\0")
    option = b"--authenticated-emails-file"
    if option not in args:
        raise GuardError("gateway credential argument missing")
    index = args.index(option)
    if index + 1 >= len(args) or args[index + 1] != (
        b"/run/credentials/" + UNIT.encode("ascii") + b"/allowed-emails.txt"
    ):
        raise GuardError("gateway is not using the expected systemd credential")
    connection = http.client.HTTPConnection("127.0.0.1", 4180, timeout=5)
    try:
        connection.request("GET", "/oauth2/auth")
        response = connection.getresponse()
        response.read()
        if response.status != 401:
            raise GuardError("anonymous gateway request was not denied")
    finally:
        connection.close()


def restart_and_verify() -> None:
    if run_systemctl("restart", UNIT).returncode:
        raise GuardError("gateway restart failed")
    for attempt in range(20):
        try:
            verify_service()
            return
        except (GuardError, OSError, http.client.HTTPException):
            if attempt == 19:
                raise GuardError("gateway did not pass post-restart checks") from None
            time.sleep(0.5)


def transact(launcher: Path, allowlist: Path, candidate: bytes, new_list: bytes,
             old_launcher: bytes, old_list: bytes, restart) -> None:
    """Never expose a new list to the old launcher; reverse order on rollback."""
    try:
        atomic_write(launcher, candidate, 0o755)
        atomic_write(allowlist, new_list, 0o600)
        if read_regular(launcher) != candidate or read_regular(allowlist) != new_list:
            raise GuardError("installed file readback mismatch")
        restart()
    except Exception as error:
        try:
            atomic_write(allowlist, old_list, 0o600)
            atomic_write(launcher, old_launcher, 0o755)
            if read_regular(launcher) != old_launcher or read_regular(allowlist) != old_list:
                raise GuardError("rollback file readback mismatch")
            restart()
        except Exception:
            raise GuardError("activation and automatic rollback failed; use protected backup") from None
        raise GuardError("activation failed; previous files and gateway restored") from error


def protected_backup(parent: Path, old_launcher: bytes, old_list: bytes, new_list: bytes) -> Path:
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise GuardError("backup parent is unsafe")
    backup = Path(tempfile.mkdtemp(prefix="gateway-1523-", dir=parent))
    save_backup(backup, old_launcher, old_list, new_list)
    return backup


def activate_with_backup(launcher: Path, allowlist: Path, backup_parent: Path,
                         candidate: bytes, new_list: bytes, old_launcher: bytes,
                         old_list: bytes, restart) -> Path:
    backup = protected_backup(backup_parent, old_launcher, old_list, new_list)
    print(f"BACKUP_READY={backup}", flush=True)
    if (read_regular(launcher, uid=os.geteuid(), mode=0o755) != old_launcher
            or read_regular(allowlist, uid=os.geteuid(), mode=0o600) != old_list):
        raise GuardError("site files changed during preflight")
    transact(launcher, allowlist, candidate, new_list, old_launcher, old_list, restart)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--additions-file", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--recover", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise GuardError("root is required")
    if not args.recover and not args.additions_file:
        raise GuardError("private approved additions file is required")
    if args.recover and args.additions_file:
        raise GuardError("recovery cannot accept new identities")
    with contextlib.ExitStack() as stack:
        for name in ("worker.lock", "queue.lock", "update-plane.lock"):
            fd = os.open(ROOT / name, os.O_RDWR | os.O_NOFOLLOW)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, 10001) or info.st_nlink != 1 or info.st_mode & 0o022:
                raise GuardError("canonical lock is unsafe")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            named = (ROOT / name).lstat()
            if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                raise GuardError("canonical lock identity changed")
        verify_version_plane(ROOT)
        assert_no_deleted_deployment_locks(DEPLOYMENT_LOCKS)
        missing_user_lock = acquire_existing_deployment_locks(
            stack, DEPLOYMENT_LOCKS, prepare_user_lock=bool(args.execute or args.recover),
            allow_missing_user_lock=not bool(args.execute or args.recover),
        )
        assert_no_deleted_deployment_locks(DEPLOYMENT_LOCKS)
        definition = run_systemctl("cat", UNIT)
        active_start = run_systemctl("show", UNIT, "-p", "ExecStart", "--value")
        required = "LoadCredential=allowed-emails.txt:/etc/nexolab-external/allowed-emails.txt"
        if definition.returncode or required not in definition.stdout.splitlines():
            raise GuardError("unit credential source not confirmed")
        if active_start.returncode or str(LAUNCHER) not in active_start.stdout or "--run" not in active_start.stdout:
            raise GuardError("unit does not start the expected launcher")
        if args.recover:
            if args.recover.parent != BACKUP_PARENT or not args.recover.name.startswith("gateway-1523-"):
                raise GuardError("recovery path is outside the protected backup directory")
            parent = BACKUP_PARENT.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o077:
                raise GuardError("backup parent is unsafe")
            read_regular(LAUNCHER, uid=0, mode=0o755)
            read_regular(ALLOWLIST, uid=0, mode=0o600)
            recover_from_backup(LAUNCHER, ALLOWLIST, args.recover, OLD_SHA, NEW_SHA, restart_and_verify)
            print("RECOVERY_PASS: original files restored; actual owner login remains to be verified")
            return 0
        old_launcher = read_regular(LAUNCHER, uid=0, mode=0o755)
        old_list = read_regular(ALLOWLIST, uid=0, mode=0o600)
        candidate = read_regular(CANDIDATE)
        additions = read_regular(args.additions_file, uid=0, mode=0o600)
        if hashlib.sha256(old_launcher).hexdigest() != OLD_SHA:
            raise GuardError("installed launcher does not match baseline")
        if hashlib.sha256(candidate).hexdigest() != NEW_SHA:
            raise GuardError("candidate launcher checksum mismatch")
        new_list = validate_identities(old_list, additions)
        verify_service()
        if not args.execute:
            suffix = "; missing user lock will be created at execution" if missing_user_lock else ""
            print(f"PREFLIGHT_PASS: gateway and six named identities verified; no changes made{suffix}")
            return 0
        activate_with_backup(LAUNCHER, ALLOWLIST, BACKUP_PARENT, candidate, new_list,
                             old_launcher, old_list, restart_and_verify)
        print("GATEWAY_UPDATED: anonymous denial verified; actual user logins remain to be verified")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GuardError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc if isinstance(exc, GuardError) else 'system preflight failed'}")
        raise SystemExit(1)
