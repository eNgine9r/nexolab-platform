from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/rebaseline-device-agent-recovery.py"
DEPLOY = ROOT / "scripts/deploy-current-head-raspberry-pi.sh"
SPEC = importlib.util.spec_from_file_location("device_agent_rebaseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeploymentAuthorityTests(unittest.TestCase):
    source = "f" * 40

    def make_attempt(
        self, root: Path, stamp: str, *, passed: bool = False, mutated: bool = False
    ) -> Path:
        directory = root / stamp
        directory.mkdir()
        summary = "DEPLOYMENT PASSED\n" if passed else "preflight failed\n"
        (directory / "summary.txt").write_text(summary, encoding="utf-8")
        if passed:
            (directory / "final-state.txt").write_text(
                f"commit={self.source}\nruntime_mode=lan\n", encoding="utf-8"
            )
        if mutated:
            (directory / "runtime-mutation-started").write_text("source=x\n", encoding="utf-8")
        return directory

    def test_latest_success_with_later_pre_mutation_failure_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = self.make_attempt(root, "20260829T154823Z", passed=True)
            self.make_attempt(root, "20260830T071417Z")
            authority = MODULE.authoritative_deployment(root, expected, self.source)
        self.assertEqual(authority["source_commit"], self.source)
        self.assertEqual(authority["path"], "runtime/deployments/20260829T154823Z")

    def test_later_unrecovered_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = self.make_attempt(root, "20260829T154823Z", passed=True)
            self.make_attempt(root, "20260830T071417Z", mutated=True)
            with self.assertRaisesRegex(MODULE.RebaselineError, "crossed the mutation"):
                MODULE.authoritative_deployment(root, expected, self.source)

    def test_non_latest_success_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = self.make_attempt(root, "20260829T154823Z", passed=True)
            self.make_attempt(root, "20260830T071417Z", passed=True)
            with self.assertRaisesRegex(MODULE.RebaselineError, "not the latest"):
                MODULE.authoritative_deployment(root, expected, self.source)


class ContainerSafetyTests(unittest.TestCase):
    lost_image = "sha256:" + "8" * 64
    container_id = "5" * 64

    def container(self) -> dict[str, object]:
        config = {
            key: MODULE.SAFE_CONFIG[key]
            for key in ("user", "working_dir", "entrypoint", "cmd", "exposed_ports", "healthcheck")
        }
        return {
            "id": self.container_id,
            "image_id": self.lost_image,
            "name": "/nexolab-edge-device-agent-1",
            "created": "2026-08-29T15:55:08Z",
            "state": {
                "status": "running",
                "running": True,
                "paused": False,
                "restarting": False,
                "dead": False,
                "health": "healthy",
            },
            "config": config,
            "mounts": [
                {
                    "Type": "volume",
                    "Name": MODULE.EXPECTED_EDGE_VOLUME,
                    "Source": f"/var/lib/docker/volumes/{MODULE.EXPECTED_EDGE_VOLUME}/_data",
                    "Destination": "/var/lib/nexolab",
                    "RW": True,
                },
                {
                    "Type": "bind",
                    "Name": "",
                    "Source": "/dev",
                    "Destination": "/host/dev",
                    "RW": False,
                },
            ],
            "size_root_fs": 10_000_000,
        }

    def test_exact_healthy_container_and_mount_identity_pass(self) -> None:
        verified = MODULE.verify_container(
            self.container(), self.container_id[:12], self.lost_image
        )
        self.assertEqual(verified["id"], self.container_id)
        self.assertEqual(verified["mounts"][1]["name"], MODULE.EXPECTED_EDGE_VOLUME)

    def test_unexpected_safe_config_is_rejected(self) -> None:
        container = self.container()
        container["config"]["cmd"] = ["adaptive_main.py"]  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.RebaselineError, "safe image configuration"):
            MODULE.verify_container(container, None, self.lost_image)

    def test_additional_mount_is_rejected(self) -> None:
        container = self.container()
        container["mounts"].append(  # type: ignore[union-attr]
            {
                "Type": "bind",
                "Name": "",
                "Source": "/tmp",
                "Destination": "/unexpected",
                "RW": False,
            }
        )
        with self.assertRaisesRegex(MODULE.RebaselineError, "mount identity"):
            MODULE.verify_container(container, None, self.lost_image)

    @mock.patch.object(MODULE, "run")
    def test_writable_layer_accepts_only_mount_point_artifacts(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "A /host/dev\nA /host\n", "")
        self.assertEqual(MODULE.verify_diff(self.container_id), MODULE.ALLOWED_DIFF)
        run.return_value = subprocess.CompletedProcess([], 0, "C /app/main.py\n", "")
        with self.assertRaisesRegex(MODULE.RebaselineError, "not allowlisted"):
            MODULE.verify_diff(self.container_id)


class ImportContractTests(unittest.TestCase):
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_runtime_health_accepts_deployed_nested_scheduler(self, urlopen: mock.Mock) -> None:
        payload = {
            "status": "ok",
            "node_id": "edge-01",
            "device_mode": "modbus",
            "mqtt_connected": True,
            "queue_depth": 0,
            "acquisition": {
                "cadence_policy_revision": 18,
                "scheduler": {"workers_healthy": True},
            },
        }
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps(payload).encode()
        urlopen.return_value = response
        self.assertTrue(MODULE.read_runtime_health()["workers_healthy"])

    def test_export_mount_exclusion_accepts_directory_placeholders_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "rootfs.tar"
            with tarfile.open(archive_path, "w") as archive:
                for name in ("var/lib/nexolab", "host/dev", "app/main.py"):
                    info = tarfile.TarInfo(name)
                    if name in {"var/lib/nexolab", "host/dev"}:
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        payload = b"safe"
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
            result = MODULE.verify_export_mount_exclusion(archive_path)
        self.assertTrue(result["verified"])
        self.assertEqual(result["nested_entry_count"], 0)

    def test_export_mount_exclusion_rejects_mounted_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "rootfs.tar"
            with tarfile.open(archive_path, "w") as archive:
                info = tarfile.TarInfo("var/lib/nexolab/edge.db")
                payload = b"must-not-be-exported"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaisesRegex(MODULE.RebaselineError, "mounted-path payloads"):
                MODULE.verify_export_mount_exclusion(archive_path)

    @mock.patch.object(MODULE, "docker_format_json")
    @mock.patch.object(MODULE, "run")
    def test_validation_container_removal_failure_fails_closed(
        self, run: mock.Mock, docker_format_json: mock.Mock
    ) -> None:
        image_id = "sha256:" + "1" * 64
        container_id = "5" * 64
        run.side_effect = [
            subprocess.CompletedProcess([], 0, container_id + "\n", ""),
            subprocess.CompletedProcess([], 1, "", "remove failed"),
        ]
        docker_format_json.side_effect = ["created", image_id]
        with self.assertRaisesRegex(MODULE.RebaselineError, "could not be removed"):
            MODULE.validate_create(image_id, "20260830T120000Z")

    @mock.patch.object(MODULE, "docker_format_json")
    @mock.patch.object(MODULE, "run")
    def test_validation_container_reports_removed_only_after_successful_cleanup(
        self, run: mock.Mock, docker_format_json: mock.Mock
    ) -> None:
        image_id = "sha256:" + "1" * 64
        container_id = "5" * 64
        run.side_effect = [
            subprocess.CompletedProcess([], 0, container_id + "\n", ""),
            subprocess.CompletedProcess([], 0, container_id + "\n", ""),
        ]
        docker_format_json.side_effect = ["created", image_id]
        result = MODULE.validate_create(image_id, "20260830T120000Z")
        self.assertTrue(result["removed"])

    def test_import_config_is_a_fixed_non_secret_allowlist(self) -> None:
        changes = MODULE.import_changes("20260830T120000Z", "f" * 40, "5" * 64)
        rendered = "\n".join(changes)
        self.assertIn("ENV PYTHONPATH=/app/site-packages", rendered)
        self.assertIn('ENTRYPOINT ["/usr/bin/python3.13"]', rendered)
        self.assertIn('CMD ["dual_bus_main.py"]', rendered)
        self.assertIn("HEALTHCHECK", rendered)
        self.assertNotIn("MQTT_", rendered)
        self.assertNotIn("RS485_", rendered)
        self.assertNotIn("SERIAL_", rendered)

    def test_source_container_environment_is_never_requested(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('docker_format_json(container, ".Config.Env")', text)
        self.assertIn('"runtime_environment_imported": False', text)

    def test_cli_requires_explicit_execute_acknowledgement(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--deployment-evidence",
                "runtime/deployments/20260829T154823Z",
                "--expected-deployed-source",
                "f" * 40,
                "--lost-image-id",
                "sha256:" + "8" * 64,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit --execute", result.stderr)


class DeploymentIntegrationContractTests(unittest.TestCase):
    def test_rebaseline_resolution_precedes_prebuild_preservation(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        resolver = text.index("--resolve-current")
        preserve_call = text.index("\npreserve_deployed_device_agent_image_for_recovery\n")
        candidate_build = text.index('docker build --pull -t nexolab-device-agent:local')
        self.assertLess(resolver, preserve_call)
        self.assertLess(preserve_call, candidate_build)

    def test_snapshot_uses_addressable_recovery_image_for_rebaseline(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        capture_start = text.index("capture_edge_sqlite_snapshot()")
        capture_end = text.index("\n}\n\npersist_edge_device_agent_quiesce_record()", capture_start)
        capture = text[capture_start:capture_end]
        self.assertIn('recovery_image="$VERIFIED_DEPLOYED_DEVICE_AGENT_IMAGE_ID"', capture)
        self.assertIn('"$recovery_image"', capture)
        self.assertIn('--deployed-device-agent-image-id "$recovery_image"', capture)

    def test_quiesce_keeps_source_container_identity_separate(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        quiesce_start = text.index("quiesce_edge_device_agent_for_cutover()")
        quiesce_end = text.index("\n}\n\nwrite_durable_runtime_mutation_marker()", quiesce_start)
        quiesce = text[quiesce_start:quiesce_end]
        self.assertIn("VERIFIED_DEPLOYED_DEVICE_AGENT_SOURCE_CONTAINER_ID", quiesce)
        self.assertIn("VERIFIED_DEPLOYED_DEVICE_AGENT_SOURCE_IMAGE_ID", quiesce)


if __name__ == "__main__":
    unittest.main()
