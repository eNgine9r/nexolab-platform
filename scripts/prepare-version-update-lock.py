#!/usr/bin/env python3
"""Prepare the one shared API/Root update-plane lock without replacing its inode."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import stat


def identity(info: os.stat_result) -> dict:
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid,
            "gid": info.st_gid, "mode": f"{stat.S_IMODE(info.st_mode):04o}"}


def checked_file(stack: ExitStack, directory: int, name: str, flags: int, uid: int) -> int:
    descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o640, dir_fd=directory)
    stack.callback(os.close, descriptor)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid not in {0, uid}:
        raise RuntimeError(f"{name}: expected regular file without hardlinks and approved owner")
    return descriptor


def exclusive(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError("native worker or update plane is active; no permissions changed") from error


def assert_named_inode(directory: int, name: str, descriptor: int) -> None:
    opened = os.fstat(descriptor)
    named = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
        raise RuntimeError(f"{name}: lock inode changed; no permissions changed")


def assert_idle_queue(stack: ExitStack, directory: int, name: str, uid: int) -> None:
    try:
        queue = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return
    stack.callback(os.close, queue)
    info = os.fstat(queue)
    if info.st_uid not in {0, uid} or info.st_mode & 0o022:
        raise RuntimeError(f"{name}: unexpected queue ownership or writable directory")
    if any(item.endswith(".json") for item in os.listdir(queue)):
        raise RuntimeError("a version operation or update check is queued; no permissions changed")


def prepare(root: Path, *, state_uid: int = 10001, state_gid: int = 10001,
            existing_only: bool = False, expected_bundle: str | None = None,
            expected_operation: str | None = None) -> dict:
    with ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        parent = os.fstat(directory)
        if (parent.st_uid, parent.st_gid) != (state_uid, state_gid) or parent.st_mode & 0o022:
            raise RuntimeError("unexpected state ownership or writable parent")

        try:
            worker = checked_file(stack, directory, "worker.lock", os.O_RDWR, state_uid)
        except FileNotFoundError:
            if expected_operation is not None:
                raise RuntimeError("native worker lock unavailable; no permissions changed")
        else:
            exclusive(worker)

        if expected_bundle is not None or expected_operation is not None:
            if not existing_only or not expected_bundle or not expected_operation:
                raise RuntimeError("repair requires exact current authority and existing lock")
            current_fd = checked_file(stack, directory, "current.json", os.O_RDONLY, state_uid)
            current = json.loads(os.read(current_fd, 131072))
            if (not isinstance(current, dict) or current.get("bundle_id") != expected_bundle
                    or current.get("last_operation_id") != expected_operation
                    or current.get("deployment_authority") != "validated_package"
                    or current.get("health") != "ready" or current.get("runtime_state_known") is not True):
                raise RuntimeError("current authority changed; no permissions changed")

        flags = os.O_RDWR | (0 if existing_only else os.O_CREAT)
        descriptor = checked_file(stack, directory, "update-plane.lock", flags, state_uid)
        before = os.fstat(descriptor)
        if before.st_size != 0 or before.st_gid not in {0, state_gid} or before.st_mode & 0o022:
            raise RuntimeError("expected empty lock with approved ownership and permissions")
        exclusive(descriptor)

        # Discovery holds update-plane before queue.lock. Use that same order;
        # the API queues native operations under queue.lock independently.
        try:
            queue_lock = checked_file(stack, directory, "queue.lock", os.O_RDWR, state_uid)
        except FileNotFoundError:
            if expected_operation is not None:
                raise RuntimeError("native queue lock unavailable; no permissions changed")
        else:
            exclusive(queue_lock)
            assert_named_inode(directory, "queue.lock", queue_lock)
        for name in ("requests", "update-check-requests"):
            assert_idle_queue(stack, directory, name, state_uid)
        assert_named_inode(directory, "update-plane.lock", descriptor)
        os.fchown(descriptor, state_uid, state_gid)
        os.fchmod(descriptor, 0o640)
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        return {"status": "shared_update_plane_lock_prepared", "before": identity(before),
                "after": identity(after), "inode_retained": before.st_ino == after.st_ino,
                "package_activation": False, "database_restore": False, "controller_write": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/var/lib/nexolab/version-management"))
    parser.add_argument("--repair-existing", action="store_true")
    parser.add_argument("--expected-current-bundle")
    parser.add_argument("--expected-current-operation")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("controlled host Root context required")
    if args.repair_existing and not (args.expected_current_bundle and args.expected_current_operation):
        parser.error("repair requires the exact current bundle and completed operation")
    result = prepare(args.root, existing_only=args.repair_existing,
                     expected_bundle=args.expected_current_bundle,
                     expected_operation=args.expected_current_operation)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
