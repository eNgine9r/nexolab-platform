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
import importlib.util
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "raspberry-pi-frontend-release.sh"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "frontend-release-artifact.yml"
ARTIFACT_BUILDER = ROOT / "scripts" / "build-frontend-release-artifact.sh"
DASHBOARD_DOCKERFILE = ROOT / "infrastructure" / "offline" / "Dockerfile.dashboard"


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


class PrivilegedFrontendOwnerTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location(
            "privileged_partial_launch", ROOT / "scripts/privileged_partial_launch.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_root_caller_preserves_both_installed_nonroot_service_accounts(self):
        module = self.module()
        import pwd
        owner = pwd.getpwnam("nobody")
        import grp
        group = grp.getgrgid(owner.pw_gid).gr_name
        def show(unit, field):
            return {"User": owner.pw_name, "Group": group,
                    "DynamicUser": "no", "DropInPaths": ""}[field]
        with patch.object(module, "show", side_effect=show):
            self.assertEqual(module.service_identity(owner), (owner.pw_name, group))
            with patch.object(module, "show", return_value="root"):
                with self.assertRaises(ValueError):
                    module.service_identity(owner)

    def test_new_private_release_becomes_readable_without_broadening_modes(self):
        if os.geteuid() != 0 and os.environ.get("GITHUB_ACTIONS") == "true":
            result = subprocess.run(["sudo", "-n", sys.executable, "-m", "unittest",
                "scripts.tests.test_raspberry_pi_frontend_release.PrivilegedFrontendOwnerTests."
                "test_new_private_release_becomes_readable_without_broadening_modes"],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("skipped=", result.stderr)
            return
        if os.geteuid() != 0 or not any(int(row.split()[2]) > 65534 for row in Path("/proc/self/uid_map").read_text().splitlines()):
            self.skipTest("real ownership test requires root with mapped non-root UIDs")
        module = self.module()
        import pwd
        owner = pwd.getpwnam("nobody")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o755)
            releases = root / "runtime/frontend-releases"
            releases.mkdir(parents=True)
            releases.parent.chmod(0o755)
            releases.chmod(0o755)
            candidate = releases / ("a" * 40 + "-20261010T000000Z")
            candidate.mkdir(mode=0o700)
            identity = candidate / ".nexolab-runtime-identity.json"
            identity.write_text("identity")
            identity.chmod(0o600)
            outside = root / "old-evidence"
            outside.write_text("private")
            outside.chmod(0o600)
            (candidate / "escape").symlink_to(outside)
            with self.assertRaises(ValueError):
                module.own_new_release(root, candidate, owner, "a" * 40, "20261010T000000Z")
            self.assertEqual(outside.stat().st_uid, 0)
            (candidate / "escape").unlink()
            module.own_new_release(root, candidate, owner, "a" * 40, "20261010T000000Z")
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
            read = subprocess.run(["runuser", "-u", "nobody", "--", "cat", str(identity)],
                                  capture_output=True, text=True)
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(read.stdout, "identity")
            self.assertEqual(outside.stat().st_uid, 0)

    def test_git_shim_uses_owner_and_rejects_unreviewed_writes(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "calls"
            runner = root / "runuser"
            runner.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n')
            runner.chmod(0o700)
            shim = root / "git"
            shim.write_text(module.git_shim(root, "nobody", "a" * 40, "b" * 40,
                                            runuser=str(runner)))
            shim.chmod(0o700)
            env = {**os.environ, "CALL_LOG": str(log)}
            for args in (("fetch", "--prune", "origin", "main"),
                         ("switch", "--detach", "b" * 40),
                         ("merge", "--ff-only", "a" * 40)):
                self.assertEqual(subprocess.run([str(shim), *args], env=env).returncode, 0)
            for args in (("pull", "--ff-only", "origin", "main"),
                         ("reset", "--hard"), ("switch", "--detach", "c" * 40),
                         ("-C", "/other", "status")):
                self.assertNotEqual(subprocess.run([str(shim), *args], env=env).returncode, 0)
            self.assertIn("--user nobody -- /usr/bin/git --no-optional-locks -C", log.read_text())

    def test_candidate_handoff_changes_only_new_tree_ownership(self):
        module = self.module()
        import pwd
        owner = pwd.getpwnam("nobody")
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for directory in ("frontend-releases", "external-frontend-releases"):
                release = repo / "runtime" / directory / ("a" * 40 + "-20261010T000000Z")
                release.mkdir(parents=True, mode=0o700)
                private = release / ".env.local"
                private.write_text("private")
                private.chmod(0o600)
                with patch.object(module.os, "chown") as chown, patch.object(module.subprocess, "run") as probe:
                    module.own_new_release(repo, release, owner, "a" * 40, "20261010T000000Z")
                    self.assertEqual([call.args[0] for call in chown.call_args_list], [private, release])
                    self.assertTrue(all(call.kwargs == {"follow_symlinks": False} for call in chown.call_args_list))
                    self.assertEqual(probe.call_args.args[0][2], "nobody")
                    self.assertEqual(private.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(ValueError):
                    module.own_new_release(repo, release, owner, "b" * 40, "20261010T000000Z")

    def launcher(self):
        spec = importlib.util.spec_from_file_location(
            "owner_continuation", ROOT / "scripts/nexolab-partial-continuation-1327.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_launcher_keeps_existing_lock_inode_and_refuses_busy_or_replaced_lock(self):
        module = self.launcher()
        created, name = tempfile.mkstemp(prefix="nexolab-lock-regression-", dir="/tmp")
        os.close(created)
        lock = Path(name)
        moved = lock.with_name(lock.name + "-preserved")
        try:
            fd, before = module.acquire_existing_lock(lock, os.getuid())
            try:
                module.verify_locked_inode(lock, fd, before)
                with self.assertRaises(BlockingIOError):
                    module.acquire_existing_lock(lock, os.getuid())
                lock.rename(moved)
                lock.touch(mode=0o600)
                with self.assertRaises(ValueError):
                    module.verify_locked_inode(lock, fd, before)
                self.assertEqual(moved.stat().st_ino, before['inode'])
            finally:
                os.close(fd)
        finally:
            lock.unlink(missing_ok=True)
            moved.unlink(missing_ok=True)

    @unittest.skipUnless(os.geteuid() == 0, "root caller regression")
    def test_root_full_partial_handoff_without_owner_fails_before_host_actions(self):
        result = run_bash(f"bash {DEPLOY} --runtime-mode lan "
                          f"--source-ref {'a' * 40} --expected-deployed-source {'b' * 40} "
                          f"--expected-control-source {'c' * 40} "
                          "--continue-partial-activation /missing --runtime-check-report /missing "
                          f"--runtime-check-sha256 {'d' * 64} --verified-agent-recovery-report /missing")
        self.assertEqual(result.returncode, 64)
        self.assertIn("requires --preserve-service-owner", result.stderr)

    def test_launcher_binds_full_deployer_and_requires_genuine_final_state(self):
        module = self.launcher()
        command = module.command("a" * 40, Path("/lan"), Path("/protected"))
        self.assertIn("--preserve-service-owner", command)
        self.assertNotIn("--source-selection-check-only", command)
        self.assertIn(module.CAPTURE_SHA, command)
        with tempfile.TemporaryDirectory() as temp, patch.object(module, "REPO", Path(temp)):
            audit = Path(temp) / "runtime/deployments/20261010T000000Z"
            audit.mkdir(parents=True)
            values = {'commit': module.TARGET, 'control_origin_main': 'a' * 40,
                      'frontend_build_id': module.ARTIFACTS['lan']['build_id'],
                      'external_frontend_source_commit': module.TARGET,
                      'external_frontend_build_id': module.ARTIFACTS['protected']['build_id'],
                      'external_frontend_origin': module.ORIGIN}
            final = audit / 'final-state.txt'
            final.write_text(''.join(f'{key}={value}\n' for key, value in values.items()))
            output = f'[time] Evidence: {audit}\n[time] DEPLOYMENT PASSED\n[time] Evidence: {audit}\n'
            self.assertEqual(module.verify_success(output, 'a' * 40), audit)
            with self.assertRaises(ValueError):
                module.verify_success(output.replace('[time] DEPLOYMENT PASSED\n', ''), 'a' * 40)
            final.write_text(final.read_text().replace(module.TARGET, 'b' * 40))
            with self.assertRaises(ValueError):
                module.verify_success(output, 'a' * 40)


class RaspberryPiFrontendReleaseTests(unittest.TestCase):
    def test_profile_rejects_lan_artifact_for_protected_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "contract.txt"
            contract.write_text("runtime_mode=live\nexternal_https_stage=false\n")
            result = run_bash(
                f"source {HELPER}; nexolab_frontend_verify_profile {contract} true"
            )
            self.assertEqual(result.returncode, 70)

    def test_profile_requires_explicit_boolean_and_accepts_legacy_lan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contract = Path(temp) / "contract.txt"
            contract.write_text("runtime_mode=live\n")
            result = run_bash(f"source {HELPER}; nexolab_frontend_verify_profile {contract} false")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_bash(f"source {HELPER}; nexolab_frontend_verify_profile {contract} true")
            self.assertEqual(result.returncode, 70)
            contract.write_text("external_https_stage=true\nexternal_https_stage=false\n")
            result = run_bash(f"source {HELPER}; nexolab_frontend_verify_profile {contract} true")
            self.assertEqual(result.returncode, 70)

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
        self.assertIn(
            'Environment=NEXOLAB_RUNTIME_IDENTITY_FILE=$DASHBOARD_RUNTIME_IDENTITY_FILE',
            text,
        )
        self.assertIn("write_dashboard_runtime_identity_manifest", text)
        self.assertIn("raspberry_activation", text)
        self.assertIn("raspberry_rollback", text)
        self.assertIn('echo "deployed_at=$DASHBOARD_DEPLOYED_AT"', text)
        self.assertIn('rollback_dashboard_release', text)
        self.assertIn('nexolab_frontend_verify_public_contract', text)

    def test_post_activation_readiness_failure_rolls_back_last_known_good(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        wrapper = text.index("wait_http_or_rollback()")
        rollback = text.index("rollback_dashboard_release", wrapper)
        failure = text.index("post-activation readiness failed for $label; last-known-good dashboard restored", wrapper)
        self.assertLess(wrapper, rollback)
        self.assertLess(rollback, failure)
        for label in ("telemetry", "device-agent", "dashboard"):
            self.assertIn(f"wait_http_or_rollback {label}", text)
        self.assertNotIn('wait_http telemetry "$NEXOLAB_API_BASE_URL/health/ready"', text)
        self.assertNotIn('wait_http device-agent "http://127.0.0.1:8081/health"', text)

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
        self.assertIn('ALLOW_LOCAL_FRONTEND_BUILD="0"', text)
        self.assertIn("--allow-local-frontend-build", text)
        self.assertIn(
            "production deployment requires --frontend-artifact; use --allow-local-frontend-build only for an explicit emergency fallback",
            text,
        )
        self.assertNotIn("docker curl python3 openssl npm node flock", text)
        self.assertIn("docker curl python3 openssl node flock", text)
        self.assertIn('NVM_NODE_BIN="$HOME/.nvm/versions/node/v${EXPECTED_NODE_VERSION}/bin"', text)
        self.assertIn('export PATH="$NVM_NODE_BIN:$PATH"', text)
        self.assertIn('ACTUAL_NODE_VERSION="$(node --version', text)

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
        self.assertIn("runs-on: ubuntu-24.04-arm", ci)
        self.assertIn("runs-on: ubuntu-24.04-arm", release)
        self.assertNotIn("Setup QEMU", ci)
        self.assertNotIn("Setup QEMU", release)
        self.assertIn("ARM64", builder)
        self.assertIn('docker create --platform "$PLATFORM" "$IMAGE"', builder)
        self.assertIn('--build-arg "NEXOLAB_SOURCE_COMMIT=$SOURCE_SHA"', builder)
        dashboard_dockerfile = DASHBOARD_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("cp package-lock.json /tmp/nexolab-package-lock.json", dashboard_dockerfile)
        self.assertIn("npm prune --omit=dev", dashboard_dockerfile)
        self.assertIn("mv /tmp/nexolab-package-lock.json package-lock.json", dashboard_dockerfile)
        self.assertIn("ARG NEXOLAB_SOURCE_COMMIT", dashboard_dockerfile)
        self.assertIn(".nexolab-runtime-identity.json", dashboard_dockerfile)
        offline_builder = (ROOT / "scripts" / "build-offline-bundle.sh").read_text(encoding="utf-8")
        self.assertIn('--build-arg "NEXOLAB_SOURCE_COMMIT=${SOURCE_COMMIT}"', offline_builder)

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
