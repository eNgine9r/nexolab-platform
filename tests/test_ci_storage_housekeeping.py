"""Tests for NEXOLAB storage housekeeping and the disk guard (#1710, #1551)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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


def _image(n: int) -> str:
    return "sha256:" + hashlib.sha256(str(n).encode()).hexdigest()


class FakeDocker:
    def __init__(self, images: dict[str, tuple[int, int]] | None = None, used: dict[str, list[str]] | None = None,
                 fail: set[str] | None = None) -> None:
        self.images = images or {}
        self.used = used or {}  # container image -> mount sources
        self.fail = fail or set()
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        key = " ".join(command[:2])
        if key in self.fail:
            return subprocess.CompletedProcess(command, 1, "", "denied")
        out = ""
        if command[:2] == ["docker", "ps"]:
            out = "\n".join(f"c{i}" for i in range(len(self.used)))
        elif command[:2] == ["docker", "inspect"]:
            out = "\n".join(f"{image}|{';'.join(mounts)};" for image, mounts in self.used.items())
        elif command[:2] == ["docker", "images"]:
            out = "\n".join(self.images)
        elif command[:3] == ["docker", "image", "inspect"]:
            age_days, size = self.images[command[-1]]
            created = (datetime(2026, 11, 23, tzinfo=UTC) - timedelta(days=age_days)).isoformat()
            out = f"{created}|{size}"
        elif command[:1] == ["pgrep"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, out, "")


def _config(**overrides: object) -> object:
    values: dict[str, object] = dict(protected_images=(_image(999),), protected_paths=("/nonexistent/protected",))
    values.update(overrides)
    return HK.Config(**values)


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "frontend-releases"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def plan(self, **kwargs: object) -> tuple[list, list]:
        config = kwargs.pop("config", _config(release_roots=(str(self.root),)))
        defaults = dict(now=NOW, unit_text="", process_paths=set(), mount_sources=set(), references={})
        defaults.update(kwargs)
        return HK.plan_releases(config, **defaults)

    def test_keeps_newest_and_prunes_only_old_superseded(self) -> None:
        releases = {day: _release(self.root, day, age_days=40 - day) for day in range(1, 9)}
        (self.root / "not-a-release").mkdir()
        actions, kept = self.plan()
        self.assertEqual({a.target for a in actions}, {str(releases[d]) for d in range(1, 6)})
        self.assertTrue(all(a.command[:3] == ["rm", "-rf", "--one-file-system"] for a in actions))
        self.assertIn("newest", {k["target"]: k["reason"] for k in kept}[str(releases[8])])

    def test_every_protection_reason(self) -> None:
        releases = {day: _release(self.root, day, age_days=60 - day) for day in range(1, 10)}
        references = {releases[5].name: ["/runtime/deployments/20261101T000000Z/rollback.json"]}
        actions, kept = self.plan(
            config=_config(release_roots=(str(self.root),), protected_paths=(str(releases[3]),)),
            unit_text=f"WorkingDirectory={releases[1]}\n",
            process_paths={str(releases[2] / "node_modules")},
            mount_sources={str(releases[4] / "public")},
            references=references,
        )
        reasons = {k["target"]: k["reason"] for k in kept}
        self.assertEqual(reasons[str(releases[1])], "referenced by a systemd unit")
        self.assertEqual(reasons[str(releases[2])], "in use by a running process")
        self.assertEqual(reasons[str(releases[3])], "listed as protected")
        self.assertEqual(reasons[str(releases[4])], "bind-mounted into a container")
        self.assertIn("referenced by 1 record(s)", reasons[str(releases[5])])
        self.assertEqual({a.target for a in actions}, {str(releases[6])})

    def test_root_and_parent_paths_do_not_protect_everything(self) -> None:
        releases = {day: _release(self.root, day, age_days=60) for day in range(1, 6)}
        actions, _ = self.plan(process_paths={"/", str(self.root.parent)}, mount_sources={"/", str(self.root)})
        self.assertEqual({a.target for a in actions}, {str(releases[1]), str(releases[2])})
        actions, _ = self.plan(config=_config(release_roots=(str(self.root),), protected_paths=("/", str(self.root))))
        self.assertEqual(actions, [], "a protected parent directory protects the releases inside it")

    def test_symlinks_are_never_removed(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        for day in range(1, 5):
            _release(self.root, day, age_days=50)
        link = self.root / f"{SHA[:-2]}00-20250101T000000Z"
        link.symlink_to(outside)
        actions, kept = self.plan()
        self.assertNotIn(str(link), {a.target for a in actions})
        root_link = Path(self.tmp.name) / "root-link"
        root_link.symlink_to(self.root)
        actions, _ = self.plan(config=_config(release_roots=(str(root_link),)))
        self.assertEqual(actions, [])

    def test_reference_index_finds_records_and_skips_release_roots(self) -> None:
        release = _release(self.root, 1, age_days=60)
        records = Path(self.tmp.name) / "runtime" / "deployments" / "20261101T000000Z"
        records.mkdir(parents=True)
        (records / "rollback.json").write_text(json.dumps({"rollback_release": str(release)}), encoding="utf-8")
        (self.root / "inside.json").write_text(release.name, encoding="utf-8")
        config = _config(release_roots=(str(self.root),), reference_roots=(str(Path(self.tmp.name) / "runtime"),))
        hits = HK.reference_index(config, [release.name])
        self.assertEqual(hits[release.name], [str(records / "rollback.json")])


class DockerTests(unittest.TestCase):
    def test_only_old_unused_unprotected_unreferenced_dangling_images(self) -> None:
        images = {_image(n): (30, n * 100) for n in (1, 2, 3, 5)}
        images[_image(4)] = (2, 400)
        fake = FakeDocker(images, used={_image(2): ["/srv/x"]})
        config = _config(protected_images=(_image(3),))
        in_use, _ = HK.docker_usage(fake)
        actions, kept = HK.plan_docker(
            config, fake, now=datetime(2026, 11, 23, tzinfo=UTC), in_use=in_use,
            references={_image(5)[7:19]: ["/var/backups/nexolab/manifest.json"]},
        )
        self.assertEqual({a.target for a in actions if a.kind == "dangling_image"}, {_image(1)})
        reasons = {k["target"]: k["reason"] for k in kept}
        self.assertEqual(reasons[_image(2)], "used by a container")
        self.assertEqual(reasons[_image(3)], "listed as protected")
        self.assertIn("younger", reasons[_image(4)])
        self.assertIn("referenced by 1 record(s)", reasons[_image(5)])
        for action in actions:
            self.assertFalse({"-f", "--force", "volume", "system"} & set(action.command[2:] if action.kind == "dangling_image" else []))

    def test_docker_failures_fail_closed(self) -> None:
        for failing in ("docker ps", "docker inspect"):
            with self.subTest(failing=failing):
                with self.assertRaises(HK.FailClosed):
                    HK.docker_usage(FakeDocker(used={_image(1): []}, fail={failing}))


class PlanAndManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.root = self.dir / "releases"
        self.root.mkdir()
        for day in range(1, 6):
            _release(self.root, day, age_days=60)
        (self.dir / "protected-images").write_text(_image(999) + "\n", encoding="utf-8")
        (self.dir / "protected-paths").write_text("/nonexistent/protected\n", encoding="utf-8")
        self.env = {
            "STORAGE_RELEASE_ROOTS": str(self.root),
            "STATE_DIRECTORY": str(self.dir / "state"),
            "STORAGE_WARN_GIB": "0",
            "STORAGE_CRITICAL_GIB": "0",
            "STORAGE_PROTECTED_IMAGES_FILE": str(self.dir / "protected-images"),
            "STORAGE_PROTECTED_PATHS_FILE": str(self.dir / "protected-paths"),
        }
        self.env_file = self.dir / "housekeeping.env"
        self.env_file.write_text("\n".join(f"{k}={v}" for k, v in self.env.items()) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_or_empty_protected_inventory_withholds_images_and_releases(self) -> None:
        for broken in ({"STORAGE_PROTECTED_IMAGES_FILE": str(self.dir / "absent")}, {"STORAGE_PROTECTED_PATHS_FILE": ""}):
            with self.subTest(broken=broken):
                config = HK.config_from_env({**self.env, **broken})
                self.assertFalse(config.protected_inventories_ok)
                actions, _kept, withheld = HK.plan_all(config, FakeDocker())
                self.assertEqual({a.kind for a in actions}, {"apt_cache"})
                self.assertTrue(withheld and "withheld" in withheld[0])
        (self.dir / "protected-images").write_text("# only comments\n", encoding="utf-8")
        self.assertFalse(HK.config_from_env(self.env).protected_inventories_ok)

    def test_docker_failure_withholds_images_and_releases(self) -> None:
        config = HK.config_from_env(self.env)
        actions, _kept, withheld = HK.plan_all(config, FakeDocker(fail={"docker ps"}))
        self.assertEqual({a.kind for a in actions}, {"apt_cache"})
        self.assertIn("docker ps failed", withheld[0])

    def test_report_writes_manifest_and_executes_nothing(self) -> None:
        fake = FakeDocker()
        self.assertEqual(HK.main(["--env-file", str(self.env_file)], run=fake), 0)
        self.assertFalse([c for c in fake.calls if c[0] in {"rm", "apt-get"} or c[:2] == ["docker", "builder"]])
        report = json.loads((self.dir / "state" / "housekeeping.json").read_text(encoding="utf-8"))
        manifest_path = Path(report["manifest"]["path"])
        self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), report["manifest"]["sha256"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len([e for e in manifest["entries"] if e["kind"] == "frontend_release"]), 2)

    def test_apply_requires_exact_hash_and_runs_only_still_eligible_entries(self) -> None:
        HK.main(["--env-file", str(self.env_file)], run=FakeDocker())
        report = json.loads((self.dir / "state" / "housekeeping.json").read_text(encoding="utf-8"))
        path, digest = report["manifest"]["path"], report["manifest"]["sha256"]

        refused = FakeDocker()
        self.assertEqual(HK.main(["--env-file", str(self.env_file), "--apply-manifest", path, "--manifest-sha256", "0" * 64], run=refused), 3)
        self.assertFalse([c for c in refused.calls if c[0] == "rm"])

        # One approved release becomes protected after approval: it must be skipped.
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        release_targets = [e["target"] for e in manifest["entries"] if e["kind"] == "frontend_release"]
        (self.dir / "protected-paths").write_text(release_targets[0] + "\n", encoding="utf-8")
        applied = FakeDocker()
        HK.main(["--env-file", str(self.env_file), "--apply-manifest", path, "--manifest-sha256", digest], run=applied)
        removed = [c[-1] for c in applied.calls if c[0] == "rm"]
        self.assertEqual(removed, [release_targets[1]])
        final = json.loads((self.dir / "state" / "housekeeping.json").read_text(encoding="utf-8"))
        self.assertIn({"target": f"frontend_release:{release_targets[0]}", "reason": "no longer eligible; skipped"}, final["kept"])


class GuardAndUnitTests(unittest.TestCase):
    def test_guard_levels_and_exit_code(self) -> None:
        self.assertEqual(HK.disk_state(HK.Config(warn_gib=0, critical_gib=0))["level"], "ok")
        self.assertEqual(HK.disk_state(HK.Config(warn_gib=10**9, critical_gib=0))["level"], "warning")
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "env"
            env.write_text(f"STATE_DIRECTORY={tmp}\nSTORAGE_WARN_GIB=1e9\nSTORAGE_CRITICAL_GIB=1e9\n", encoding="utf-8")
            self.assertEqual(HK.main(["--guard-only", "--env-file", str(env)], run=FakeDocker()), 2)
            self.assertTrue((Path(tmp) / "guard.json").is_file())

    def test_units_and_defaults(self) -> None:
        guard = (STORAGE / "nexolab-storage-guard.service").read_text(encoding="utf-8")
        self.assertIn("--guard-only", guard)
        housekeeping = (STORAGE / "nexolab-storage-housekeeping.service").read_text(encoding="utf-8")
        exec_start = [line for line in housekeeping.splitlines() if line.startswith("ExecStart=")]
        self.assertEqual(len(exec_start), 1)
        self.assertNotIn("--apply-manifest", exec_start[0], "scheduled runs must never apply")
        for setting in ("IOSchedulingClass=idle", "MemoryMax=256M", "NoNewPrivileges=yes"):
            self.assertIn(setting, housekeeping)
        env = (STORAGE / "housekeeping.env.example").read_text(encoding="utf-8")
        for setting in ("STORAGE_WARN_GIB=40", "STORAGE_CRITICAL_GIB=20", "STORAGE_REFERENCE_ROOTS=", "STORAGE_PROTECTED_IMAGES_FILE="):
            self.assertIn(setting, env)
        source = (STORAGE / "nexolab-storage-housekeeping.py").read_text(encoding="utf-8")
        for forbidden in ("volume prune", "system prune", "compose down", "VACUUM", "DELETE FROM"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
