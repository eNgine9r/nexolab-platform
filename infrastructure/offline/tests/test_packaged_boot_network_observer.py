"""Tests for read-only packaged NEXOLAB post-boot observer."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "inspect-packaged-boot-network.py"
SPEC = importlib.util.spec_from_file_location("boot_observer", SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

IMAGES = {role: "sha256:" + format(index, "064x")
          for index, role in enumerate(
              ("mqtt", "postgres", "object-storage", "telemetry-service", "dashboard", "device-agent"), 1)}


def fixture():
    items = {}
    for role, name in module.CONTAINER_NAMES.items():
        project = "nexolab-edge" if role == "device-agent" else "nexolab-central"
        port = {"dashboard": "3000/tcp", "mqtt": "1883/tcp",
                "minio": "9000/tcp", "telemetry-service": "8082/tcp"}.get(role)
        bindings = [{"HostIp": "192.0.2.12", "HostPort": port.split("/")[0]}] if port else []
        items[name] = {
            "Image": IMAGES[module.IMAGE_ROLES[role]],
            "Config": {"Labels": {"com.docker.compose.project": project,
                                  "com.docker.compose.service": role}},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": [{"Type": "volume", "Name": v} for v in module.EXPECTED_VOLUMES.get(role, ())],
            "HostConfig": {"PortBindings": {port: bindings} if port else {}},
            "NetworkSettings": {
                "Networks": {n: {} for n in module.NETWORK_REQUIREMENTS[role]},
                "Ports": {port: bindings} if port else {},
            },
        }
    for names in module.EXPECTED_VOLUMES.values():
        for name in names:
            items[name] = {"Name": name}
    return items


def inspector(objects):
    return lambda name, kind: objects[name]


class BootObserverUnitTests(unittest.TestCase):
    def test_ready_host_does_not_need_changes(self):
        result = module.run(Path("/unused"), cidr_check=lambda: None,
                            authority=lambda _: IMAGES, locks=lambda _: None,
                            inspect=inspector(fixture()))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["candidate_order"], [])
        self.assertFalse(result["mutation_performed"])

    def test_lost_networks_detected_in_safe_order(self):
        objects = fixture()
        for role in ("mqtt", "telemetry-service", "dashboard", "minio"):
            item = objects[module.CONTAINER_NAMES[role]]
            item["NetworkSettings"]["Networks"] = {}
            item["NetworkSettings"]["Ports"] = {}
        result = module.run(Path("/unused"), cidr_check=lambda: None,
                            authority=lambda _: IMAGES, locks=lambda _: None,
                            inspect=inspector(objects))
        self.assertEqual(result["status"], "drift_detected")
        self.assertEqual(result["candidate_order"], ["mqtt", "telemetry-service", "dashboard", "minio"])
        self.assertFalse(result["mutation_performed"])

    def test_unsafe_network_stops_before_authority(self):
        calls = []
        def blocked():
            calls.append("cidr")
            raise module.BootGuardError("physical_docker_cidr_not_safe")
        with self.assertRaises(module.BootGuardError):
            module.run(Path("/unused"), cidr_check=blocked,
                       authority=lambda _: calls.append("authority"))
        self.assertEqual(calls, ["cidr"])

    def test_wrong_image_blocks(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["mqtt"]]["Image"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(module.BootGuardError, "container_image_drift_mqtt"):
            module.diagnose_containers(IMAGES, inspector(objects))

    def test_missing_storage_volume_blocks(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["minio"]]["Mounts"] = []
        with self.assertRaisesRegex(module.BootGuardError, "volume_mount_missing_minio"):
            module.diagnose_containers(IMAGES, inspector(objects))

    def test_wrong_compose_label_blocks(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["dashboard"]]["Config"]["Labels"][
            "com.docker.compose.service"] = "other"
        with self.assertRaisesRegex(module.BootGuardError, "container_compose_identity"):
            module.diagnose_containers(IMAGES, inspector(objects))

    def test_running_dashboard_missing_live_host_port_is_detected(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["dashboard"]]["NetworkSettings"]["Ports"] = {}
        result = module.diagnose_containers(IMAGES, inspector(objects))
        self.assertIn({"service": "dashboard", "kind": "missing_published_port",
                       "detail": "3000/tcp"}, result["container_drift"])

    def test_postgres_drift_is_manual_only_and_cannot_be_auto_candidate(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["postgres"]]["NetworkSettings"]["Networks"] = {}
        result = module.run(Path("/unused"), cidr_check=lambda: None,
                            authority=lambda _: IMAGES, locks=lambda _: None,
                            inspect=inspector(objects))
        self.assertEqual(result["status"], "manual_review_required")
        self.assertIn("postgres", result["manual_only_services"])
        self.assertNotIn("postgres", result["candidate_order"])
        self.assertTrue(result["owner_authorization_required_for_repair"])

    def test_hardware_agent_health_failure_is_manual_not_network_autorepair(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["device-agent"]]["State"]["Health"] = {
            "Status": "unhealthy",
        }
        result = module.run(Path("/unused"), cidr_check=lambda: None,
                            authority=lambda _: IMAGES, locks=lambda _: None,
                            inspect=inspector(objects))
        self.assertEqual(result["status"], "manual_review_required")
        self.assertIn("device-agent", result["manual_only_services"])

    def test_missing_health_proof_for_api_cannot_silently_pass(self):
        objects = fixture()
        objects[module.CONTAINER_NAMES["telemetry-service"]]["State"].pop("Health")
        result = module.run(Path("/unused"), cidr_check=lambda: None,
                            authority=lambda _: IMAGES, locks=lambda _: None,
                            inspect=inspector(objects))
        self.assertEqual(result["status"], "drift_detected")
        self.assertIn({"service": "telemetry-service", "kind": "unhealthy",
                       "detail": "healthcheck"}, result["container_drift"])

    def test_missing_locks_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(module.BootGuardError):
                module.check_update_locks(Path(d))
            for name in ("worker.lock", "update-plane.lock"):
                (Path(d) / name).touch()
            module.check_update_locks(Path(d))

    def make_protected_authority(self, base):
        root = Path(base)
        package = root / "catalog" / "validated-package-001"
        package.mkdir(parents=True)
        manifest = {
            "source_commit": "f" * 40,
            "platform": "linux/arm64",
            "version_management": {"bundle_id": "validated-package-001"},
            "images": [{"id": role, "image_id": digest}
                       for role, digest in IMAGES.items()],
        }
        raw = json.dumps(manifest).encode()
        (package / "manifest.json").write_bytes(raw)
        (package / ".nexolab-validated.json").write_text(json.dumps({
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        }))
        current = {
            "deployment_authority": "validated_package",
            "health": "ready", "runtime_state_known": True,
            "bundle_id": "validated-package-001", "bundle_root": str(package),
            "source_commit": "f" * 40, "platform": "linux/arm64",
        }
        (root / "current.json").write_text(json.dumps(current))
        return root, package

    def test_accepted_package_hashes_and_image_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, package = self.make_protected_authority(tmp)
            with patch.object(module.platform, "machine", return_value="aarch64"):
                self.assertEqual(module.validate_authority(root), IMAGES)

    def test_tampered_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, package = self.make_protected_authority(tmp)
            (package / "manifest.json").write_text('{"source_commit":"invalid"}')
            with patch.object(module.platform, "machine", return_value="aarch64"):
                with self.assertRaisesRegex(module.BootGuardError, "marker_mismatch"):
                    module.validate_authority(root)

    def test_nonready_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, package = self.make_protected_authority(tmp)
            current = json.loads((root / "current.json").read_text())
            current["runtime_state_known"] = False
            (root / "current.json").write_text(json.dumps(current))
            with patch.object(module.platform, "machine", return_value="aarch64"):
                with self.assertRaisesRegex(module.BootGuardError, "authority_not_ready"):
                    module.validate_authority(root)

    def test_missing_prior_package_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, package = self.make_protected_authority(tmp)
            current = json.loads((root / "current.json").read_text())
            current["previous_bundle_id"] = "missing-rollback-package"
            (root / "current.json").write_text(json.dumps(current))
            with patch.object(module.platform, "machine", return_value="aarch64"):
                with self.assertRaisesRegex(module.BootGuardError, "prior_rollback_bundle_missing"):
                    module.validate_authority(root)

    def test_unverified_authority_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(module.BootGuardError):
                module.validate_authority(Path(d))


if __name__ == "__main__":
    unittest.main()
