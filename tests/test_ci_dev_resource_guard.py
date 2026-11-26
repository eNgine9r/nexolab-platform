"""#1794: development-session memory guard (fake cgroup v2 tree, fake tmpfs dirs)."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "dev-resource-guard.py"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("dev_resource_guard", TOOL)
guard = importlib.util.module_from_spec(spec)
sys.modules["dev_resource_guard"] = guard
spec.loader.exec_module(guard)
MIB = 1024 * 1024


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "cgroup"
        self.slice = self.root / "user.slice" / "user-1001.slice"
        self.service = self.slice / "nexolab-dev-session.service"
        self.service.mkdir(parents=True)
        (self.root / "user.slice" / "memory.max").write_text("max\n")
        self.limits(self.slice, high=768, current=700, swap_max=512, swap=500, high_events=2276852)
        self.limits(self.service, high=1152, current=690, swap_max=512, swap=500, high_events=10)
        self.proc = Path(self.temp.name) / "cgroup-self"
        self.proc.write_text("0::/user.slice/user-1001.slice/nexolab-dev-session.service\n")
        self.tmp = Path(self.temp.name) / "tmpfs"
        self.tmp.mkdir()

    @staticmethod
    def limits(path: Path, *, high: int, current: int, swap_max: int, swap: int, high_events: int) -> None:
        (path / "memory.high").write_text(f"{high * MIB}\n")
        (path / "memory.max").write_text(f"{1280 * MIB}\n")
        (path / "memory.current").write_text(f"{current * MIB}\n")
        (path / "memory.swap.max").write_text(f"{swap_max * MIB}\n")
        (path / "memory.swap.current").write_text(f"{swap * MIB}\n")
        (path / "memory.events").write_text(f"low 0\nhigh {high_events}\nmax 0\noom 0\noom_kill 0\n")

    def report(self) -> dict:
        return guard.report(self.root, self.proc, (str(self.tmp),))

    def test_tightest_level_of_the_hierarchy_decides(self) -> None:
        data = self.report()
        self.assertEqual(data["cgroup"], "/user.slice/user-1001.slice")  # 68 MiB room beats the service's 462 MiB
        self.assertEqual(data["headroom_mib"], 68)
        self.assertEqual(data["swap_free_mib"], 12)
        self.assertEqual(data["events"]["high"], 2276852)

    def test_refuses_on_swap_quota_headroom_and_tmpfs(self) -> None:
        big = self.tmp / "tsvenv" / "lib.so"
        big.parent.mkdir()
        with open(big, "wb") as handle:  # allocated blocks count, written in chunks (never one big buffer)
            for _ in range(200):
                handle.write(b"x" * MIB)
        data = self.report()
        reasons = guard.verdict(data, need_mib=256, min_swap_free_mib=128, max_tmpfs_mib=150)
        self.assertEqual([r.split()[0] for r in reasons], ["HEADROOM", "SWAP_QUOTA", "TMPFS_OWNED"])
        self.assertEqual(data["tmpfs_largest"][0]["path"], str(big))

    def test_ok_after_the_tmpfs_offload(self) -> None:
        self.limits(self.slice, high=768, current=500, swap_max=512, swap=80, high_events=2276852)
        data = self.report()
        self.assertEqual(guard.verdict(data, need_mib=256, min_swap_free_mib=128, max_tmpfs_mib=150), [])

    def test_symlinks_are_not_followed(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        with open(outside / "big", "wb") as handle:
            for _ in range(50):
                handle.write(b"x" * MIB)
        (self.tmp / "link").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.report()["tmpfs_owned_mib"], 0)

    def test_cli_exit_codes(self) -> None:
        base = [sys.executable, "-I", "-B", str(TOOL), "check", "--cgroup-root", str(self.root),
                "--proc-cgroup", str(self.proc), "--tmpfs-dir", str(self.tmp)]
        refused = subprocess.run(base, capture_output=True, text=True, timeout=60)
        self.assertEqual(refused.returncode, 75, refused.stdout + refused.stderr)
        self.assertIn("RESOURCE_GUARD_REFUSED", refused.stdout)
        self.limits(self.slice, high=768, current=400, swap_max=512, swap=50, high_events=0)
        ok = subprocess.run(base, capture_output=True, text=True, timeout=60)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("RESOURCE_GUARD_OK", ok.stdout)

    def test_read_only(self) -> None:
        code = TOOL.read_text().split('"""', 2)[2]
        for forbidden in ("write_text", "write_bytes", "unlink", "rmtree", "remove(", "subprocess", "open(", "chmod"):
            self.assertNotIn(forbidden, code, forbidden)


if __name__ == "__main__":
    unittest.main()
