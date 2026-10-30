"""Issue #1439: all receipts are invented; no site access, writes or key material."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nexolab-site-dr-capture-handoff.py"
SPEC = importlib.util.spec_from_file_location("site_dr_capture_handoff", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
GiB = 1024**3


def sha(number: int) -> str:
    return f"{number:064x}"


def fixtures() -> tuple[dict, dict]:
    from importlib.util import spec_from_file_location, module_from_spec

    preflight_path = ROOT / "scripts" / "nexolab-site-dr-preflight.py"
    spec = spec_from_file_location("site_preflight_fixture", preflight_path)
    assert spec and spec.loader
    preflight = module_from_spec(spec)
    spec.loader.exec_module(preflight)
    assets = {}
    handoff_assets = []
    for n, (ident, (project, service, _, volume)) in enumerate(preflight.SOURCES.items(), start=1):
        entry = {
            "compose_project": project,
            "compose_service": service,
            "container_id_sha256": sha(n + 100),
            "image_sha256": sha(n + 200),
            "runtime_status": "running",
            "capture_status": "unverified",
            "restore_status": "unverified",
            "disposition": "unclassified" if ident in ("central-ingestion-spool", "edge-mqtt-persistence") else "retain_required",
            "max_proposed_bytes": preflight.CAP_BYTES[ident],
        }
        if volume:
            entry["source_volume"] = volume
        else:
            entry["secret_mount_presence"] = "unverified"
        if ident == "object-storage":
            entry["migration_authority_sha256"] = sha(500)
        assets[ident] = entry
        handoff_assets.append({
            "id": ident,
            "disposition": "retain",
            "consistency_method": module.METHODS[ident],
            "image_sha256": entry["image_sha256"],
            "container_id_sha256": entry["container_id_sha256"],
            "estimated_archive_bytes": min(preflight.CAP_BYTES[ident], 1 * 1024 * 1024),
            "review_evidence_sha256": sha(n + 300),
        })
    # All three retained records share ONE central telemetry-service container.
    central_telemetry = assets["local-auth-private-key"]
    for ident in ("local-auth-public-key", "central-ingestion-spool"):
        for identity_field in ("image_sha256", "container_id_sha256"):
            assets[ident][identity_field] = central_telemetry[identity_field]
            handoff_assets[next(i for i, x in enumerate(handoff_assets) if x["id"] == ident)][
                identity_field
            ] = central_telemetry[identity_field]
    p = {
        "schema_version": 2,
        "kind": "nexolab-site-dr-preflight",
        "profile": "LOCAL_LAN",
        "observed_at": "2026-10-30T10:00:00Z",
        "assets": assets,
        "capacity": {
            "working_free_bytes": 28 * GiB,
            "destination_free_bytes": 16 * GiB,
            "working_reserve_bytes": 20 * GiB,
            "working_staging_cap_bytes": 4 * GiB,
            "destination_minimum_bytes": 16 * GiB,
            "destination_physical_independence": "unverified",
            "destination_key_custody": "unverified",
        },
        "source_inventory": "observed_read_only",
        "backup_capture": "not_performed",
        "encrypted_off_device_copy": "not_verified",
        "isolated_restore": "not_performed",
        "site_activation": "not_authorized",
    }
    h = {
        "schema_version": 1,
        "kind": "nexolab-site-capture-handoff",
        "profile": "LOCAL_LAN",
        "site_id": "nexolab-edge-01",
        "observed_at": "2026-10-30T10:08:00Z",
        "preflight_sha256": hashlib.sha256(module.canonical(p)).hexdigest(),
        "source_device_sha256": sha(801),
        "destination_device_sha256": sha(802),
        "custody": {
            "independent_physical_media_reviewed": True,
            "encrypted_off_device_destination_reviewed": True,
            "key_custody_separate_reviewed": True,
            "encryption": "aes-256-gcm",
            "key_source": "mounted_file",
            "destination_review_sha256": sha(803),
            "key_custody_review_sha256": sha(804),
        },
        "continuity": {
            "sampling_interval_seconds": 10,
            "offline_core_reviewed": True,
            "outbox_high_water_reviewed": True,
            "legacy_minio_retained_reviewed": True,
            "versitygw_retained_reviewed": True,
            "no_modbus_hardware_writes": True,
            "consistency_review_sha256": sha(805),
        },
        "assets": handoff_assets,
    }
    return p, h


def refresh_hash(p: dict, h: dict) -> None:
    h["preflight_sha256"] = hashlib.sha256(module.canonical(p)).hexdigest()


def get_asset(handoff: dict, ident: str) -> dict:
    return next(item for item in handoff["assets"] if item["id"] == ident)


class CaptureHandoffTests(unittest.TestCase):
    def deny(self, preflight: dict, handoff: dict, needle: str) -> None:
        with self.assertRaisesRegex(module.HandoffBlocked, needle):
            module.review(preflight, handoff)

    def test_complete_synthetic_plan_is_structurally_reviewable_not_executable(self):
        result = module.review(*fixtures())
        self.assertEqual(result["status"], "STRUCTURAL_PLAN_READY_FOR_INDEPENDENT_REVIEW")
        self.assertEqual(result["stores"], 8)
        self.assertEqual(result["encrypted_backup"], "NOT_PERFORMED")
        self.assertEqual(result["actual_isolated_restore"], "NOT_PERFORMED")
        self.assertEqual(result["production_capture"], "NOT_AUTHORIZED")
        self.assertEqual(result["site_activation"], "NOT_AUTHORIZED")

    def test_preflight_hash_mismatch_blocks(self):
        p, h = fixtures()
        h["preflight_sha256"] = sha(6)
        self.deny(p, h, "hash mismatch")

    def test_source_image_drift_blocks(self):
        p, h = fixtures()
        get_asset(h, "object-storage")["image_sha256"] = sha(8)
        self.deny(p, h, "source image drift")

    def test_source_container_drift_blocks(self):
        p, h = fixtures()
        get_asset(h, "postgresql")["container_id_sha256"] = sha(8)
        self.deny(p, h, "container drift")

    def test_missing_edge_sqlite_blocks(self):
        p, h = fixtures()
        h["assets"] = [x for x in h["assets"] if x["id"] != "edge-sqlite-outbox"]
        self.deny(p, h, "incomplete")

    def test_duplicate_s3_asset_blocks(self):
        p, h = fixtures()
        h["assets"][1] = deepcopy(h["assets"][0])
        self.deny(p, h, "duplicate")

    def test_wrong_compose_project_is_rejected(self):
        p, h = fixtures()
        p["assets"]["edge-mqtt-persistence"]["compose_project"] = "nexolab-central"
        refresh_hash(p, h)
        self.deny(p, h, "Compose project/service drift")

    def test_auxiliary_shared_service_must_match_same_identity(self):
        p, h = fixtures()
        p["assets"]["central-ingestion-spool"]["image_sha256"] = sha(999)
        get_asset(h, "central-ingestion-spool")["image_sha256"] = sha(999)
        refresh_hash(p, h)
        self.deny(p, h, "shared service identity drift")

    def test_raise_preflight_size_cap_is_forbidden(self):
        p, h = fixtures()
        p["assets"]["postgresql"]["max_proposed_bytes"] = 100 * GiB
        refresh_hash(p, h)
        self.deny(p, h, "cap policy drift")

    def test_legacy_minio_volume_blocks(self):
        p, h = fixtures()
        p["assets"]["object-storage"]["source_volume"] = "nexolab-central-object-storage-data"
        refresh_hash(p, h)
        self.deny(p, h, "volume authority drift")

    def test_missing_migration_authority_blocks(self):
        p, h = fixtures()
        p["assets"]["object-storage"]["migration_authority_sha256"] = "unknown"
        refresh_hash(p, h)
        self.deny(p, h, "invalid SHA-256")

    def test_unclassified_auxiliary_store_blocks(self):
        p, h = fixtures()
        get_asset(h, "central-ingestion-spool")["disposition"] = "unclassified"
        self.deny(p, h, "unclassified")

    def test_wrong_quiesce_method_blocks(self):
        p, h = fixtures()
        get_asset(h, "mqtt-dynamic-security")["consistency_method"] = "unsafe_file_copy"
        self.deny(p, h, "consistency")

    def test_same_physical_source_and_target_blocks(self):
        p, h = fixtures()
        h["destination_device_sha256"] = h["source_device_sha256"]
        self.deny(p, h, "same device")

    def test_missing_independent_media_review_blocks(self):
        p, h = fixtures()
        h["custody"]["independent_physical_media_reviewed"] = False
        self.deny(p, h, "media_reviewed")

    def test_missing_separate_key_custody_review_blocks(self):
        p, h = fixtures()
        h["custody"]["key_custody_separate_reviewed"] = False
        self.deny(p, h, "key_custody_separate")

    def test_missing_encrypted_off_device_review_blocks(self):
        p, h = fixtures()
        h["custody"]["encrypted_off_device_destination_reviewed"] = False
        self.deny(p, h, "encrypted_off_device")

    def test_insufficient_work_reserve_blocks(self):
        p, h = fixtures()
        p["capacity"]["working_free_bytes"] = 23 * GiB
        refresh_hash(p, h)
        self.deny(p, h, "20 GiB")

    def test_insufficient_destination_capacity_blocks(self):
        p, h = fixtures()
        p["capacity"]["destination_free_bytes"] = 15 * GiB
        refresh_hash(p, h)
        self.deny(p, h, "16 GiB")

    def test_aggregate_budget_above_destination_reserve_blocks(self):
        p, h = fixtures()
        p["capacity"]["destination_free_bytes"] = 16 * GiB
        for x in h["assets"]:
            x["estimated_archive_bytes"] = p["assets"][x["id"]]["max_proposed_bytes"]
        self.deny(p, h, "aggregate archive")

    def test_single_store_cap_exceeded_blocks(self):
        p, h = fixtures()
        get_asset(h, "postgresql")["estimated_archive_bytes"] = 5 * GiB
        self.deny(p, h, "per-store bound")

    def test_freshness_after_30_minutes_blocks(self):
        p, h = fixtures()
        h["observed_at"] = "2026-10-30T10:31:00Z"
        self.deny(p, h, "stale")

    def test_wrong_sample_interval_blocks(self):
        p, h = fixtures()
        h["continuity"]["sampling_interval_seconds"] = 5
        self.deny(p, h, "10-second")

    def test_missing_outbox_high_water_proof_blocks(self):
        p, h = fixtures()
        h["continuity"]["outbox_high_water_reviewed"] = False
        self.deny(p, h, "outbox_high_water")

    def test_legacy_rollback_volume_retention_blocks(self):
        p, h = fixtures()
        h["continuity"]["legacy_minio_retained_reviewed"] = False
        self.deny(p, h, "legacy_minio")

    def test_lan_offline_core_false_blocks(self):
        p, h = fixtures()
        h["continuity"]["offline_core_reviewed"] = False
        self.deny(p, h, "offline_core")

    def test_secret_data_in_handoff_is_denied(self):
        p, h = fixtures()
        h["private_key"] = "not a real secret"
        self.deny(p, h, "unexpected fields")

    def test_false_site_restore_claim_blocks(self):
        p, h = fixtures()
        p["site_activation"] = "authorized"
        refresh_hash(p, h)
        self.deny(p, h, "activation forbidden")

    def test_unverified_input_file_permission_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "handoff.json"
            file.write_text(json.dumps(fixtures()[1]), encoding="utf-8")
            file.chmod(0o644)
            with self.assertRaisesRegex(module.HandoffBlocked, "mode 0600"):
                module.parse_offline_document(file)

    def test_symlinked_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "handoff.json"
            file.write_text(json.dumps(fixtures()[1]), encoding="utf-8")
            file.chmod(0o600)
            link = Path(tmp) / "link.json"
            link.symlink_to(file)
            with self.assertRaisesRegex(module.HandoffBlocked, "symlink"):
                module.parse_offline_document(link)

    def test_cli_reports_plan_only_and_denies_fake_capture(self):
        p, h = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            path_p, path_h = Path(tmp) / "preflight.json", Path(tmp) / "handoff.json"
            for path, data in ((path_p, p), (path_h, h)):
                path.write_text(json.dumps(data), encoding="utf-8")
                path.chmod(0o600)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--preflight", str(path_p), "--handoff", str(path_h)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = json.loads(result.stdout)
            self.assertEqual(out["site_activation"], "NOT_AUTHORIZED")
            self.assertEqual(out["production_capture"], "NOT_AUTHORIZED")
            h["custody"]["key_custody_separate_reviewed"] = False
            path_h.write_text(json.dumps(h), encoding="utf-8")
            blocked = subprocess.run(
                [sys.executable, str(SCRIPT), "--preflight", str(path_p), "--handoff", str(path_h)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(blocked.returncode, 78)
            self.assertEqual(json.loads(blocked.stdout)["status"], "BLOCKED")

    def test_no_live_docker_or_production_write_commands(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for token in ("docker exec", "docker compose", "pg_dump", "s3 put", "modbus write", "subprocess.run", "--execute", "--capture"):
            self.assertNotIn(token, source.lower())

    def test_previous_dr_policies_untouched(self):
        policy = json.loads((ROOT / "security/disaster-recovery-assets.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["bundle"]["format"], "nexolab-dr-v1")
        self.assertEqual(len(policy["assets"]), 5)


if __name__ == "__main__":
    unittest.main()
