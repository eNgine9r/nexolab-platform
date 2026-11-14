"""Synthetic tests only; never touch a real gateway or service."""
from __future__ import annotations

import importlib.util
import hashlib
import contextlib
import fcntl
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/operations/nexolab_google_oauth_gateway_rollout.py"
SPEC = importlib.util.spec_from_file_location("gateway_rollout", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GatewayRolloutTests(unittest.TestCase):
    old = b"owner@example.test\n"
    additions = b"a@example.test\nb@example.test\nc@example.test\nd@example.test\ne@example.test\n"

    def test_activation_without_approved_file_stops_before_any_site_access(self) -> None:
        with (patch.object(MODULE.os, "geteuid", return_value=0),
              patch.object(sys, "argv", ["rollout", "--execute"]),
              patch.object(MODULE, "read_regular", side_effect=AssertionError("site access attempted"))):
            with self.assertRaisesRegex(MODULE.GuardError, "approved additions file is required"):
                MODULE.main()

    def test_exact_six_preserves_owner(self) -> None:
        result = MODULE.validate_identities(self.old, self.additions)
        self.assertEqual(result, self.old + self.additions)

    def test_invalid_unbounded_duplicate_wildcard_and_owner_duplicate_denied(self) -> None:
        for invalid in (
            b"", self.additions + b"extra@example.test\n",
            b"owner@example.test\nb@example.test\nc@example.test\nd@example.test\ne@example.test\n",
            b"*@example.test\nb@example.test\nc@example.test\nd@example.test\ne@example.test\n",
            b"A@example.test\nb@example.test\nc@example.test\nd@example.test\ne@example.test\n",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(MODULE.GuardError):
                MODULE.validate_identities(self.old, invalid)

    def test_untrusted_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "actual").write_bytes(b"text")
            (base / "link").symlink_to(base / "actual")
            with self.assertRaises(OSError):
                MODULE.read_regular(base / "link")

    def test_unexpected_running_process_is_not_accepted(self) -> None:
        with (patch.object(MODULE, "run_systemctl", return_value=SimpleNamespace(returncode=0, stdout="123\n")),
              patch.object(MODULE.os.path, "samefile", return_value=False),
              patch.object(MODULE.http.client, "HTTPConnection", side_effect=AssertionError("unexpected probe"))):
            with self.assertRaisesRegex(MODULE.GuardError, "expected proxy binary"):
                MODULE.verify_service()

    def test_deployment_locks_must_both_exist_and_are_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "first", Path(temp) / "second"
            first.touch(mode=0o600)
            with contextlib.ExitStack() as stack, self.assertRaises(FileNotFoundError):
                MODULE.acquire_existing_deployment_locks(stack, (first, second), owner_uids=(os.geteuid(),))
            self.assertFalse(second.exists())
            second.touch(mode=0o600)
            before = (first.stat().st_ino, second.stat().st_ino)
            with contextlib.ExitStack() as stack:
                MODULE.acquire_existing_deployment_locks(stack, (first, second), owner_uids=(os.geteuid(),))
                self.assertEqual(before, (first.stat().st_ino, second.stat().st_ino))

    def test_busy_deployment_lock_aborts_without_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "first", Path(temp) / "second"
            first.touch(mode=0o600)
            second.touch(mode=0o600)
            inode = second.stat().st_ino
            with second.open("r+") as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with contextlib.ExitStack() as stack, self.assertRaises(BlockingIOError):
                    MODULE.acquire_existing_deployment_locks(stack, (first, second), owner_uids=(os.geteuid(),))
            self.assertEqual(second.stat().st_ino, inode)

    def test_deployment_lock_symlink_and_world_writable_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first, second, link = (Path(temp) / name for name in ("first", "second", "link"))
            first.touch(mode=0o600)
            second.touch(mode=0o600)
            link.symlink_to(second)
            with contextlib.ExitStack() as stack, self.assertRaises(OSError):
                MODULE.acquire_existing_deployment_locks(stack, (first, link), owner_uids=(os.geteuid(),))
            os.chmod(second, 0o666)
            with contextlib.ExitStack() as stack, self.assertRaises(MODULE.GuardError):
                MODULE.acquire_existing_deployment_locks(stack, (first, second), owner_uids=(os.geteuid(),))
            os.chmod(second, 0o600)
            with contextlib.ExitStack() as stack, self.assertRaises(MODULE.GuardError):
                MODULE.acquire_existing_deployment_locks(stack, (first, second), owner_uids=(os.geteuid() + 100000,))

    def test_missing_user_lock_is_not_created_during_read_only_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            first.touch(mode=0o600)
            user_dir = root / "user-runtime"
            user_dir.mkdir(mode=0o700)
            second = user_dir / "lock"
            with contextlib.ExitStack() as stack:
                missing = MODULE.acquire_existing_deployment_locks(
                    stack, (first, second), owner_uids=(os.geteuid(),),
                    allow_missing_user_lock=True, user_uid=os.geteuid(),
                )
                self.assertTrue(missing)
                self.assertFalse(second.exists())

    def test_missing_user_lock_is_safely_created_only_in_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            first.touch(mode=0o600)
            user_dir = root / "user-runtime"
            user_dir.mkdir(mode=0o700)
            second = user_dir / "lock"
            with contextlib.ExitStack() as stack:
                missing = MODULE.acquire_existing_deployment_locks(
                    stack, (first, second), owner_uids=(os.geteuid(),),
                    prepare_user_lock=True, user_uid=os.geteuid(),
                )
                self.assertFalse(missing)
                self.assertEqual(second.stat().st_uid, os.geteuid())
                self.assertEqual(second.stat().st_mode & 0o777, 0o600)

    def test_missing_user_lock_requires_private_owned_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            first.touch(mode=0o600)
            user_dir = root / "unsafe-runtime"
            user_dir.mkdir(mode=0o755)
            os.chmod(user_dir, 0o755)
            with contextlib.ExitStack() as stack, self.assertRaises(MODULE.GuardError):
                MODULE.acquire_existing_deployment_locks(
                    stack, (first, user_dir / "lock"), owner_uids=(os.geteuid(),),
                    prepare_user_lock=True, user_uid=os.geteuid(),
                )
            self.assertFalse((user_dir / "lock").exists())

    def test_missing_user_lock_does_not_use_wrong_runtime_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            first.touch(mode=0o600)
            user_dir = root / "user-runtime"
            user_dir.mkdir(mode=0o700)
            with contextlib.ExitStack() as stack, self.assertRaises(MODULE.GuardError):
                MODULE.acquire_existing_deployment_locks(
                    stack, (first, user_dir / "lock"), owner_uids=(os.geteuid(),),
                    prepare_user_lock=True, user_uid=os.geteuid() + 100000,
                )
            self.assertFalse((user_dir / "lock").exists())

    def test_unlinked_lock_still_open_by_another_process_blocks_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proc = root / "proc"
            descriptors = proc / "123" / "fd"
            descriptors.mkdir(parents=True)
            lock = root / "gateway.lock"
            (descriptors / "7").symlink_to(str(lock) + " (deleted)")
            with self.assertRaisesRegex(MODULE.GuardError, "unlinked deployment lock"):
                MODULE.assert_no_deleted_deployment_locks((lock,), proc)

    def test_other_open_files_do_not_trigger_deleted_lock_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            descriptors = root / "proc" / "123" / "fd"
            descriptors.mkdir(parents=True)
            (descriptors / "7").symlink_to("/tmp/unrelated (deleted)")
            MODULE.assert_no_deleted_deployment_locks((root / "gateway.lock",), root / "proc")

    def test_rollout_and_restore_on_post_restart_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            launcher, allowlist = Path(temp) / "launcher", Path(temp) / "allowlist"
            launcher.write_bytes(b"old launcher")
            allowlist.write_bytes(self.old)
            calls = []

            def restart() -> None:
                calls.append((launcher.read_bytes(), allowlist.read_bytes()))
                if len(calls) == 1:
                    raise MODULE.GuardError("synthetic startup failure")

            with self.assertRaisesRegex(MODULE.GuardError, "previous files and gateway restored"):
                MODULE.transact(launcher, allowlist, b"new launcher", self.old + self.additions,
                                b"old launcher", self.old, restart)
            self.assertEqual(calls, [(b"new launcher", self.old + self.additions), (b"old launcher", self.old)])
            self.assertEqual(launcher.read_bytes(), b"old launcher")
            self.assertEqual(allowlist.read_bytes(), self.old)
            self.assertEqual(os.stat(allowlist).st_mode & 0o777, 0o600)

    def test_successful_transaction_checks_exact_files_before_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            launcher, allowlist = Path(temp) / "launcher", Path(temp) / "allowlist"
            launcher.write_bytes(b"old")
            allowlist.write_bytes(self.old)
            observations = []
            MODULE.transact(
                launcher, allowlist, b"new", self.old + self.additions,
                b"old", self.old, lambda: observations.append((launcher.read_bytes(), allowlist.read_bytes())),
            )
            self.assertEqual(observations, [(b"new", self.old + self.additions)])

    def test_second_file_failure_restores_both_before_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            launcher, allowlist = Path(temp) / "launcher", Path(temp) / "allowlist"
            launcher.write_bytes(b"old")
            allowlist.write_bytes(self.old)
            real_write, writes, restarts = MODULE.atomic_write, [], []

            def write(path, data, mode):
                writes.append(path)
                if len(writes) == 2:
                    raise OSError("synthetic write failure")
                return real_write(path, data, mode)

            with patch.object(MODULE, "atomic_write", side_effect=write):
                with self.assertRaises(MODULE.GuardError):
                    MODULE.transact(launcher, allowlist, b"new", self.old + self.additions,
                                    b"old", self.old, lambda: restarts.append(True))
            self.assertEqual(writes, [launcher, allowlist, allowlist, launcher])
            self.assertEqual(launcher.read_bytes(), b"old")
            self.assertEqual(allowlist.read_bytes(), self.old)
            self.assertEqual(restarts, [True])

    def test_failed_rollback_is_never_reported_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            launcher, allowlist = Path(temp) / "launcher", Path(temp) / "allowlist"
            launcher.write_bytes(b"old")
            allowlist.write_bytes(self.old)
            with self.assertRaisesRegex(MODULE.GuardError, "automatic rollback failed"):
                MODULE.transact(launcher, allowlist, b"new", self.old + self.additions,
                                b"old", self.old, lambda: (_ for _ in ()).throw(OSError()))

    def test_crash_recovery_from_each_intermediate_file_pair(self) -> None:
        previous, candidate = b"original launcher", b"candidate launcher"
        old_sha, new_sha = hashlib.sha256(previous).hexdigest(), hashlib.sha256(candidate).hexdigest()
        proposed = self.old + self.additions
        for active_launcher, active_list in ((previous, self.old), (candidate, self.old), (candidate, proposed), (previous, proposed)):
            with self.subTest(active_launcher=active_launcher, active_list=active_list), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                backup = root / "backup"
                backup.mkdir(mode=0o700)
                launcher, allowlist = root / "launcher", root / "allowlist"
                launcher.write_bytes(active_launcher)
                allowlist.write_bytes(active_list)
                MODULE.save_backup(backup, previous, self.old, proposed)
                restarted = []
                MODULE.recover_from_backup(launcher, allowlist, backup, old_sha, new_sha, lambda: restarted.append(True))
                self.assertEqual((launcher.read_bytes(), allowlist.read_bytes()), (previous, self.old))
                self.assertEqual(restarted, [True])

    def test_crash_recovery_refuses_unrelated_changes_without_mutation(self) -> None:
        previous, candidate = b"original launcher", b"candidate launcher"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup = root / "backup"
            backup.mkdir(mode=0o700)
            launcher, allowlist = root / "launcher", root / "allowlist"
            launcher.write_bytes(b"unrelated launcher")
            allowlist.write_bytes(self.old)
            MODULE.save_backup(backup, previous, self.old, self.old + self.additions)
            with self.assertRaises(MODULE.GuardError):
                MODULE.recover_from_backup(
                    launcher, allowlist, backup, hashlib.sha256(previous).hexdigest(),
                    hashlib.sha256(candidate).hexdigest(), lambda: self.fail("unexpected restart"),
                )
            self.assertEqual(launcher.read_bytes(), b"unrelated launcher")
            self.assertEqual(allowlist.read_bytes(), self.old)

    def test_interrupted_update_can_be_recovered_from_saved_private_backup(self) -> None:
        previous, candidate = b"original launcher", b"candidate launcher"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private"
            private.mkdir(mode=0o700)
            launcher, allowlist = root / "launcher", root / "allowlist"
            launcher.write_bytes(previous)
            allowlist.write_bytes(self.old)
            backup = MODULE.protected_backup(private, previous, self.old, self.old + self.additions)
            with self.assertRaises(KeyboardInterrupt):
                MODULE.transact(
                    launcher, allowlist, candidate, self.old + self.additions, previous, self.old,
                    lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
                )
            self.assertEqual((launcher.read_bytes(), allowlist.read_bytes()), (candidate, self.old + self.additions))
            restarts = []
            MODULE.recover_from_backup(
                launcher, allowlist, backup, hashlib.sha256(previous).hexdigest(),
                hashlib.sha256(candidate).hexdigest(), lambda: restarts.append(True),
            )
            self.assertEqual((launcher.read_bytes(), allowlist.read_bytes()), (previous, self.old))
            self.assertEqual(restarts, [True])

    def test_existing_backup_files_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            backup = Path(temp) / "backup"
            backup.mkdir(mode=0o700)
            (backup / "launcher").write_bytes(b"preserve")
            with self.assertRaises(MODULE.GuardError):
                MODULE.save_backup(backup, b"new", self.old, self.old + self.additions)
            self.assertEqual((backup / "launcher").read_bytes(), b"preserve")

    def test_protected_backup_is_private_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "private"
            parent.mkdir(mode=0o700)
            backup = MODULE.protected_backup(parent, b"original", self.old, self.old + self.additions)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            for name in ("launcher", "allowlist", "proposed-list"):
                self.assertEqual((backup / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual((backup / "launcher").read_bytes(), b"original")

    def test_backup_refuses_world_readable_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "unsafe"
            parent.mkdir(mode=0o755)
            os.chmod(parent, 0o755)
            with self.assertRaises(MODULE.GuardError):
                MODULE.protected_backup(parent, b"original", self.old, self.old + self.additions)
            self.assertEqual(list(parent.iterdir()), [])

    def test_full_fixture_activation_saves_backup_before_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup_parent = root / "private"
            backup_parent.mkdir(mode=0o700)
            launcher, allowlist = root / "launcher", root / "allowlist"
            launcher.write_bytes(b"old")
            allowlist.write_bytes(self.old)
            launcher.chmod(0o755)
            allowlist.chmod(0o600)
            restarted = []
            backup = MODULE.activate_with_backup(
                launcher, allowlist, backup_parent, b"new", self.old + self.additions,
                b"old", self.old, lambda: restarted.append(True),
            )
            self.assertEqual((backup / "launcher").read_bytes(), b"old")
            self.assertEqual((backup / "allowlist").read_bytes(), self.old)
            self.assertEqual((launcher.read_bytes(), allowlist.read_bytes()), (b"new", self.old + self.additions))
            self.assertEqual(restarted, [True])

    def test_file_change_after_backup_aborts_without_restart_or_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backup_parent = root / "private"
            backup_parent.mkdir(mode=0o700)
            launcher, allowlist = root / "launcher", root / "allowlist"
            launcher.write_bytes(b"old")
            allowlist.write_bytes(self.old)
            launcher.chmod(0o755)
            allowlist.chmod(0o600)
            save = MODULE.protected_backup

            def mutate_after_backup(*args):
                backup = save(*args)
                launcher.write_bytes(b"other update")
                return backup

            with patch.object(MODULE, "protected_backup", side_effect=mutate_after_backup):
                with self.assertRaisesRegex(MODULE.GuardError, "site files changed"):
                    MODULE.activate_with_backup(
                        launcher, allowlist, backup_parent, b"new", self.old + self.additions,
                        b"old", self.old, lambda: self.fail("unexpected restart"),
                    )
            self.assertEqual(launcher.read_bytes(), b"other update")
            self.assertEqual(allowlist.read_bytes(), self.old)


if __name__ == "__main__":
    unittest.main()
