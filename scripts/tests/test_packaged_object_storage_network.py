"""Isolated contract regression for the private offline object-storage path."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "verify-packaged-object-storage-network.py"
SPEC = importlib.util.spec_from_file_location("storage_network", PATH)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

PROJECT = "nexolab-central"
ADDRESS = "192.0.2.75"
PORT = 9000


def fixture():
    binding = [{"HostIp": ADDRESS, "HostPort": str(PORT)}]
    return {
        f"{PROJECT}-minio-1": {
            "Config": {"Labels": {
                "com.docker.compose.project": PROJECT,
                "com.docker.compose.service": "minio",
            }},
            "State": {"Running": True},
            "HostConfig": {"PortBindings": {"9000/tcp": binding}},
            "NetworkSettings": {
                "Networks": {PROJECT: {"Aliases": ["minio", "nexolab-central-minio-1"]}},
                "Ports": {"9000/tcp": binding},
            },
        },
        f"{PROJECT}-telemetry-service-1": {
            "Config": {"Labels": {
                "com.docker.compose.project": PROJECT,
                "com.docker.compose.service": "telemetry-service",
            }},
            "State": {"Running": True},
            "NetworkSettings": {
                "Networks": {PROJECT: {"Aliases": ["telemetry-service"]}},
            },
        },
    }


class ObjectStorageNetworkAcceptanceTests(unittest.TestCase):
    def checked(self, data, probe=None):
        calls = []
        result = gate.verify(
            project=PROJECT, central_network=PROJECT,
            expected_bind=ADDRESS, expected_port=PORT,
            inspect=lambda name: copy.deepcopy(data[name]),
            probe=probe or (lambda container, alias: calls.append((container, alias))),
        )
        return result, calls

    def test_packaged_storage_accessible_from_actual_api(self):
        result, calls = self.checked(fixture())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(calls, [(f"{PROJECT}-telemetry-service-1", "minio")])

    def test_running_but_detached_storage_fails_even_if_internal_health_green(self):
        data = fixture()
        storage = data[f"{PROJECT}-minio-1"]
        storage["NetworkSettings"]["Networks"] = {}
        storage["NetworkSettings"]["Ports"] = {}
        storage["State"]["Health"] = {"Status": "healthy"}
        with self.assertRaisesRegex(gate.StorageNetworkError, "central Docker network"):
            self.checked(data)

    def test_running_api_but_wrong_network_fails(self):
        data = fixture()
        data[f"{PROJECT}-telemetry-service-1"]["NetworkSettings"]["Networks"] = {}
        with self.assertRaisesRegex(gate.StorageNetworkError, "central Docker network"):
            self.checked(data)

    def test_missing_dns_alias_blocks(self):
        data = fixture()
        data[f"{PROJECT}-minio-1"]["NetworkSettings"]["Networks"][PROJECT]["Aliases"] = []
        with self.assertRaisesRegex(gate.StorageNetworkError, "DNS alias"):
            self.checked(data)

    def test_configured_but_unpublished_port_blocks(self):
        data = fixture()
        data[f"{PROJECT}-minio-1"]["NetworkSettings"]["Ports"] = {}
        with self.assertRaisesRegex(gate.StorageNetworkError, "published port missing"):
            self.checked(data)

    def test_wrong_public_bind_blocks(self):
        data = fixture()
        data[f"{PROJECT}-minio-1"]["NetworkSettings"]["Ports"]["9000/tcp"] = [
            {"HostIp": "0.0.0.0", "HostPort": str(PORT)}
        ]
        with self.assertRaisesRegex(gate.StorageNetworkError, "published port missing"):
            self.checked(data)

    def test_wrong_compose_identity_blocks(self):
        for service in ("minio", "telemetry-service"):
            with self.subTest(service=service):
                data = fixture()
                data[f"{PROJECT}-{service}-1"]["Config"]["Labels"][
                    "com.docker.compose.service"
                ] = "unknown-service"
                with self.assertRaisesRegex(gate.StorageNetworkError, "Compose ownership"):
                    self.checked(data)

    def test_stopped_storage_blocks(self):
        data = fixture()
        data[f"{PROJECT}-minio-1"]["State"]["Running"] = False
        with self.assertRaisesRegex(gate.StorageNetworkError, "not running"):
            self.checked(data)

    def test_api_to_minio_dns_or_http_failure_blocks(self):
        data = fixture()
        with self.assertRaisesRegex(gate.StorageNetworkError, "fixture-dns-unavailable"):
            self.checked(
                data,
                probe=lambda _container, _alias: (_ for _ in ()).throw(
                    gate.StorageNetworkError("fixture-dns-unavailable")
                ),
            )

    def test_invalid_parameters_block_without_touching_docker(self):
        with self.assertRaisesRegex(gate.StorageNetworkError, "invalid"):
            gate.verify(project="", expected_bind=ADDRESS)
        with self.assertRaisesRegex(gate.StorageNetworkError, "invalid"):
            gate.verify(project=PROJECT, expected_bind=ADDRESS, expected_port=0)


if __name__ == "__main__":
    unittest.main()
