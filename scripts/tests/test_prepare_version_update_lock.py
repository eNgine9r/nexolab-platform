from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "prepare-version-update-lock.py"


class SharedUpdateLockTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("shared_update_lock", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "versions"
        self.root.mkdir(mode=0o750)
        self.uid, self.gid = os.geteuid(), os.getegid()

    def prepare(self, **kwargs):
        return self.module.prepare(self.root, state_uid=self.uid, state_gid=self.gid, **kwargs)

    def test_bootstrap_creates_API_accessible_lock(self):
        self.prepare()
        lock = self.root / "update-plane.lock"
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o640)
        self.assertEqual(lock.read_bytes(), b"")
        with lock.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_existing_root_first_lock_retains_inode_and_bytes(self):
        lock = self.root / "update-plane.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        before = lock.stat()
        result = self.prepare(existing_only=True)
        after = lock.stat()
        self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
        self.assertEqual(result["after"]["mode"], "0640")
        self.prepare(existing_only=True)
        self.assertEqual(after.st_ino, lock.stat().st_ino)

    def test_busy_lock_is_unchanged_and_still_serializes_API(self):
        lock = self.root / "update-plane.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
        before = lock.stat()
        with lock.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "active"):
                self.prepare(existing_only=True)
        after = lock.stat()
        self.assertEqual((before.st_ino, before.st_mode), (after.st_ino, after.st_mode))

    def test_symlink_hardlink_and_nonempty_lock_refused(self):
        lock = self.root / "update-plane.lock"
        outside = self.root.parent / "outside"
        outside.write_bytes(b"keep")
        lock.symlink_to(outside)
        with self.assertRaises((OSError, RuntimeError)):
            self.prepare(existing_only=True)
        lock.unlink()
        os.link(outside, lock)
        with self.assertRaisesRegex(RuntimeError, "regular|hardlink"):
            self.prepare(existing_only=True)
        lock.unlink()
        lock.write_bytes(b"not a lock")
        with self.assertRaisesRegex(RuntimeError, "empty"):
            self.prepare(existing_only=True)
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertEqual(lock.read_bytes(), b"not a lock")

    def test_repair_requires_existing_lock_and_exact_current_operation(self):
        with self.assertRaises(FileNotFoundError):
            self.prepare(existing_only=True)
        current = {"bundle_id": "current-package", "last_operation_id": "actual-rollback", "deployment_authority": "validated_package", "health": "ready", "runtime_state_known": True}
        (self.root / "current.json").write_text(json.dumps(current))
        (self.root / "worker.lock").touch()
        (self.root / "queue.lock").touch()
        (self.root / "update-plane.lock").touch(mode=0o600)
        with self.assertRaisesRegex(RuntimeError, "current authority"):
            self.prepare(existing_only=True, expected_bundle="current-package", expected_operation="stale")
        self.prepare(existing_only=True, expected_bundle="current-package", expected_operation="actual-rollback")

    def test_busy_native_worker_and_queued_request_refused(self):
        (self.root / "update-plane.lock").touch(mode=0o600)
        worker = self.root / "worker.lock"
        worker.touch()
        with worker.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "active"):
                self.prepare(existing_only=True)
        (self.root / "requests").mkdir()
        (self.root / "requests" / "queued.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "queued"):
            self.prepare(existing_only=True)

    def test_wrong_directory_owner_or_writable_parent_refused(self):
        with self.assertRaisesRegex(RuntimeError, "state ownership"):
            self.module.prepare(self.root, state_uid=self.uid + 1, state_gid=self.gid)
        self.root.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, "state ownership"):
            self.prepare()
        self.assertFalse((self.root / "update-plane.lock").exists())

    def test_busy_native_API_queue_preserves_lock(self):
        lock = self.root / "update-plane.lock"
        lock.touch(mode=0o600)
        queue = self.root / "queue.lock"
        queue.touch()
        before = lock.stat()
        with queue.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "active"):
                self.prepare(existing_only=True)
        self.assertEqual(before, lock.stat())

    def test_request_arriving_before_plane_lock_is_not_missed(self):
        lock = self.root / "update-plane.lock"
        lock.touch(mode=0o600)
        requests = self.root / "update-check-requests"
        requests.mkdir()
        original = self.module.exclusive
        def arriving(descriptor):
            (requests / "arriving.json").write_text("{}")
            original(descriptor)
        with patch.object(self.module, "exclusive", side_effect=arriving):
            with self.assertRaisesRegex(RuntimeError, "queued"):
                self.prepare(existing_only=True)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_unsafe_queue_directory_and_nonregular_lock_refused(self):
        lock = self.root / "update-plane.lock"
        lock.mkdir()
        with self.assertRaises(OSError):
            self.prepare(existing_only=True)
        lock.rmdir()
        os.mkfifo(lock)
        with self.assertRaisesRegex(RuntimeError, "regular"):
            self.prepare(existing_only=True)
        lock.unlink()
        lock.touch(mode=0o600)
        (self.root / "requests").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            self.prepare(existing_only=True)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_independent_processes_serialize_both_directions(self):
        self.prepare()
        lock = self.root / "update-plane.lock"
        code = "import fcntl,sys; f=open(sys.argv[1],'a+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        with lock.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(lock)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BlockingIOError", result.stderr)
        held_code = code + "; print('held',flush=True); sys.stdin.readline()"
        with subprocess.Popen([sys.executable, "-I", "-B", "-c", held_code, str(lock)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
            try:
                self.assertEqual(child.stdout.readline().strip(), "held")
                with self.assertRaisesRegex(RuntimeError, "active"):
                    self.prepare(existing_only=True)
            finally:
                child.communicate("release\n", timeout=10)

    def test_bootstrap_helper_is_shipped_in_offline_bundle(self):
        builder = SCRIPT.with_name("build-offline-bundle.sh").read_text()
        bootstrap = SCRIPT.with_name("deploy-version-manager-service.sh").read_text()
        self.assertIn('cp scripts/prepare-version-update-lock.py "$STAGING/scripts/"', builder)
        self.assertLess(bootstrap.index('--root /var/lib/nexolab/version-management'), bootstrap.index('install -m 0755 "$SOURCE_ROOT/scripts/nexolab-version-manager.py"'))

    def test_independent_UID_root_first_reproduction_and_repair(self):
        if os.geteuid() != 0:
            self.skipTest("real independent UID proof requires Root")
        try:
            os.chown(self.root, 10001, 10001)
        except OSError:
            self.skipTest("UID10001 is not mapped in this test namespace; owner-host proof required")
        self.root.parent.chmod(0o755)
        lock = self.root / "update-plane.lock"
        lock.touch(mode=0o644)
        code = "import fcntl; from pathlib import Path; f=Path(__import__('sys').argv[1]).open('a+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        def demote():
            os.setgroups([])
            os.setgid(10001)
            os.setuid(10001)
        def run():
            return subprocess.run([sys.executable, "-I", "-B", "-c", code, str(lock)], preexec_fn=demote, capture_output=True, text=True, timeout=10)
        self.assertIn("PermissionError", run().stderr)
        self.module.prepare(self.root, existing_only=True)
        self.assertEqual(run().returncode, 0)
        with lock.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("BlockingIOError", run().stderr)


if __name__ == "__main__":
    unittest.main()
