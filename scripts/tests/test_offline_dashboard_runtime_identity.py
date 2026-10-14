from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


DOCKERFILE = Path(__file__).resolve().parents[2] / "infrastructure/offline/Dockerfile.dashboard"
SOURCE_COMMIT = "a" * 40
BUILD_ID = "offline-dashboard-identity-1377"


class OfflineDashboardRuntimeIdentityTests(unittest.TestCase):
    def generator_script(self) -> str:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        matches = re.findall(r"\bnode -e ('[^'\r\n]+')", dockerfile)
        self.assertEqual(len(matches), 1, "expected one shell-quoted identity generator")
        command = shlex.split("node -e " + matches[0])
        self.assertEqual(command[:2], ["node", "-e"])
        self.assertEqual(len(command), 3)
        return command[2]

    def test_generator_uses_real_newline_not_literal_backslash_n(self) -> None:
        script = self.generator_script()
        self.assertIn("JSON.stringify(", script)
        self.assertIn("String.fromCharCode(10)", script)
        self.assertNotIn('+"\\\\n"', script)
        self.assertIn(".nexolab-runtime-identity.json", script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the Dockerfile generator")
    def test_generator_emits_parseable_json_bound_to_source_and_build(self) -> None:
        script = self.generator_script()
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            (cwd / ".next").mkdir()
            (cwd / ".next/BUILD_ID").write_text(BUILD_ID + "\n", encoding="utf-8")
            env = {**os.environ, "NEXOLAB_SOURCE_COMMIT": SOURCE_COMMIT}
            result = subprocess.run(
                ["node", "-e", script],
                cwd=cwd, env=env, text=True, capture_output=True, timeout=15, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = (cwd / ".nexolab-runtime-identity.json").read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertFalse(raw.endswith(b"\\n"))
            self.assertEqual(raw.count(b"\n"), 1)
            identity = json.loads(raw)
            self.assertEqual(identity, {
                "schema_version": "nexolab-runtime-identity-v1",
                "service": "dashboard",
                "source_commit": SOURCE_COMMIT,
                "build_id": BUILD_ID,
                "deployed_at": None,
                "identity_source": "offline_image_manifest",
            })

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to execute the Dockerfile generator")
    def test_generator_rejects_invalid_source_without_writing_identity(self) -> None:
        script = self.generator_script()
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            (cwd / ".next").mkdir()
            (cwd / ".next/BUILD_ID").write_text(BUILD_ID, encoding="utf-8")
            env = {**os.environ, "NEXOLAB_SOURCE_COMMIT": "not-a-commit"}
            result = subprocess.run(
                ["node", "-e", script],
                cwd=cwd, env=env, text=True, capture_output=True, timeout=15, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((cwd / ".nexolab-runtime-identity.json").exists())


if __name__ == "__main__":
    unittest.main()
