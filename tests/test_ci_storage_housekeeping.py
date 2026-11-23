"""Tests for NEXOLAB storage housekeeping and the disk guard (#1710, #1551)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "docs" / "operations" / "storage"
SPEC = importlib.util.spec_from_file_location("nexolab_storage_housekeeping", STORAGE / "nexolab-storage-housekeeping.py")
assert SPEC and SPEC.loader
HK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HK
SPEC.loader.exec_module(HK)

SHA = "a" * 40
NOW = time.time()


def _release(root: Path, day: int, *, age_days: float) -> Path:
    path = root / f"{SHA[:-2]}{day:02d}-202611{day:02d}T000000Z"
    (path / "node_modules").mkdir(parents=True)
    (path / "node_modules" / "blob").write_bytes(b"x" * 8192)
    stamp = NOW - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "frontend-releases"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_keeps_newest_and_young_and_prunes_only_old_superseded(self) -> None:
        releases = {day: _release(self.root, day, age_days=40 - day) for day in range(1, 9)}
        (self.root / "not-a-release").mkdir()
        actions, kept = HK.plan_releases(HK.Config(release_roots=(str(self.root),)), now=NOW, unit_text="", process_paths=set())
        targets = {action.target for action in actions}
        # newest three (days 8, 7, 6) kept; days 1..5 are 35..39 days old -> pruned
        self.assertEqual(targets, {str(releases[day]) for day in range(1, 6)})
        self.assertTrue(all(action.bytes > 0 for action in actions))
        self.assertTrue(all(action.command[:3] == ["rm", "-rf", "--one-file-system"] for action in actions))
        self.assertNotIn(str(self.root / "not-a-release"), targets)
        reasons = {item["target"]: item["reason"] for item in kept}
        self.assertIn("newest", reasons[str(releases[8])])

    def test_systemd_reference_process_use_protected_list_and_age_protect(self) -> None:
        releases = {day: _release(self.root, day, age_days=60 - day) for day in range(1, 9)}
        releases[9] = _release(self.root, 9, age_days=2)
        young = _release(self.root, 10, age_days=1)
        old_young = self.root / f"{SHA[:-2]}00-20261100T000000Z"
        (old_young).mkdir()
        unit_text = f"WorkingDirectory={releases[1]}\n"
        actions, kept = HK.plan_releases(
            HK.Config(release_roots=(str(self.root),), protected_paths=(str(releases[3]),)),
            now=NOW,
            unit_text=unit_text,
            process_paths={str(releases[2] / "node_modules")},
        )
        reasons = {item["target"]: item["reason"] for item in kept}
        self.assertEqual(reasons[str(releases[1])], "referenced by a systemd unit")
        self.assertEqual(reasons[str(releases[2])], "in use by a running process")
        self.assertEqual(reasons[str(releases[3])], "listed as protected")
        self.assertIn("newest", reasons[str(young)])
        targets = {action.target for action in actions}
        self.assertFalse({str(releases[1]), str(releases[2]), str(releases[3]), str(young)} & targets)
        self.assertIn(str(releases[4]), targets)

    def test_symlinked_release_and_symlinked_root_are_never_removed(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        for day in range(1, 5):
            _release(self.root, day, age_days=50)
        link = self.root / f"{SHA[:-2]}00-20250101T000000Z"
        link.symlink_to(outside)
        actions, kept = HK.plan_releases(HK.Config(release_roots=(str(self.root),)), now=NOW, unit_text="", process_paths=set())
        self.assertNotIn(str(link), {action.target for action in actions})
        self.assertIn({"target": str(link), "reason": "symlink or not a directory"}, kept)
        root_link = Path(self.tmp.name) / "root-link"
        root_link.symlink_to(self.root)
        actions, kept = HK.plan_releases(HK.Config(release_roots=(str(root_link),)), now=NOW, unit_text="", process_paths=set())
        self.assertEqual(actions, [])


class FakeDocker:
    def __init__(self, images: dict[str, tuple[int, int]], used: set[str]) -> None:
        self.images = images
        self.used = used
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        out = ""
        if command[:3] == ["docker", "ps", "-aq"]:
            out = "c1\nc2\n"
        elif command[:2] == ["docker", "inspect"]:
            out = "\n".join(sorted(self.used))
        elif command[:2] == ["docker", "images"]:
            out = "\n".join(self.images)
        elif command[:3] == ["docker", "image", "inspect"]:
            age_days, size = self.images[command[-1]]
            created = (datetime(2026, 11, 23, tzinfo=UTC) - timedelta(days=age_days)).isoformat()
            out = f"{created}|{size}"
        elif command[:1] == ["pgrep"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, out, "")


def _image(n: int) -> str:
    return "sha256:" + f"{n:064x}"


class DockerTests(unittest.TestCase):
    def test_only_old_unused_unprotected_dangling_images(self) -> None:
        images = {_image(1): (30, 100), _image(2): (30, 200), _image(3): (30, 300), _image(4): (2, 400)}
        fake = FakeDocker(images, used={_image(2)})
        actions, kept = HK.plan_docker(
            HK.Config(protected_images=(_image(3),)), fake, now=datetime(2026, 11, 23, tzinfo=UTC)
        )
        kinds = {(action.kind, action.target) for action in actions}
        self.assertIn(("dangling_image", _image(1)), kinds)
        self.assertFalse({_image(2), _image(3), _image(4)} & {action.target for action in actions})
        reasons = {item["target"]: item["reason"] for item in kept}
        self.assertEqual(reasons[_image(2)], "used by a container")
        self.assertEqual(reasons[_image(3)], "listed as protected")
        self.assertIn("younger", reasons[_image(4)])
        build = [action for action in actions if action.kind == "docker_build_cache"][0]
        self.assertEqual(build.command, ["docker", "builder", "prune", "--force", "--filter", "until=168h"])
        for action in actions:
            self.assertNotIn("-f", action.command[3:] if action.kind == "dangling_image" else [])
            self.assertNotIn("volume", action.command)
            self.assertNotIn("system", action.command)


class GuardAndModeTests(unittest.TestCase):
    def test_guard_levels(self) -> None:
        self.assertEqual(HK.disk_state(HK.Config(warn_gib=0, critical_gib=0))["level"], "ok")
        self.assertEqual(HK.disk_state(HK.Config(warn_gib=10**9, critical_gib=0))["level"], "warning")
        self.assertEqual(HK.disk_state(HK.Config(warn_gib=10**9, critical_gib=10**9))["level"], "critical")

    def test_report_mode_executes_nothing_and_apply_executes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "releases"
            root.mkdir()
            for day in range(1, 6):
                _release(root, day, age_days=60)
            env = {
                "STORAGE_RELEASE_ROOTS": str(root),
                "STATE_DIRECTORY": str(Path(tmp) / "state"),
                "STORAGE_WARN_GIB": "0",
                "STORAGE_CRITICAL_GIB": "0",
            }
            old_env = dict(os.environ)
            try:
                os.environ.update(env)
                fake = FakeDocker({}, set())
                self.assertEqual(HK.main([], run=fake), 0)
                executed = [c for c in fake.calls if c[0] in {"rm", "apt-get"} or c[:2] == ["docker", "builder"]]
                self.assertEqual(executed, [], "report mode must not execute any action")
                self.assertEqual(len(list(root.iterdir())), 5)
                os.environ["STORAGE_HOUSEKEEPING_MODE"] = "apply"
                fake = FakeDocker({}, set())
                HK.main([], run=fake)
                removed = [c for c in fake.calls if c[0] == "rm"]
                self.assertEqual(len(removed), 2, "only releases beyond the newest three")
                self.assertTrue((Path(tmp) / "state" / "housekeeping.json").is_file())
            finally:
                os.environ.clear()
                os.environ.update(old_env)

    def test_guard_only_exit_code_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_env = dict(os.environ)
            try:
                os.environ.update({"STATE_DIRECTORY": tmp, "STORAGE_WARN_GIB": "1e9", "STORAGE_CRITICAL_GIB": "1e9"})
                self.assertEqual(HK.main(["--guard-only"], run=FakeDocker({}, set())), 2)
                self.assertTrue((Path(tmp) / "guard.json").is_file())
            finally:
                os.environ.clear()
                os.environ.update(old_env)

    def test_units_keep_limits_and_report_default(self) -> None:
        guard = (STORAGE / "nexolab-storage-guard.service").read_text(encoding="utf-8")
        self.assertIn("--guard-only", guard)
        self.assertIn("ProtectSystem=strict", guard)
        housekeeping = (STORAGE / "nexolab-storage-housekeeping.service").read_text(encoding="utf-8")
        for setting in ("IOSchedulingClass=idle", "MemoryMax=256M", "NoNewPrivileges=yes"):
            self.assertIn(setting, housekeeping)
        env = (STORAGE / "housekeeping.env.example").read_text(encoding="utf-8")
        self.assertIn("STORAGE_HOUSEKEEPING_MODE=report", env)
        self.assertIn("STORAGE_WARN_GIB=40", env)
        self.assertIn("STORAGE_CRITICAL_GIB=20", env)
        source = (STORAGE / "nexolab-storage-housekeeping.py").read_text(encoding="utf-8")
        for forbidden in ("volume prune", "system prune", "compose down", "VACUUM", "DELETE FROM"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
