"""Verify pinned CI installer failure paths without downloading or executing payloads."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install-ci-trivy.sh"


def run_installer(tmp_path: Path, curl_body: str, uname_body: str | None = None):
    commands = tmp_path / "commands"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text("#!/bin/bash\n" + curl_body)
    curl.chmod(0o755)
    if uname_body is not None:
        uname = commands / "uname"
        uname.write_text("#!/bin/bash\n" + uname_body)
        uname.chmod(0o755)
    destination = tmp_path / "installed"
    result = subprocess.run(
        ["bash", str(INSTALLER), str(destination)],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result, destination


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_download_failure_does_not_install(self):
        result, destination = run_installer(self.root, "exit 6\n")
        self.assertEqual(result.returncode, 6)
        self.assertFalse(destination.exists())

    def test_tampered_archive_is_rejected_before_extraction(self):
        result, destination = run_installer(
            self.root,
            'while [[ $# -gt 0 ]]; do if [[ $1 == --output ]]; then shift; printf tampered > "$1"; exit; fi; shift; done\n',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("tar:", result.stderr)
        self.assertFalse(destination.exists())

    def test_unsupported_platform_never_downloads(self):
        result, destination = run_installer(
            self.root, "echo download-must-not-run >&2; exit 99\n", "echo unsupported\n"
        )
        self.assertEqual(result.returncode, 64)
        self.assertNotIn("download-must-not-run", result.stderr)
        self.assertFalse(destination.exists())

    def test_all_scans_use_installed_pinned_scanner_without_policy_changes(self):
        workflow = (ROOT / ".github/workflows/container-supply-chain.yml").read_text()
        self.assertEqual(workflow.count('skip-setup-trivy: "true"'), 3)
        self.assertEqual(workflow.count("version: v0.70.0"), 3)
        self.assertEqual(
            workflow.count(
                "uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"
            ),
            3,
        )
        self.assertIn(
            'bash scripts/install-ci-trivy.sh "$RUNNER_TEMP/nexolab-trivy-bin"',
            workflow,
        )
        self.assertIn("scripts/evaluate-container-vulnerabilities.py", workflow)
        self.assertIn("ignore-unfixed: false", workflow)
