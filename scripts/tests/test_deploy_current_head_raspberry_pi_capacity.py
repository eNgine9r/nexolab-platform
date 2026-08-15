from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "deploy-capacity-guard.sh"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"


def run_bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
    )


class DeploymentCapacityTests(unittest.TestCase):
    def test_shell_scripts_parse(self) -> None:
        for path in (HELPER, DEPLOY):
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_capacity_sufficient_and_insufficient_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            audit = repo / "runtime" / "deployments" / "20260815T210000Z"
            audit.mkdir(parents=True)
            report = audit / "capacity-preflight.txt"
            common_env = {
                "NEXOLAB_DEPLOY_MIN_FREE_RESERVE_BYTES": "100",
                "NEXOLAB_DEPLOY_BUILD_HEADROOM_BYTES": "200",
                "NEXOLAB_DEPLOY_METADATA_HEADROOM_BYTES": "300",
                "NEXOLAB_DEPLOY_ARCHIVE_FIXED_OVERHEAD_BYTES": "0",
                "NEXOLAB_DEPLOY_POSTGRES_FIXED_OVERHEAD_BYTES": "0",
            }
            quoted_helper = subprocess.list2cmdline([str(HELPER)])
            quoted_repo = subprocess.list2cmdline([str(repo)])
            quoted_audit = subprocess.list2cmdline([str(audit)])
            quoted_report = subprocess.list2cmdline([str(report)])

            sufficient = run_bash(
                f'''source {quoted_helper}\n'''
                '''nexolab_capacity_free_bytes() { printf '1000\\n'; }\n'''
                f'''nexolab_capacity_preflight {quoted_repo} {quoted_audit} '' {quoted_report}\n''',
                env=common_env,
            )
            self.assertEqual(sufficient.returncode, 0, sufficient.stderr)
            content = report.read_text(encoding="utf-8")
            self.assertIn("status=PASS", content)
            self.assertIn("required_bytes=600", content)
            self.assertIn("required_bytes_is_complete=true", content)

            insufficient = run_bash(
                f'''source {quoted_helper}\n'''
                '''nexolab_capacity_free_bytes() { printf '599\\n'; }\n'''
                f'''nexolab_capacity_preflight {quoted_repo} {quoted_audit} '' {quoted_report}\n''',
                env=common_env,
            )
            self.assertEqual(insufficient.returncode, 75)
            content = report.read_text(encoding="utf-8")
            self.assertIn("status=FAIL", content)
            self.assertIn("free_bytes=599", content)
            self.assertIn("required_bytes=600", content)
            self.assertIn("reserve_bytes=100", content)
            self.assertIn("insufficient deployment capacity", insufficient.stderr)

    def test_retention_preserves_current_newest_marker_and_product_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            deployments = repo / "runtime" / "deployments"
            product_evidence = repo / "runtime" / "evidence"
            product_evidence.mkdir(parents=True)
            (product_evidence / "must-survive.txt").write_text("protected", encoding="utf-8")

            stamps = [f"2026010{day}T000000Z" for day in range(1, 7)]
            dirs: list[Path] = []
            old = time.time() - 40 * 86400
            for stamp in stamps:
                path = deployments / stamp
                path.mkdir(parents=True)
                (path / "payload.bin").write_bytes(b"x" * 1024)
                os.utime(path, (old, old))
                dirs.append(path)
            (dirs[1] / ".nexolab-preserve").write_text("acceptance evidence\n", encoding="utf-8")
            current = dirs[-1]

            result = run_bash(
                f'''source {subprocess.list2cmdline([str(HELPER)])}\n'''
                f'''nexolab_prune_deployment_evidence {subprocess.list2cmdline([str(deployments)])} {subprocess.list2cmdline([str(current)])}\n''',
                env={
                    "NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT": "2",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT": "6",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS": "30",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES": "99999999",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(dirs[0].exists())
            self.assertTrue(dirs[1].exists(), "explicitly preserved acceptance evidence must survive")
            self.assertFalse(dirs[2].exists())
            self.assertFalse(dirs[3].exists())
            self.assertTrue(dirs[4].exists(), "newest protected deployment must survive")
            self.assertTrue(current.exists(), "current deployment must survive")
            self.assertEqual((product_evidence / "must-survive.txt").read_text(), "protected")

    def test_count_retention_is_deterministic_oldest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deployments = Path(temp) / "deployments"
            dirs: list[Path] = []
            for day in range(1, 7):
                path = deployments / f"2026080{day}T000000Z"
                path.mkdir(parents=True)
                (path / "payload.bin").write_bytes(bytes([day]) * 128)
                dirs.append(path)
            current = dirs[-1]

            result = run_bash(
                f'''source {subprocess.list2cmdline([str(HELPER)])}\n'''
                f'''nexolab_prune_deployment_evidence {subprocess.list2cmdline([str(deployments)])} {subprocess.list2cmdline([str(current)])}\n''',
                env={
                    "NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT": "2",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT": "3",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS": "0",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES": "0",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            remaining = sorted(path.name for path in deployments.iterdir() if path.is_dir())
            self.assertEqual(remaining, [dirs[3].name, dirs[4].name, dirs[5].name])

    def test_postgres_measurement_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            audit = repo / "runtime" / "deployments" / "20260815T220000Z"
            audit.mkdir(parents=True)
            report = audit / "capacity-preflight.txt"
            result = run_bash(
                f'''source {subprocess.list2cmdline([str(HELPER)])}\n'''
                '''docker() { return 1; }\n'''
                '''nexolab_capacity_free_bytes() { printf '1000000\\n'; }\n'''
                f'''if nexolab_capacity_preflight {subprocess.list2cmdline([str(repo)])} {subprocess.list2cmdline([str(audit)])} fake-postgres {subprocess.list2cmdline([str(report)])}; then exit 99; else rc=$?; fi\n'''
                '''printf 'rc=%s\\n' "$rc"\n''',
                env={
                    "NEXOLAB_DEPLOY_MIN_FREE_RESERVE_BYTES": "100",
                    "NEXOLAB_DEPLOY_BUILD_HEADROOM_BYTES": "200",
                    "NEXOLAB_DEPLOY_METADATA_HEADROOM_BYTES": "300",
                    "NEXOLAB_DEPLOY_ARCHIVE_FIXED_OVERHEAD_BYTES": "0",
                    "NEXOLAB_DEPLOY_POSTGRES_FIXED_OVERHEAD_BYTES": "0",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("rc=70", result.stdout)
            content = report.read_text(encoding="utf-8")
            self.assertIn("status=FAIL", content)
            self.assertIn("postgresql_estimate_source=unavailable", content)
            self.assertIn("required_bytes_is_complete=false", content)
            self.assertIn("error=postgresql-size-unavailable", content)

    def test_retention_fails_closed_when_classified_directory_cannot_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            deployments = Path(temp) / "deployments"
            old_dir = deployments / "20260101T000000Z"
            current = deployments / "20260815T220001Z"
            old_dir.mkdir(parents=True)
            current.mkdir(parents=True)
            result = run_bash(
                f'''source {subprocess.list2cmdline([str(HELPER)])}\n'''
                '''rm() { return 1; }\n'''
                f'''nexolab_prune_deployment_evidence {subprocess.list2cmdline([str(deployments)])} {subprocess.list2cmdline([str(current)])}\n''',
                env={
                    "NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT": "1",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT": "1",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS": "0",
                    "NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES": "0",
                },
            )
            self.assertEqual(result.returncode, 70)
            self.assertTrue(old_dir.exists())
            self.assertIn("failed to prune classified deployment evidence", result.stderr)

    def test_deployment_orders_capacity_gate_before_mutation_and_uses_atomic_large_files(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        first_gate = text.index('log "Running deployment capacity preflight before evidence capture"')
        inventory = text.index("echo '=== host ==='")
        fetch = text.index('git fetch --prune origin main')
        build = text.index('docker build --pull -t nexolab-device-agent:local')
        recreate = text.index('up -d --force-recreate mqtt device-agent')
        self.assertLess(first_gate, inventory)
        self.assertLess(first_gate, fetch)
        self.assertLess(first_gate, build)
        self.assertLess(first_gate, recreate)
        self.assertGreaterEqual(text.count("nexolab_capacity_preflight"), 2)
        self.assertIn(".runtime-evidence.tar.gz.partial", text)
        self.assertIn(".postgresql-pre-upgrade.dump.partial", text)
        self.assertNotIn("docker volume rm", text)
        self.assertNotIn("docker compose down -v", text)


if __name__ == "__main__":
    unittest.main()
