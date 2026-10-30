"""Offline source-only tests of complete-site DR inventory v2 (#1433)."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-site-dr-inventory-v2.py"
SPEC = importlib.util.spec_from_file_location("site_dr_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def h(value: int) -> str:
    return f"{value:064x}"


def fixture() -> dict:
    assets = []
    group = h(700)
    pairs = {"local-auth-private-key", "local-auth-public-key"}
    for i, (identifier, (service, boundary, fmt)) in enumerate(MODULE.REQUIRED.items(), start=1):
        source = {
            "compose_service": service,
            "image_sha256": h(i + 10),
            "source_identity_sha256": h(i + 30),
            "authority_sha256": h(i + 50),
            "observed_at": "2026-10-30T09:00:00Z",
        }
        if identifier not in pairs:
            source["source_volume"] = (
                "nexolab-central-object-storage-versitygw-data"
                if identifier == "object-storage"
                else f"nexolab-test-{identifier}-data"
            )
        asset = {
            "id": identifier,
            "disposition": "retain",
            "source": source,
            "capture": {
                "status": "verified",
                "format": fmt,
                "consistency_boundary": boundary,
                "sha256": h(i + 90),
                "bytes": 1000 + i,
                "captured_at": "2026-10-30T09:03:00Z",
                "consistency_group_sha256": group,
            },
            "restore": {
                "status": "verified",
                "receipt_sha256": h(i + 110),
                "new_target": True,
                "source_untouched": True,
                "verification_sha256": h(150) if identifier in pairs else h(i + 140),
            },
        }
        if identifier == "object-storage":
            asset["storage_backend"] = "versitygw"
        assets.append(asset)
    return {
        "schema_version": 2,
        "kind": "nexolab-site-dr-inventory",
        "profile": "LOCAL_LAN",
        "site_id": "nexolab-edge-01",
        "release_commit": "a" * 40,
        "capture_id": "dr-20261030-0900",
        "observed_at": "2026-10-30T09:00:00Z",
        "v1_bundle_format": "nexolab-dr-v1",
        "storage": {
            "encrypted_bundle_sha256": h(200),
            "encrypted_manifest_sha256": h(201),
            "encryption": "aes-256-gcm",
            "key_source": "mounted_file",
            "independent_key_custody_verified": True,
            "off_device_copy_verified": True,
            "source_disk_independent": True,
            "destination_kind": "independent_host",
            "destination_identity_sha256": h(202),
            "free_after_bytes": 21 * 1024**3,
            "isolated_restore_verified": True,
            "restore_target_kind": "isolated_host",
            "restore_target_identity_sha256": h(203),
            "restore_receipt_sha256": h(204),
        },
        "assets": assets,
    }


def get(data: dict, identifier: str) -> dict:
    return next(a for a in data["assets"] if a["id"] == identifier)


class SiteDRInventoryContractTests(unittest.TestCase):
    def valid(self, data: dict) -> None:
        MODULE.validate_site_inventory(data)

    def blocked(self, data: dict, reason: str) -> None:
        with self.assertRaisesRegex(MODULE.InventoryError, reason):
            self.valid(data)

    def test_complete_deterministic_fixture_is_structurally_valid(self) -> None:
        self.valid(fixture())

    def test_reject_missing_edge_sqlite(self) -> None:
        d = fixture()
        d["assets"] = [a for a in d["assets"] if a["id"] != "edge-sqlite-outbox"]
        self.blocked(d, "incomplete")

    def test_reject_legacy_minio_volume(self) -> None:
        d = fixture()
        get(d, "object-storage")["source"]["source_volume"] = "nexolab-central-object-storage-data"
        self.blocked(d, "VersityGW source volume")

    def test_reject_wrong_backend_even_with_current_volume(self) -> None:
        d = fixture()
        get(d, "object-storage")["storage_backend"] = "minio"
        self.blocked(d, "backend identity")

    def test_reject_incorrect_compose_service(self) -> None:
        d = fixture()
        get(d, "object-storage")["source"]["compose_service"] = "versitygw"
        self.blocked(d, "service identity mismatch")

    def test_reject_duplicate_asset(self) -> None:
        d = fixture()
        d["assets"][1] = deepcopy(d["assets"][0])
        self.blocked(d, "duplicate")

    def test_reject_unknown_protected_asset(self) -> None:
        d = fixture()
        d["assets"][1]["id"] = "mystery-data"
        self.blocked(d, "unrecognized")

    def test_reject_unclassified_ingestion_spool(self) -> None:
        d = fixture()
        get(d, "central-ingestion-spool")["disposition"] = "unclassified"
        self.blocked(d, "unclassified")

    def test_rebuildable_auxiliary_state_requires_proof(self) -> None:
        d = fixture()
        a = get(d, "edge-mqtt-persistence")
        a.pop("capture")
        a.pop("restore")
        a["disposition"] = "proven_rebuildable"
        a["rebuild_proof_sha256"] = h(220)
        self.valid(d)
        del a["rebuild_proof_sha256"]
        self.blocked(d, "missing or unexpected")

    def test_critical_asset_cannot_be_declared_rebuildable(self) -> None:
        d = fixture()
        a = get(d, "postgresql")
        a.pop("capture")
        a.pop("restore")
        a["disposition"] = "proven_rebuildable"
        a["rebuild_proof_sha256"] = h(210)
        self.blocked(d, "cannot be discarded")

    def test_missing_image_identity_fails(self) -> None:
        d = fixture()
        get(d, "edge-sqlite-outbox")["source"]["image_sha256"] = "unknown"
        self.blocked(d, "invalid SHA-256")

    def test_wrong_consistency_boundary_fails(self) -> None:
        d = fixture()
        get(d, "edge-sqlite-outbox")["capture"]["consistency_boundary"] = "file_copy"
        self.blocked(d, "consistency boundary")

    def test_cross_store_inconsistent_receipt_fails(self) -> None:
        d = fixture()
        get(d, "postgresql")["capture"]["consistency_group_sha256"] = h(999)
        self.blocked(d, "cross-store")

    def test_no_independent_key_custody_fails(self) -> None:
        d = fixture()
        d["storage"]["independent_key_custody_verified"] = False
        self.blocked(d, "key_custody")

    def test_no_verified_off_device_copy_fails(self) -> None:
        d = fixture()
        d["storage"]["off_device_copy_verified"] = False
        self.blocked(d, "off_device_copy")

    def test_insufficient_free_space_fails(self) -> None:
        d = fixture()
        d["storage"]["free_after_bytes"] = 19 * 1024**3
        self.blocked(d, "20 GiB")

    def test_restore_to_source_is_forbidden(self) -> None:
        d = fixture()
        get(d, "mqtt-dynamic-security")["restore"]["source_untouched"] = False
        self.blocked(d, "unsafe restore target")

    def test_restoration_must_be_isolated(self) -> None:
        d = fixture()
        d["storage"]["restore_target_kind"] = "production_host"
        self.blocked(d, "isolated host")

    def test_storage_and_restore_target_must_differ(self) -> None:
        d = fixture()
        d["storage"]["restore_target_identity_sha256"] = d["storage"]["destination_identity_sha256"]
        self.blocked(d, "independent")

    def test_local_auth_keypair_must_match(self) -> None:
        d = fixture()
        get(d, "local-auth-public-key")["restore"]["verification_sha256"] = h(501)
        self.blocked(d, "keypair")

    def test_no_plaintext_secret_payload_or_unknown_fields(self) -> None:
        d = fixture()
        d["storage"]["private_key"] = "fake-test-not-real"
        self.blocked(d, "unexpected keys")

    def test_reject_invalid_version(self) -> None:
        d = fixture()
        d["schema_version"] = 1
        self.blocked(d, "schema_version")

    def test_reject_boolean_size(self) -> None:
        d = fixture()
        get(d, "postgresql")["capture"]["bytes"] = True
        self.blocked(d, "archive bytes")

    def test_reject_invalid_snapshot_timestamp(self) -> None:
        d = fixture()
        get(d, "postgresql")["capture"]["captured_at"] = "yesterday"
        self.blocked(d, "expected UTC")

    def test_cli_requires_inventory_and_keeps_activation_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "inventory.json"
            p.write_text(json.dumps(fixture()), encoding="utf-8")
            response = subprocess.run(
                [sys.executable, str(SCRIPT), "--inventory", str(p)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(response.returncode, 0, response.stdout + response.stderr)
            self.assertIn("STRUCTURAL_GATE=PASS", response.stdout)
            self.assertIn("RUNTIME_EVIDENCE=NOT_INDEPENDENTLY_VERIFIED", response.stdout)
            self.assertIn("SITE_ACTIVATION=NOT_AUTHORIZED", response.stdout)
            p.write_text("{}", encoding="utf-8")
            denied = subprocess.run(
                [sys.executable, str(SCRIPT), "--inventory", str(p)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(denied.returncode, 78)
            self.assertIn("STRUCTURAL_GATE=BLOCKED", denied.stdout)

    def test_legacy_v1_validation_remains_supported(self) -> None:
        legacy_path = ROOT / "scripts" / "validate-disaster-recovery-assets.py"
        spec = importlib.util.spec_from_file_location("legacy_dr", legacy_path)
        assert spec and spec.loader
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        policy = legacy.validate_policy(ROOT / "security" / "disaster-recovery-assets.json")
        self.assertEqual(policy["bundle"]["format"], "nexolab-dr-v1")
        self.assertEqual(len(policy["assets"]), 5)


if __name__ == "__main__":
    unittest.main()
