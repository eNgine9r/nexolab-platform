from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "raspberry-pi-frontend-release.sh"
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


class RaspberryPiFrontendReleaseTests(unittest.TestCase):
    def test_scripts_parse(self) -> None:
        for path in (HELPER, DEPLOY):
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
    def test_resource_preflight_fails_closed_on_memory_or_swap_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "resource.txt"
            command = (
                f"source {HELPER}; "
                f"nexolab_frontend_resource_preflight {report}"
            )
            passed = run_bash(
                command,
                env={
                    "NEXOLAB_FRONTEND_MEM_AVAILABLE_KIB_OVERRIDE": "2000000",
                    "NEXOLAB_FRONTEND_SWAP_FREE_KIB_OVERRIDE": "1500000",
                },
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertIn("status=PASS", report.read_text())

            failed = run_bash(
                command,
                env={
                    "NEXOLAB_FRONTEND_MEM_AVAILABLE_KIB_OVERRIDE": "1000000",
                    "NEXOLAB_FRONTEND_SWAP_FREE_KIB_OVERRIDE": "1500000",
                },
            )
            self.assertEqual(failed.returncode, 75)
            self.assertIn("status=FAIL", report.read_text())

    def test_competing_build_guard_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "competing.txt"
            command = f"source {HELPER}; nexolab_frontend_assert_no_competing_builds {report}"
            result = run_bash(
                command,
                env={"NEXOLAB_FRONTEND_PROCESS_SNAPSHOT": "123 npm run build"},
            )
            self.assertEqual(result.returncode, 75)
            self.assertIn("status=FAIL", report.read_text())
            self.assertIn("npm run build", report.read_text())
    def test_public_contract_rejects_dynamic_or_wrong_build_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            release = Path(temp) / "release"
            chunk = release / ".next" / "static" / "chunks" / "app.js"
            chunk.parent.mkdir(parents=True)
            (release / ".next" / "BUILD_ID").write_text("build-1\n", encoding="utf-8")
            values = [
                "live",
                "http://172.18.48.34:8082",
                "ws://172.18.48.34:8082/api/v1/telemetry/live",
                "local",
                "00000000-0000-0000-0000-000000000001",
            ]
            chunk.write_text("\n".join(repr(value) for value in values), encoding="utf-8")
            report = Path(temp) / "contract.txt"
            args = " ".join(subprocess.list2cmdline([value]) for value in values)
            command = f"source {HELPER}; nexolab_frontend_verify_public_contract {release} {args} {report}"
            good = run_bash(command)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertIn("status=PASS", report.read_text())

            chunk.write_text(
                chunk.read_text() + "\nprocess.env.NEXT_PUBLIC_NEXOLAB_DATA_MODE\n",
                encoding="utf-8",
            )
            bad = run_bash(command)
            self.assertEqual(bad.returncode, 70)
            content = report.read_text()
            self.assertIn("status=FAIL", content)
            self.assertIn("dynamic_public_env_ref=NEXT_PUBLIC_NEXOLAB_DATA_MODE", content)
    def test_bounded_build_contract_uses_cgroup_limits_and_non_root_host_identity(self) -> None:
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn('--memory "${memory_mb}m"', text)
        self.assertIn('--memory-swap "${memory_mb}m"', text)
        self.assertIn('--cpus "$cpus"', text)
        self.assertIn('--pids-limit 512', text)
        self.assertIn('--user "$uid:$gid"', text)
        self.assertIn('docker run --rm --init', text)
        self.assertNotIn('--privileged', text)
        self.assertNotIn('/var/run/docker.sock', text)

    def test_deploy_never_builds_frontend_in_active_repository(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        resource_gate = text.index('log "Checking frontend deployment resource headroom"')
        device_build = text.index('log "Building current Device Agent image"')
        candidate_build = text.index('log "Building frontend candidate inside a bounded container"')
        backend_start = text.index('log "Starting central backend, MinIO and observability"')
        activation = text.index('log "Activating verified frontend release"')
        self.assertLess(resource_gate, device_build)
        self.assertLess(device_build, candidate_build)
        self.assertLess(candidate_build, backend_start)
        self.assertLess(backend_start, activation)
        self.assertNotIn('\nnpm ci\n', text)
        self.assertNotIn('NEXT_TELEMETRY_DISABLED=1 npm run build', text)
        self.assertIn('WorkingDirectory=$FRONTEND_RELEASE_DIR', text)
        self.assertIn('rollback_dashboard_release', text)
        self.assertIn('nexolab_frontend_verify_public_contract', text)

    def test_unactivated_release_cleanup_is_path_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "releases"
            good = root / ("a" * 40 + "-20260820T120000Z")
            good.mkdir(parents=True)
            command = f"source {HELPER}; nexolab_frontend_discard_unactivated_release {root} {good}"
            result = run_bash(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(good.exists())

            outside = Path(temp) / ("b" * 40 + "-20260820T120001Z")
            outside.mkdir()
            result = run_bash(
                f"source {HELPER}; nexolab_frontend_discard_unactivated_release {root} {outside}"
            )
            self.assertEqual(result.returncode, 70)
            self.assertTrue(outside.exists())



if __name__ == "__main__":
    unittest.main()
