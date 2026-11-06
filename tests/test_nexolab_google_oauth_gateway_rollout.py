"""Synthetic tests only; never touch a real gateway or service."""
from __future__ import annotations

import importlib.util
import hashlib
import os
import sys
import tempfile
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

    def test_activation_is_disabled_before_any_site_access(self) -> None:
        with (patch.object(MODULE.os, "geteuid", return_value=0),
              patch.object(sys, "argv", ["rollout", "--additions-file", "/missing", "--execute"]),
              patch.object(MODULE, "read_regular", side_effect=AssertionError("site access attempted"))):
            with self.assertRaisesRegex(MODULE.GuardError, "activation disabled"):
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

    def test_existing_backup_files_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            backup = Path(temp) / "backup"
            backup.mkdir(mode=0o700)
            (backup / "launcher").write_bytes(b"preserve")
            with self.assertRaises(MODULE.GuardError):
                MODULE.save_backup(backup, b"new", self.old, self.old + self.additions)
            self.assertEqual((backup / "launcher").read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
