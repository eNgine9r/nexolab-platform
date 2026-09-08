#!/usr/bin/env python3
"""Regression contract for required root mountpoints in the SSD migration helper."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "migrate-raspberry-pi-root-to-ssd.sh"

EXPECTED_MODES = {
    "dev": 0o755,
    "proc": 0o555,
    "sys": 0o555,
    "run": 0o755,
    "tmp": 0o1777,
    "mnt": 0o755,
    "media": 0o755,
    "boot": 0o755,
}
VALIDATED_MODES = {**EXPECTED_MODES, "boot/firmware": 0o755}


class SsdRootMountpointContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_pseudo_runtime_contents_remain_excluded(self) -> None:
        for path in ("dev", "proc", "sys", "run", "tmp", "mnt", "media"):
            self.assertIn(f"--exclude='/{path}/***'", self.text)

    def test_root_rsync_recreates_and_validates_mountpoints(self) -> None:
        match = re.search(r"root_rsync\(\) \{(?P<body>.*?)\n\}\n\nconfigure_target_boot", self.text, re.S)
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("ensure_target_root_mountpoints", body)
        self.assertIn("validate_target_root_mountpoints", body)

    def test_mountpoint_creation_modes(self) -> None:
        match = re.search(
            r"ensure_target_root_mountpoints\(\) \{(?P<body>.*?)\n\}\n\nvalidate_target_root_mountpoints",
            self.text,
            re.S,
        )
        self.assertIsNotNone(match)
        function = "ensure_target_root_mountpoints() {" + match.group("body") + "\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["TARGET_ROOT"] = tmp
            subprocess.run(
                ["bash", "-c", function + "\nensure_target_root_mountpoints"],
                check=True,
                env=env,
            )
            for relative, expected in EXPECTED_MODES.items():
                path = Path(tmp) / relative
                self.assertTrue(path.is_dir(), relative)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected, relative)
            self.assertTrue((Path(tmp) / "boot/firmware").is_dir())

    def test_validator_requires_root_ownership(self) -> None:
        self.assertIn("[[ \"$owner\" == '0:0' ]]", self.text)
        for relative, mode in VALIDATED_MODES.items():
            self.assertIn(f"'{relative}:{mode:o}'", self.text)
        mount_target = re.search(r"mount_target\(\) \{(?P<body>.*?)\n\}", self.text, re.S)
        self.assertIsNotNone(mount_target)
        self.assertIn('chmod 0755 "$TARGET_ROOT/boot" "$TARGET_ROOT/boot/firmware"', mount_target.group("body"))


if __name__ == "__main__":
    unittest.main()
