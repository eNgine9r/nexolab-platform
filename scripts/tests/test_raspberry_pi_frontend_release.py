from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "raspberry-pi-frontend-release.sh"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "frontend-release-artifact.yml"


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
        resource_gate = text.index('log "Checking frontend deployment resource headroom for bounded local build fallback"')
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

    def test_verified_off_device_artifact_imports_without_frontend_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            artifact = root / "artifact"
            release = root / "release"
            fake_bin = root / "bin"
            for path in (repo, artifact, release, fake_bin):
                path.mkdir(parents=True)

            package = {"name": "fixture", "version": "1.0.0", "dependencies": {"next": "1.0.0"}}
            package_lock = {
                "name": "fixture",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "fixture", "version": "1.0.0", "dependencies": {"next": "1.0.0"}},
                    "node_modules/next": {
                        "version": "1.0.0",
                        "resolved": "https://example.invalid/next.tgz",
                        "integrity": "sha512-fixture",
                    },
                },
            }
            hidden_lock = {"lockfileVersion": 3, "packages": {"node_modules/next": package_lock["packages"]["node_modules/next"]}}
            for base in (repo, artifact, release):
                (base / "package.json").write_text(json.dumps(package), encoding="utf-8")
                (base / "package-lock.json").write_text(json.dumps(package_lock), encoding="utf-8")

            (repo / "node_modules" / ".bin").mkdir(parents=True)
            (repo / "node_modules" / ".package-lock.json").write_text(json.dumps(hidden_lock), encoding="utf-8")
            next_bin = repo / "node_modules" / ".bin" / "next"
            next_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            next_bin.chmod(0o755)

            values = {
                "runtime_mode": "live",
                "api_base_url": "http://172.18.48.34:8082",
                "websocket_url": "ws://172.18.48.34:8082/api/v1/telemetry/live",
                "auth_provider": "local",
                "organization_id": "00000000-0000-0000-0000-000000000001",
            }
            chunk = artifact / ".next" / "static" / "chunks" / "app.js"
            chunk.parent.mkdir(parents=True)
            (artifact / ".next" / "BUILD_ID").write_text("fixture-build\n", encoding="utf-8")
            chunk.write_text("\n".join(repr(value) for value in values.values()), encoding="utf-8")
            commit = "a" * 40
            (artifact / "frontend-source-sha.txt").write_text(commit + "\n", encoding="utf-8")
            package_lines = []
            for name in ("package.json", "package-lock.json"):
                digest = hashlib.sha256((artifact / name).read_bytes()).hexdigest()
                package_lines.append(f"{digest}  {name}")
            (artifact / "frontend-package-sha256.txt").write_text("\n".join(package_lines) + "\n", encoding="utf-8")
            (artifact / "frontend-runtime-contract.txt").write_text(
                "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
                encoding="utf-8",
            )
            manifest_targets = [
                *sorted(path for path in (artifact / ".next").rglob("*") if path.is_file()),
                artifact / "package.json",
                artifact / "package-lock.json",
                artifact / "frontend-source-sha.txt",
                artifact / "frontend-package-sha256.txt",
                artifact / "frontend-runtime-contract.txt",
            ]
            manifest = []
            for path in manifest_targets:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest.append(f"{digest}  {path.relative_to(artifact)}")
            (artifact / "frontend-artifact-sha256.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

            npm = fake_bin / "npm"
            npm.write_text("#!/bin/sh\nprintf '{}\\n'\nexit 0\n", encoding="utf-8")
            npm.chmod(0o755)
            report = root / "import.txt"
            args = [
                artifact,
                repo,
                release,
                commit,
                *values.values(),
                report,
            ]
            command = "source {} ; nexolab_frontend_import_artifact {}".format(
                shlex.quote(str(HELPER)),
                " ".join(shlex.quote(str(value)) for value in args),
            )
            result = run_bash(command, env={"PATH": f"{fake_bin}:{os.environ['PATH']}"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=PASS", report.read_text())
            self.assertIn("preparation=off-device-artifact", report.read_text())
            self.assertEqual((release / ".next" / "BUILD_ID").read_text(), "fixture-build\n")
            self.assertTrue((release / "node_modules" / ".bin" / "next").exists())
            self.assertTrue((report.parent / f"{report.name}.public-contract").exists())

            tampered_release = root / "release-tampered"
            tampered_release.mkdir()
            for name in ("package.json", "package-lock.json"):
                (tampered_release / name).write_bytes((artifact / name).read_bytes())
            chunk.write_text(chunk.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
            tampered_report = root / "tampered-import.txt"
            tampered_args = [
                artifact,
                repo,
                tampered_release,
                commit,
                *values.values(),
                tampered_report,
            ]
            tampered_command = "source {} ; nexolab_frontend_import_artifact {}".format(
                shlex.quote(str(HELPER)),
                " ".join(shlex.quote(str(value)) for value in tampered_args),
            )
            tampered = run_bash(
                tampered_command,
                env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )
            self.assertEqual(tampered.returncode, 70)
            self.assertIn("error=artifact-checksum-mismatch", tampered_report.read_text())
            self.assertFalse((tampered_release / ".next").exists())

    def test_off_device_artifact_checksum_tamper_fails_closed(self) -> None:
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn("sha256sum --check frontend-artifact-sha256.txt", text)
        self.assertIn("error=artifact-checksum-mismatch", text)
        self.assertIn("error=source-sha-mismatch", text)
        self.assertIn("error=runtime-contract-mismatch", text)
        self.assertIn("error=runtime-dependency-snapshot-mismatch", text)

    def test_deploy_routes_explicit_artifact_around_local_frontend_build(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        artifact_import = text.index('log "Importing verified off-device frontend artifact"')
        local_build = text.index('log "Building frontend candidate inside a bounded container"')
        self.assertLess(artifact_import, local_build)
        self.assertIn("--frontend-artifact", text)
        self.assertIn("nexolab_frontend_import_artifact", text)
        self.assertIn("status=SKIPPED_OFF_DEVICE_ARTIFACT", text)
        self.assertIn('if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then', text)

    def test_ci_and_release_workflows_publish_integrity_bound_frontend_artifacts(self) -> None:
        ci = CI_WORKFLOW.read_text(encoding="utf-8")
        release = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        for text in (ci, release):
            self.assertIn("frontend-source-sha.txt", text)
            self.assertIn("frontend-package-sha256.txt", text)
            self.assertIn("frontend-runtime-contract.txt", text)
            self.assertIn("frontend-artifact-sha256.txt", text)
            self.assertIn("find .next -type f -print0 | sort -z | xargs -0 sha256sum", text)
            self.assertIn("include-hidden-files: true", text)
        self.assertIn("nexolab-frontend-recovery-${{ github.event.pull_request.head.sha }}", ci)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", ci)
        self.assertIn("fetch-depth: 0", ci)
        self.assertIn('git diff --quiet "${{ github.event.pull_request.base.sha }}"', ci)
        self.assertIn("Reject native binaries in portable recovery .next artifact", ci)
        self.assertIn("Reject native binaries in portable .next artifact", release)

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
