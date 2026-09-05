from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, env=env, check=False, capture_output=True, text=True)


class HistoricalMainSourceSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        self.assertEqual(run("git", "init", "--bare", str(self.remote), cwd=self.root).returncode, 0)
        self.assertEqual(run("git", "clone", str(self.remote), str(self.repo), cwd=self.root).returncode, 0)
        for key, value in (("user.email", "test@nexolab.local"), ("user.name", "NEXOLAB Test")):
            self.assertEqual(run("git", "config", key, value, cwd=self.repo).returncode, 0)
        self.assertEqual(run("git", "switch", "-c", "main", cwd=self.repo).returncode, 0)
        migrations = self.repo / "services" / "telemetry-service" / "migrations" / "versions"
        migrations.mkdir(parents=True)
        (migrations / "0001_test.py").write_text(
            'revision = "test_rev"\ndown_revision = None\n', encoding="utf-8"
        )

        self.base = self._commit("base")
        self.assertEqual(run("git", "push", "-u", "origin", "main", cwd=self.repo).returncode, 0)
        self.target = self._commit("target")
        self.assertEqual(run("git", "push", "origin", "main", cwd=self.repo).returncode, 0)
        self.latest = self._commit("latest")
        self.assertEqual(run("git", "push", "origin", "main", cwd=self.repo).returncode, 0)
        self.base_evidence = self._set_deployed_evidence(self.base, "20260829T000000Z")

        self.assertEqual(run("git", "switch", "-c", "feature-only", cwd=self.repo).returncode, 0)
        self.feature = self._commit("feature")
        self.assertEqual(run("git", "switch", "main", cwd=self.repo).returncode, 0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _set_deployed_evidence(
        self,
        commit: str | None,
        stamp: str,
        *,
        passed: bool = True,
        mutated: bool = False,
        restored_source: str | None = None,
        device_agent_image_id: str | None = None,
        summary_extra: str = "",
    ) -> Path:
        evidence = self.repo / "runtime" / "deployments" / stamp
        evidence.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        if mutated:
            lines.append("RUNTIME MUTATION STARTED: central backend activation")
            (evidence / "runtime-mutation-started").write_text("started\n", encoding="utf-8")
        if summary_extra:
            lines.append(summary_extra)
        if passed:
            lines.append("DEPLOYMENT PASSED")
        (evidence / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if commit is not None:
            final_state = f"commit={commit}\n"
            if device_agent_image_id is not None:
                final_state += f"deployed_device_agent_image_id={device_agent_image_id}\n"
            (evidence / "final-state.txt").write_text(final_state, encoding="utf-8")
        if restored_source is not None:
            shared = {
                "sha256": "c" * 64,
                "bytes": 4096,
                "registry_revision": 18,
                "outbound_queue_count": 0,
                "outbound_queue_high_water": 42,
                "node_stream_sequences": {},
                "deployment_evidence_id": stamp,
                "deployed_source": restored_source,
                "deployed_device_agent_image_id": "sha256:" + "d" * 64,
                "target_source": self.target,
            }
            metadata = {
                "schema_version": 1,
                "kind": "nexolab-edge-sqlite-pre-cutover",
                "source_quick_check": "ok",
                "snapshot_quick_check": "ok",
                **shared,
            }
            restore_result = {
                "schema_version": 1,
                "kind": "nexolab-edge-sqlite-restore-result",
                "status": "restored",
                **shared,
            }
            (evidence / "edge-sqlite-pre-cutover.json").write_text(
                json.dumps(metadata) + "\n", encoding="utf-8"
            )
            (evidence / "edge-sqlite-restore-result.json").write_text(
                json.dumps(restore_result) + "\n", encoding="utf-8"
            )
        return evidence

    def _set_forward_recovery_evidence(self, stamp: str) -> Path:
        evidence = self.repo / "runtime" / "deployments" / stamp
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "summary.txt").write_text(
            "[2026-09-01T09:49:45+03:00] RUNTIME MUTATION STARTED: central backend activation\n"
            "[2026-09-01T09:50:24+03:00] ERROR: late health gate failed\n",
            encoding="utf-8",
        )
        (evidence / "runtime-mutation-started").write_text(
            f"source={self.target}\nstarted_at=2026-09-01T09:49:45+03:00\n", encoding="utf-8"
        )
        metadata = {
            "schema_version": 1, "kind": "nexolab-edge-sqlite-pre-cutover",
            "deployed_source": self.base, "target_source": self.target,
            "source_quick_check": "ok", "snapshot_quick_check": "ok",
            "outbound_queue_count": 0, "outbound_queue_high_water": 10, "registry_revision": 1,
        }
        (evidence / "edge-sqlite-pre-cutover.json").write_text(json.dumps(metadata) + "\n")
        (evidence / "frontend-artifact-import.txt").write_text(
            f"status=PASS\nsource_sha={self.target}\nplatform=linux/arm64\nbuild_id=build-1\n"
        )
        release = self.repo / "runtime" / "frontend-releases" / f"{self.target}-{stamp}"
        (evidence / "dashboard-unit-candidate.service").write_text(
            f"WorkingDirectory={release}\n"
            "Environment=NEXT_PUBLIC_NEXOLAB_DATA_MODE=live\n"
            "Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://172.18.48.66:8082\n"
            "Environment=NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://172.18.48.66:8082/api/v1/telemetry/live\n"
            "Environment=NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local\n"
            "Environment=NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=org-1\n"
        )
        volumes = [{"Name": "nexolab-central-postgres-data", "Driver": "local", "Mountpoint": "/db", "CreatedAt": "now"}]
        (evidence / "volume-identities-before.json").write_text(json.dumps(volumes) + "\n")
        files = {
            "runtime_mutation_started": "runtime-mutation-started",
            "edge_sqlite_pre_cutover": "edge-sqlite-pre-cutover.json",
            "frontend_artifact_import": "frontend-artifact-import.txt",
            "dashboard_unit_candidate": "dashboard-unit-candidate.service",
            "volume_identities_before": "volume-identities-before.json",
        }
        hashes = {k: hashlib.sha256((evidence / v).read_bytes()).hexdigest() for k, v in files.items()}
        result = {
            "schema_version": 1, "kind": "nexolab-forward-deployment-recovery-result", "status": "reconciled",
            "deployment_evidence_id": stamp, "previous_source": self.base, "target_source": self.target,
            "runtime_activated_at": "2026-09-01T09:49:45+03:00", "recovered_at": "2026-09-02T09:00:00Z",
            "control_origin_main": self.latest, "runtime_mode": "lan", "platform": "linux/arm64",
            "schema_head": "test_rev", "dashboard": "http://172.18.48.66:3000", "api": "http://172.18.48.66:8082",
            "auth_mode": "jwt", "local_auth_overlay": True, "dashboard_auth_provider": "local",
            "dashboard_organization_id": "org-1", "dashboard_release_dir": str(release), "dashboard_build_id": "build-1",
            "device_agent_container_id": "1" * 64, "device_agent_image_id": "sha256:" + "2" * 64,
            "device_agent_registry_revision": 1, "device_agent_queue_depth": 0,
            "device_agent_expected_bus_workers": 2, "device_agent_active_bus_workers": 2,
            "edge_sqlite_quick_check": "ok", "edge_sqlite_outbound_queue_count": 0, "edge_sqlite_outbound_queue_high_water": 10,
            "telemetry_service_container_id": "3" * 64, "telemetry_service_image_id": "sha256:" + "4" * 64,
            "postgres_container_id": "5" * 64, "postgres_volume_name": "nexolab-central-postgres-data",
            "evidence_hashes": hashes,
            "safety": {"runtime_mutation": "none", "edge_sqlite_write": "none", "postgres_write": "none", "modbus_write": "none", "hardware_write": "none"},
        }
        (evidence / "forward-recovery-result.json").write_text(json.dumps(result) + "\n")
        return evidence

    def _commit(self, value: str) -> str:
        (self.repo / "fixture.txt").write_text(value + "\n", encoding="utf-8")
        self.assertEqual(run("git", "add", "fixture.txt", cwd=self.repo).returncode, 0)
        migration = self.repo / "services" / "telemetry-service" / "migrations" / "versions" / "0001_test.py"
        if migration.exists():
            self.assertEqual(
                run("git", "add", str(migration.relative_to(self.repo)), cwd=self.repo).returncode, 0
            )
        self.assertEqual(run("git", "commit", "-m", value, cwd=self.repo).returncode, 0)
        result = run("git", "rev-parse", "HEAD", cwd=self.repo)
        self.assertEqual(result.returncode, 0)
        return result.stdout.strip()

    def _validate(self, source: str, deployed: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        return run(
            "bash",
            str(DEPLOY),
            "--source-ref",
            source,
            "--expected-deployed-source",
            deployed,
            "--source-selection-check-only",
            cwd=ROOT,
            env=env,
        )

    def test_valid_historical_main_lineage_passes_and_restores_main(self) -> None:
        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOURCE_SELECTION_VALIDATED", result.stdout)
        self.assertIn(f"target={self.target}", result.stdout)
        self.assertEqual(run("git", "branch", "--show-current", cwd=self.repo).stdout.strip(), "main")
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), self.latest)

    def test_malformed_source_sha_fails_closed(self) -> None:
        result = self._validate("abc", self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("full lowercase 40-character commit SHA", result.stdout + result.stderr)

    def test_feature_only_commit_fails_closed(self) -> None:
        result = self._validate(self.feature, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not contained in current main history", result.stdout + result.stderr)

    def test_downgrade_target_fails_closed(self) -> None:
        self._set_deployed_evidence(self.target, "20260829T010000Z")
        result = self._validate(self.base, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a fast-forward descendant", result.stdout + result.stderr)

    def test_dirty_starting_tree_fails_before_source_selection(self) -> None:
        (self.repo / "fixture.txt").write_text("dirty\n", encoding="utf-8")
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked local changes detected before source selection", result.stdout + result.stderr)

    def test_expected_deployed_source_must_match_authoritative_successful_evidence(self) -> None:
        result = self._validate(self.target, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the latest authoritative successful deployment evidence", result.stdout + result.stderr)

    def test_default_current_main_selection_still_passes_without_historical_arguments(self) -> None:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        result = run("bash", str(DEPLOY), "--source-selection-check-only", cwd=ROOT, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"target={self.latest}", result.stdout)
        self.assertIn("expected_deployed_source=not_supplied", result.stdout)

    def test_source_and_deployed_sha_must_be_supplied_together(self) -> None:
        env = os.environ.copy()
        env["NEXOLAB_REPO"] = str(self.repo)
        result = run(
            "bash", str(DEPLOY), "--source-ref", self.target,
            "--source-selection-check-only", cwd=ROOT, env=env
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("must be supplied together", result.stderr)

    def test_successful_deployment_image_authority_is_reused(self) -> None:
        image_id = "sha256:" + "9" * 64
        self._set_deployed_evidence(
            self.target,
            "20260829T010000Z",
            device_agent_image_id=image_id,
        )
        result = self._validate(self.latest, self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed_device_agent_image_id={image_id}", result.stdout)

    def test_superseded_rebaseline_pointer_does_not_block_new_deployment_authority(self) -> None:
        self._set_deployed_evidence(self.target, "20260829T010000Z")
        authority = self.repo / "runtime/recovery-authority/device-agent/current.json"
        authority.parent.mkdir(parents=True, exist_ok=True)
        authority.write_text(json.dumps({"deployed_source": self.base}) + "\n", encoding="utf-8")
        result = self._validate(self.latest, self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ignoring superseded Device Agent rebaseline pointer", result.stdout)
        self.assertIn(f"pointer_source={self.base}", result.stdout)
        self.assertIn(f"deployed_source={self.target}", result.stdout)

    def test_malformed_rebaseline_pointer_fails_closed(self) -> None:
        self._set_deployed_evidence(self.target, "20260829T010000Z")
        authority = self.repo / "runtime/recovery-authority/device-agent/current.json"
        authority.parent.mkdir(parents=True, exist_ok=True)
        authority.write_text("{not-json\n", encoding="utf-8")
        result = self._validate(self.latest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rebaseline recovery authority pointer is invalid", result.stdout + result.stderr)

    def test_mutable_mtime_cannot_make_older_success_authoritative(self) -> None:
        newer = self._set_deployed_evidence(self.target, "20260829T010000Z")
        future = time.time() + 86400
        os.utime(self.base_evidence, (future, future))
        result = self._validate(self.latest, self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.target}", result.stdout)
        self.assertIn(str(newer), result.stdout)

    def test_newer_failed_mutating_attempt_makes_authority_indeterminate(self) -> None:
        failed = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            mutated=True,
            summary_extra="ERROR: post-mutation readiness failed",
        )
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("crossed runtime mutation boundary without success", combined)
        self.assertIn(str(failed), combined)
        self.assertIn("deployed source authority is indeterminate", combined)

    def test_verified_restore_reestablishes_previous_source_authority(self) -> None:
        recovered = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            mutated=True,
            restored_source=self.base,
            summary_extra="ERROR: post-mutation readiness failed",
        )
        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.base}", result.stdout)
        self.assertIn(str(recovered), result.stdout)

    def test_inconsistent_restore_evidence_fails_closed(self) -> None:
        recovered = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            mutated=True,
            restored_source=self.base,
        )
        result_path = recovered / "edge-sqlite-restore-result.json"
        result_document = json.loads(result_path.read_text(encoding="utf-8"))
        result_document["sha256"] = "e" * 64
        result_path.write_text(json.dumps(result_document) + "\n", encoding="utf-8")

        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("recovery authority evidence is inconsistent", combined)
        self.assertIn("deployed source authority is indeterminate", combined)

    def test_legacy_newer_mutating_attempt_without_marker_file_fails_closed(self) -> None:
        failed = self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            summary_extra="Starting central backend, MinIO and observability",
        )
        result = self._validate(self.target, self.base)
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("crossed runtime mutation boundary without success", combined)
        self.assertIn(str(failed), combined)

    def test_newer_failed_pre_mutation_attempt_does_not_replace_authority(self) -> None:
        self._set_deployed_evidence(
            None,
            "20260829T010000Z",
            passed=False,
            summary_extra="ERROR: frontend candidate verification port is already in use: 3100",
        )
        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.base}", result.stdout)

    def test_preflight_fetches_and_fast_forwards_to_fresh_remote_main(self) -> None:
        writer = self.root / "writer"
        self.assertEqual(
            run("git", "clone", "--branch", "main", str(self.remote), str(writer), cwd=self.root).returncode,
            0,
        )
        for key, value in (("user.email", "writer@nexolab.local"), ("user.name", "Writer")):
            self.assertEqual(run("git", "config", key, value, cwd=writer).returncode, 0)
        (writer / "remote.txt").write_text("fresh remote\n", encoding="utf-8")
        self.assertEqual(run("git", "add", "remote.txt", cwd=writer).returncode, 0)
        self.assertEqual(run("git", "commit", "-m", "remote advance", cwd=writer).returncode, 0)
        remote_head = run("git", "rev-parse", "HEAD", cwd=writer).stdout.strip()
        self.assertEqual(run("git", "push", "origin", "main", cwd=writer).returncode, 0)
        self.assertEqual(run("git", "rev-parse", "origin/main", cwd=self.repo).stdout.strip(), self.latest)

        result = self._validate(self.target, self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"origin_main={remote_head}", result.stdout)
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(), remote_head)
        self.assertEqual(run("git", "rev-parse", "origin/main", cwd=self.repo).stdout.strip(), remote_head)


    def test_verified_forward_recovery_reestablishes_target_authority(self) -> None:
        recovered = self._set_forward_recovery_evidence("20260829T010000Z")
        result = self._validate(self.latest, self.target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"deployed={self.target}", result.stdout)
        self.assertIn(str(recovered), result.stdout)

    def test_tampered_forward_recovery_hash_fails_closed(self) -> None:
        recovered = self._set_forward_recovery_evidence("20260829T010000Z")
        (recovered / "frontend-artifact-import.txt").write_text(
            f"status=PASS\nsource_sha={self.target}\nplatform=linux/arm64\nbuild_id=tampered\n"
        )
        result = self._validate(self.latest, self.target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forward recovery authority evidence is invalid", result.stdout + result.stderr)



if __name__ == "__main__":
    unittest.main()
