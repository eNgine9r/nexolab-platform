"""NEXOLAB #1469 exact Edge container/volume preflight; hermetic, no site writes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-edge-site-migration-gates.py"
spec = importlib.util.spec_from_file_location("nexolab_site_migration", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CANDIDATE = "172.26.0.0/24"
SUBNET = "172.18.0.0/16"
MQTT_DIGEST = "sha256:" + "a" * 64
AGENT_DIGEST = "sha256:" + "b" * 64


def fixtures():
    image_digests = {"mqtt": frozenset({MQTT_DIGEST}),
                     "device-agent": frozenset({AGENT_DIGEST})}
    network_report = {
        "status": "candidate_unapproved",
        "candidate": CANDIDATE,
        "candidate_status": "locally_disjoint_not_site_approved",
        "site_cutover_authorized": False,
        "mutation_performed": False,
        "site_reservations_verified": False,
        "candidate_conflicts": [],
        "existing_overlap": [{"docker": m.NETWORK_NAME, "docker_cidr": SUBNET,
                              "lan": "172.18.48.0/21", "interface": "eth0"}],
    }
    containers = {}
    volumes = {}
    for role, (name, _, volume, port, host_port) in m.PROTECTED_ROLES.items():
        containers[role] = {
            "Name": "/" + name,
            "Image": MQTT_DIGEST if role == "mqtt" else AGENT_DIGEST,
            "Config": {"Labels": {
                "com.docker.compose.project": "nexolab-edge",
                "com.docker.compose.service": role,
            }},
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "NetworkSettings": {"Networks": {
                m.NETWORK_NAME: {"IPAddress": "172.18.0.2"},
                m.STANDALONE: {"IPAddress": "172.21.0.3"},
            }},
            "HostConfig": {"PortBindings": {port: [{
                "HostIp": "127.0.0.1", "HostPort": host_port
            }]}},
            "Mounts": [{"Type": "volume", "Name": volume,
                        "Destination": ("/mosquitto/data" if role == "mqtt"
                                        else "/var/lib/nexolab")}],
        }
        volumes[volume] = {"Name": volume}
    return dict(candidate=CANDIDATE, image_digests=image_digests,
                network_report=network_report, containers=containers,
                volumes=volumes, update_lock_free=True,
                protected_release_ready=True)


class MigrationGatesTests(unittest.TestCase):
    def setUp(self):
        self.data = fixtures()

    def run_policy(self):
        return m.evaluate(**self.data)

    def assert_block(self, reason: str):
        out = self.run_policy()
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["reason"], reason)
        self.assertTrue(out["read_only"])
        for field in ("mutation_performed", "site_cutover_authorized", "hardware_verified"):
            self.assertFalse(out[field])
        return out

    def test_healthy_image_volume_and_locally_disjoint_subnet_still_not_site_approved(self):
        x=self.assert_block("site_reservation_rollback_and_hardware_acceptance_required")
        self.assertTrue(x["checks"]["immutable_package_identity"])
        self.assertTrue(x["checks"]["edge_persistent_volume_identities"])
        self.assertTrue(x["checks"]["candidate_locally_disjoint"])
        self.assertFalse(x["checks"]["site_network_reservation"])
        self.assertFalse(x["checks"]["protected_consistent_rollback"])
        self.assertFalse(x["checks"]["actual_offline_boot_acceptance"])

    def test_missing_immutable_release_blocks(self):
        self.data["protected_release_ready"]=False
        self.assert_block("validated_site_package_unavailable")

    def test_update_in_progress_blocks(self):
        self.data["update_lock_free"]=False
        self.assert_block("version_update_in_progress")

    def test_wrong_explicit_candidate_blocks(self):
        self.data["candidate"]="172.27.0.0/24"
        self.assert_block("source_candidate_mismatch")

    def test_overlapping_candidate_blocks(self):
        r=self.data["network_report"]
        r["status"]="candidate_conflict"
        r["candidate_status"]="conflict"
        r["candidate_conflicts"]=[{"source":"interface:eth0","cidr":"172.18.48.0/21"}]
        self.assert_block("candidate_not_locally_safe_or_source_guard_invalid")

    def test_source_guard_cannot_claim_approval(self):
        self.data["network_report"]["site_cutover_authorized"]=True
        self.assert_block("candidate_not_locally_safe_or_source_guard_invalid")

    def test_existing_actual_cidr_overlap_not_proven_blocks(self):
        self.data["network_report"]["existing_overlap"]=[]
        self.assert_block("required_old_edge_overlap_not_proven")

    def test_foreign_network_attach_blocks(self):
        self.data["containers"]["mqtt"]["NetworkSettings"]["Networks"]["foreign"]={}
        self.assert_block("edge_container_network_drift")

    def test_missing_standalone_mqtt_bridge_blocks(self):
        del self.data["containers"]["device-agent"]["NetworkSettings"]["Networks"][m.STANDALONE]
        self.assert_block("edge_container_network_drift")

    def test_changed_mqtt_image_blocks(self):
        self.data["containers"]["mqtt"]["Image"]="sha256:"+"1"*64
        self.assert_block("edge_container_image_or_compose_drift")

    def test_changed_device_agent_compose_identity_blocks(self):
        self.data["containers"]["device-agent"]["Config"]["Labels"]["com.docker.compose.project"]="other"
        self.assert_block("edge_container_image_or_compose_drift")

    def test_stopped_device_agent_blocks(self):
        self.data["containers"]["device-agent"]["State"]["Running"]=False
        self.assert_block("edge_container_image_or_compose_drift")

    def test_missing_edge_sqlite_volume_mount_blocks(self):
        self.data["containers"]["device-agent"]["Mounts"]=[]
        self.assert_block("edge_mqtt_or_sqlite_volume_mount_missing")

    def test_mqtt_volume_missing_from_docker_inspect_blocks(self):
        self.data["volumes"].pop("nexolab-edge_mqtt-data")
        self.assert_block("edge_persistent_volume_missing")

    def test_loopback_api_exposure_must_not_be_opened(self):
        self.data["containers"]["device-agent"]["HostConfig"]["PortBindings"]["8081/tcp"][0]["HostIp"]="0.0.0.0"
        self.assert_block("edge_loopback_port_binding_drift")

    def test_unknown_container_identity_blocks(self):
        self.data["containers"]["mqtt"]["Name"]="/untrusted-mqtt"
        self.assert_block("edge_container_identity_untrusted")

    def test_no_docker_network_or_volume_mutation_commands_exist(self):
        s=SCRIPT.read_text()
        self.assertNotIn("network rm", s)
        self.assertNotIn("compose down", s)
        self.assertNotIn("network create", s)
        self.assertNotIn("modbus write", s.lower())


if __name__ == "__main__":
    unittest.main()
