from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "raspberry-pi-frontend-release.sh"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "frontend-release-artifact.yml"
ARTIFACT_BUILDER = ROOT / "scripts" / "build-frontend-release-artifact.sh"


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
        for path in (HELPER, DEPLOY, ARTIFACT_BUILDER):
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
            runtime = root / "runtime"
            fake_bin = root / "bin"
            for path in (repo, artifact, release, runtime, fake_bin):
                path.mkdir(parents=True)

            package = '{"name":"fixture","version":"1.0.0"}\n'
            package_lock = '{"name":"fixture","version":"1.0.0","lockfileVersion":3,"packages":{}}\n'
            for base in (artifact, release):
                (base / "package.json").write_text(package, encoding="utf-8")
                (base / "package-lock.json").write_text(package_lock, encoding="utf-8")

            node_version = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
            (release / ".nvmrc").write_text(node_version + "\n", encoding="utf-8")
            fake_node = fake_bin / "node"
            fake_node.write_text(f"#!/bin/sh\nprintf 'v{node_version}\\n'\n", encoding="utf-8")
            fake_node.chmod(0o755)
            values = {
                "runtime_mode": "live",
                "api_base_url": "http://172.18.48.34:8082",
                "websocket_url": "ws://172.18.48.34:8082/api/v1/telemetry/live",
                "auth_provider": "local",
                "organization_id": "00000000-0000-0000-0000-000000000001",
            }
            chunk = runtime / ".next" / "static" / "chunks" / "app.js"
            chunk.parent.mkdir(parents=True)
            (runtime / ".next" / "BUILD_ID").write_text("fixture-build\n", encoding="utf-8")
            chunk.write_text("\n".join(repr(value) for value in values.values()), encoding="utf-8")
            next_bin = runtime / "node_modules" / ".bin" / "next"
            next_bin.parent.mkdir(parents=True)
            next_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            next_bin.chmod(0o755)

            runtime_manifest = []
            for base_name in (".next", "node_modules"):
                for path in sorted((runtime / base_name).rglob("*")):
                    if path.is_file():
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        runtime_manifest.append(f"{digest}  {path.relative_to(runtime)}")
            (artifact / "frontend-runtime-files-sha256.txt").write_text("\n".join(runtime_manifest) + "\n", encoding="utf-8")
            with tarfile.open(artifact / "frontend-runtime.tar.gz", "w:gz") as tf:
                tf.add(runtime / ".next", arcname=".next")
                tf.add(runtime / "node_modules", arcname="node_modules")

            machine = platform.machine()
            artifact_platform = {"aarch64": "linux/arm64", "x86_64": "linux/amd64"}[machine]
            commit = "a" * 40
            metadata = {
                "frontend-source-sha.txt": commit + "\n",
                "frontend-runtime-contract.txt": "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
                "frontend-platform.txt": artifact_platform + "\n",
                "frontend-node-version.txt": node_version + "\n",
                "frontend-build-id.txt": "fixture-build\n",
                "frontend-public-contract.txt": "status=PASS\n",
                "frontend-native-files.txt": "",
            }
            for name, content in metadata.items():
                (artifact / name).write_text(content, encoding="utf-8")
            package_lines = []
            for name in ("package.json", "package-lock.json"):
                digest = hashlib.sha256((artifact / name).read_bytes()).hexdigest()
                package_lines.append(f"{digest}  {name}")
            (artifact / "frontend-package-sha256.txt").write_text("\n".join(package_lines) + "\n", encoding="utf-8")

            manifest_names = [
                "frontend-runtime.tar.gz", "package.json", "package-lock.json",
                "frontend-source-sha.txt", "frontend-package-sha256.txt",
                "frontend-runtime-contract.txt", "frontend-platform.txt",
                "frontend-node-version.txt", "frontend-build-id.txt",
                "frontend-runtime-files-sha256.txt", "frontend-public-contract.txt",
                "frontend-native-files.txt",
            ]
            manifest = []
            for name in manifest_names:
                digest = hashlib.sha256((artifact / name).read_bytes()).hexdigest()
                manifest.append(f"{digest}  {name}")
            (artifact / "frontend-artifact-sha256.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

            report = root / "import.txt"
            args = [artifact, repo, release, commit, *values.values(), report]
            command = "source {} ; nexolab_frontend_import_artifact {}".format(
                shlex.quote(str(HELPER)),
                " ".join(shlex.quote(str(value)) for value in args),
            )
            result = run_bash(command, env={"PATH": f"{fake_bin}:{os.environ['PATH']}"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=PASS", report.read_text())
            self.assertIn("preparation=off-device-self-contained-runtime", report.read_text())
            self.assertEqual((release / ".next" / "BUILD_ID").read_text(), "fixture-build\n")
            self.assertTrue((release / "node_modules" / ".bin" / "next").stat().st_mode & 0o100)
            self.assertTrue((report.parent / f"{report.name}.archive").exists())

            tampered_release = root / "release-tampered"
            tampered_release.mkdir()
            (tampered_release / ".nvmrc").write_text(node_version + "\n", encoding="utf-8")
            for name in ("package.json", "package-lock.json"):
                (tampered_release / name).write_bytes((artifact / name).read_bytes())
            payload = bytearray((artifact / "frontend-runtime.tar.gz").read_bytes())
            payload[len(payload) // 2] ^= 1
            (artifact / "frontend-runtime.tar.gz").write_bytes(payload)
            tampered_report = root / "tampered-import.txt"
            tampered_args = [artifact, repo, tampered_release, commit, *values.values(), tampered_report]
            tampered = run_bash(
                "source {} ; nexolab_frontend_import_artifact {}".format(
                    shlex.quote(str(HELPER)),
                    " ".join(shlex.quote(str(value)) for value in tampered_args),
                ),
                env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )
            self.assertEqual(tampered.returncode, 70)
            self.assertIn("error=artifact-checksum-mismatch", tampered_report.read_text())
            self.assertFalse((tampered_release / ".next").exists())

    def test_runtime_archive_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.tar.gz"
            payload = root / "payload"
            payload.write_text("bad", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as tf:
                tf.add(payload, arcname="../escape")
            report = root / "report.txt"
            result = run_bash(
                f"source {shlex.quote(str(HELPER))}; "
                f"nexolab_frontend_verify_runtime_archive {shlex.quote(str(archive))} {shlex.quote(str(report))}"
            )
            self.assertEqual(result.returncode, 70)
            self.assertIn("status=FAIL", report.read_text())
            self.assertIn("error=path:../escape", report.read_text())

    def test_off_device_artifact_checksum_tamper_fails_closed(self) -> None:
        text = HELPER.read_text(encoding="utf-8")
        self.assertIn("sha256sum --check frontend-artifact-sha256.txt", text)
        self.assertIn("error=artifact-checksum-mismatch", text)
        self.assertIn("error=source-sha-mismatch", text)
        self.assertIn("error=runtime-contract-mismatch", text)
        self.assertIn("error=artifact-platform-mismatch", text)
        self.assertIn("error=unsafe-runtime-archive", text)
        self.assertIn("error=runtime-files-checksum-mismatch", text)
        self.assertNotIn('cp -al "$repo/node_modules"', text)
        self.assertNotIn('npm --prefix "$repo" ls', text)

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
            self.assertIn("build-frontend-release-artifact.sh", text)
            self.assertIn("--platform linux/arm64", text)
            self.assertIn("include-hidden-files: true", text)
        builder = ARTIFACT_BUILDER.read_text(encoding="utf-8")
        for marker in (
            "frontend-runtime.tar.gz",
            "frontend-source-sha.txt",
            "frontend-package-sha256.txt",
            "frontend-runtime-contract.txt",
            "frontend-platform.txt",
            "frontend-node-version.txt",
            "frontend-runtime-files-sha256.txt",
            "frontend-artifact-sha256.txt",
            "Dockerfile.dashboard",
            "git status --porcelain --untracked-files=all",
            "output directory must be empty",
        ):
            self.assertIn(marker, builder)
        self.assertIn("nexolab-frontend-recovery-${{ github.event.pull_request.head.sha }}", ci)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", ci)
        self.assertIn("fetch-depth: 0", ci)
        self.assertIn('git diff --quiet "${{ github.event.pull_request.base.sha }}"', ci)
        self.assertIn("Setup QEMU", ci)
        self.assertIn("Setup QEMU", release)
        self.assertIn("ARM64", builder)

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
