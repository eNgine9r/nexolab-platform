from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "forward_deployment_recovery.py"
SPEC = importlib.util.spec_from_file_location("forward_deployment_recovery", SCRIPT)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)

TARGET = "b" * 40
PRIOR = "a" * 40
IMAGE = "sha256:" + "c" * 64
TELEMETRY_IMAGE = "sha256:" + "d" * 64


def fixture() -> tuple[dict, dict]:
    release = Path(f"/repo/runtime/frontend-releases/{TARGET}-20260901T064156Z")
    volume = {
        "Name": "nexolab-central-postgres-data",
        "Driver": "local",
        "Mountpoint": "/var/lib/docker/volumes/nexolab-central-postgres-data/_data",
        "CreatedAt": "2026-07-24T07:43:26+03:00",
    }
    expected_contract = {
        "runtime_mode": "live",
        "api_base_url": "http://172.18.48.66:8082",
        "websocket_url": "ws://172.18.48.66:8082/api/v1/telemetry/live",
        "auth_provider": "local",
        "organization_id": "org-1",
    }
    context = {
        "stamp": "20260901T064156Z",
        "prior_source": PRIOR,
        "target_source": TARGET,
        "release_dir": release,
        "frontend": {"build_id": "build-1"},
        "expected_contract": expected_contract,
        "metadata": {"registry_revision": 20, "outbound_queue_high_water": 100},
        "schema_head": "20260828_0027",
        "origin_main": "e" * 40,
        "evidence_hashes": {"runtime_mutation_started": "1" * 64},
        "volumes": [volume],
        "mutation_started_at": "2026-09-01T09:49:45+03:00",
        "attempt_completed_at": "2026-09-01T09:50:24+03:00",
    }
    snapshot = {
        "platform": {"machine": "aarch64"},
        "dashboard": {
            "working_directory": str(release),
            "process_cwd": str(release),
            "source_sha": TARGET,
            "build_id": "build-1",
            "platform": "linux/arm64",
            "runtime_contract": expected_contract,
            "http_status": 200,
            "url": "http://172.18.48.66:3000",
        },
        "device_agent": {
            "container_id": "f" * 64,
            "created_at": "2026-09-01T06:50:13.793481+00:00",
            "image_id": IMAGE,
            "local_image_id": IMAGE,
            "docker_health": "healthy",
            "edge_volume": "nexolab-edge_edge-data",
            "status": "ok",
            "device_mode": "modbus",
            "mqtt_connected": True,
            "queue_depth": 0,
            "expected_bus_workers": 2,
            "active_bus_workers": 2,
            "workers_healthy": True,
            "registry_revision": 20,
            "latest_attempt_at": "2026-09-02T06:39:02Z",
            "sqlite": {
                "quick_check": "ok",
                "outbound_queue_count": 0,
                "outbound_queue_high_water": 101,
            },
        },
        "telemetry": {
            "container_id": "1" * 64,
            "created_at": "2026-09-01T06:49:51.327354+00:00",
            "image_id": TELEMETRY_IMAGE,
            "local_image_id": TELEMETRY_IMAGE,
            "docker_health": "healthy",
            "ready": {"status": "ready", "database": "ready", "mqtt": "ready"},
            "api": "http://172.18.48.66:8082",
            "auth_mode": "jwt",
        },
        "postgres": {
            "container_id": "2" * 64,
            "docker_health": "healthy",
            "volume_name": "nexolab-central-postgres-data",
            "schema_head": "20260828_0027",
        },
        "volumes": {volume["Name"]: copy.deepcopy(volume)},
    }
    return snapshot, context


class ForwardDeploymentRecoveryTests(unittest.TestCase):
    def assert_failure(self, snapshot: dict, context: dict, expected: str) -> None:
        with self.assertRaisesRegex(recovery.RecoveryFailure, expected):
            recovery.validate_runtime_snapshot(snapshot, context)

    def test_valid_runtime_snapshot_passes(self) -> None:
        snapshot, context = fixture()
        recovery.validate_runtime_snapshot(snapshot, context)

    def test_wrong_dashboard_source_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["dashboard"]["source_sha"] = "0" * 40
        self.assert_failure(snapshot, context, "Dashboard source")

    def test_dashboard_contract_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["dashboard"]["runtime_contract"] = copy.deepcopy(
            snapshot["dashboard"]["runtime_contract"]
        )
        snapshot["dashboard"]["runtime_contract"]["auth_provider"] = "cloud"
        self.assert_failure(snapshot, context, "runtime contract")

    def test_device_agent_image_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["local_image_id"] = "sha256:" + "9" * 64
        self.assert_failure(snapshot, context, "selected local image")

    def test_device_agent_container_must_come_from_failed_attempt(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["created_at"] = "2026-09-01T06:40:00+00:00"
        self.assert_failure(snapshot, context, "not created by the failed deployment")

    def test_nonempty_edge_queue_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["queue_depth"] = 1
        self.assert_failure(snapshot, context, "outbound queue")

    def test_worker_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["active_bus_workers"] = 1
        self.assert_failure(snapshot, context, "bus-worker invariant")

    def test_registry_revision_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["registry_revision"] = 21
        self.assert_failure(snapshot, context, "registry revision")

    def test_queue_high_water_cannot_move_backward(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["sqlite"]["outbound_queue_high_water"] = 99
        self.assert_failure(snapshot, context, "high-water mark moved backward")

    def test_telemetry_container_must_come_from_failed_attempt(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["created_at"] = "2026-09-01T07:00:00+00:00"
        self.assert_failure(snapshot, context, "not created by the failed deployment")

    def test_telemetry_image_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["local_image_id"] = "sha256:" + "8" * 64
        self.assert_failure(snapshot, context, "Telemetry Service image")

    def test_disabled_auth_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["auth_mode"] = "disabled"
        self.assert_failure(snapshot, context, "disabled/unknown")

    def test_postgres_schema_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["postgres"]["schema_head"] = "wrong"
        self.assert_failure(snapshot, context, "PostgreSQL schema")

    def test_volume_identity_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["volumes"]["nexolab-central-postgres-data"]["CreatedAt"] = "later"
        self.assert_failure(snapshot, context, "volume identities changed")

    def test_result_hash_forgery_fails_closed(self) -> None:
        snapshot, context = fixture()
        result = recovery.build_result(snapshot, context)
        result["evidence_hashes"] = {"runtime_mutation_started": "0" * 64}
        with self.assertRaisesRegex(recovery.RecoveryFailure, "hashes"):
            recovery.validate_result(result, context)

    def test_result_safety_forgery_fails_closed(self) -> None:
        snapshot, context = fixture()
        result = recovery.build_result(snapshot, context)
        result["safety"]["edge_sqlite_write"] = "performed"
        with self.assertRaisesRegex(recovery.RecoveryFailure, "safety"):
            recovery.validate_result(result, context)

    def test_later_mutating_attempt_always_blocks_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            root = repo / "runtime" / "deployments"
            later = root / "20260902T000000Z"
            later.mkdir(parents=True)
            (later / "runtime-mutation-started").write_text("source=x\n", encoding="utf-8")
            (later / recovery.RESULT_NAME).write_text(
                json.dumps({"status": "reconciled"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                recovery.RecoveryFailure,
                "latest runtime mutation attempt",
            ):
                recovery.ensure_no_newer_mutation(repo, "20260901T064156Z")


if __name__ == "__main__":
    unittest.main()
