"""#1632 health integration: the ``isolated_restore`` gate consumes a verified restore receipt.

Offline and synthetic. Receipts are built with the restore tool's own functions (custody
verification of a real synthetic bundle, ``Checks``, ``store_verification_block``,
``compute_rpo_rto``, ``target_fingerprint``, ``write_receipt``, ``v2_fields``), never against
production. unittest style so the Core CI ``unittest discover -p 'test_ci_*.py'`` runs it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
HEALTH_SCRIPT = ROOT / "scripts" / "nexolab-dr-readonly-health.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


health = _load("nexolab_dr_readonly_health_1632", HEALTH_SCRIPT)
# Reuse the #1632 synthetic bundle/custody builders (no Docker, no network).
iso = _load("nexolab_dr_isolated_restore_fixtures_1632", ROOT / "tests" / "test_ci_dr_isolated_restore.py")
inventory_fixtures = _load("nexolab_site_dr_inventory_fixtures_1632", ROOT / "tests" / "test_ci_site_dr_inventory_v2.py")
ir = iso.ir
drs = ir.drs
oc = ir.offdevice
v2 = iso.v2

UTC = timezone.utc
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
STARTED = datetime(2026, 11, 22, 11, 0, 0, tzinfo=UTC)
RESTORE_STARTED = STARTED + timedelta(seconds=5)
READY = RESTORE_STARTED + timedelta(seconds=540)
COMPLETED = READY + timedelta(seconds=90)
TIMER = {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active", "Persistent": "yes"}
SECRET_MARKERS = ("password", "secret_access", "private key material", "-----begin", "token")


def objectives() -> dict:
    return json.loads((ROOT / "security" / "disaster-recovery-assets.json").read_text(encoding="utf-8"))["objectives"]


class ReceiptCase(unittest.TestCase):
    """Builds a realistic site-mode receipt for a real synthetic bundle on 'off-device media'."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.evidence = self.tmp / "evidence"
        self.bundle, self.manifest = iso.build_bundle(self.media)
        self.custody = iso.custody_for(self.bundle, self.manifest)
        self.custody_path = self.media / oc.receipt_name(self.bundle.name)
        self.custody_path.write_bytes(drs.canonical_json(self.custody))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build(self, *, rehearsal: bool = False, mutate=None, failing=(), waivers=(), ready=READY,
              completed=COMPLETED, started=STARTED, restore_started=RESTORE_STARTED) -> tuple[dict, Path, str]:
        inputs = ir.verify_custody(bundle_path=self.bundle, custody=self.custody, key=iso.KEY)
        verified = drs.verify_file(self.bundle, iso.KEY)
        entries = ir.compare_stream_with_manifest(verified.entries, verified.manifest)
        binding = ir.bind_source_manifest(self.custody, verified.manifest)
        checks = ir.Checks(waivers=frozenset(waivers))
        for name in (*ir.REQUIRED_CHECKS, *health.SITE_MODE_CHECKS, "object_storage.objects_present_via_s3"):
            detail = {"destination_kind": self.custody["destination_kind"]} if name == "custody.verified" else {}
            checks.add(name, name not in failing, detail)
        stores = {store: ir.store_verification_block(store, {"entry_sha256": entry["sha256"], "ok": True}, True)
                  for store, entry in entries.items() if not store.startswith("local-auth-")}
        pair = ir.store_verification_block("local-auth-keypair", {"keypair": {"matches": True}}, True)
        stores["local-auth-private-key"] = stores["local-auth-public-key"] = pair
        isolation = ir.check_production_isolation(["192.0.2.10"], [22, 5432], resolve=lambda _h: [],
                                                  connect=lambda *_a: False)
        isolation.pop("addresses")
        facts = {"hostname": "spare-pi", "machine_id": "1" * 32, "host_architecture": "aarch64",
                 "host_system": "Linux", "docker_engine_id": "engine", "docker_architecture": "aarch64",
                 "docker_kernel": "6.6"}
        receipt = {
            "schema_version": 1, "kind": ir.RECEIPT_KIND, "issue": 1632,
            "evidence_class": "LOCAL_REHEARSAL_NOT_SITE_EVIDENCE" if rehearsal else "SITE_ISOLATED_RESTORE",
            "statement": ir.REHEARSAL_STATEMENT if rehearsal else ir.SITE_STATEMENT,
            "tool": {"script_sha256": "e" * 64},
            "started_at": ir.iso(started), "restore_started_at": ir.iso(restore_started),
            "ready_at": ir.iso(ready), "stores": stores, "warnings": [],
            "target": {"identity_sha256": ir.target_fingerprint(facts), "isolation": isolation,
                       "internet": ir.check_internet([("192.0.2.53", 53)], connect=lambda *_a: False),
                       "host_architecture": "aarch64", "docker_architecture": "aarch64"},
            "inputs": {**inputs, "bundle_name": self.custody["bundle_name"],
                       "custody_receipt_sha256": ir.sha256_file(self.custody_path)[0],
                       "destination_kind": self.custody["destination_kind"],
                       "destination_identity_sha256": self.custody["destination_identity_sha256"],
                       "custody_copied_at": self.custody["copied_at"], "key_fingerprint": drs.key_fingerprint(iso.KEY),
                       "source_manifest_binding": binding, "backup_created_at": verified.manifest["created_at"],
                       "backup_commit": verified.manifest.get("commit"), "leaf_a_receipt_sha256": "not_available_on_media"},
            "object_storage_s3": {"bucket_private": True, "stat_checked": 2, "present": 2, "etag_mismatches": 0,
                                  "etag_missing": 0, "content_type_mismatches": 0, "metadata_fidelity": "PRESERVED"},
            "egress": {"reachable": [], "resolved": [], "internet_name_resolution_from_stack": False},
            "rpo_rto": ir.compute_rpo_rto(backup_created_at=ir.parse_utc(verified.manifest["created_at"], "c"),
                                          restore_started_at=restore_started, ready_at=ready, newest_data_at=None,
                                          objectives=objectives()),
            "checks": checks.items, "completed_at": ir.iso(completed),
            "status": ir.evaluate_status(checks, rehearsal=rehearsal),
            "failed_checks": checks.failed(), "waived_checks": checks.waived(),
        }
        if mutate is not None:
            mutate(receipt)
        path, digest = ir.write_receipt(receipt, self.evidence)
        return receipt, path, digest

    def verify(self, path: Path | None, custody: Path | None = None, *, now=NOW, offdevice=None, **kwargs) -> dict:
        return health.verify_restore_receipt(path, self.custody_path if custody is None else custody, now=now,
                                             offdevice=offdevice, restore_module=ir, **kwargs)

    def gate(self, path: Path | None, custody: Path | None = None, *, now=NOW, offdevice_verifier=None) -> dict:
        def verifier(*, now, offdevice):
            return self.verify(path, custody, now=now, offdevice=offdevice)
        return health.assess(None, TIMER, 30 * health.GiB, now=now, structural_validator=lambda _doc: None,
                             offdevice_verifier=offdevice_verifier, restore_verifier=verifier)

    def assertBlocked(self, path: Path | None, pattern: str, **kwargs) -> dict:
        result = self.gate(path, **kwargs)
        gate = result["gates"]["isolated_restore"]
        self.assertEqual(gate["status"], "BLOCKED", gate)
        self.assertRegex(gate["reason"], pattern)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["isolated_restore_receipt"]["accepted"])
        return result


class GateSemanticsTests(ReceiptCase):
    def test_good_site_receipt_is_reported_ok_but_never_site_ready(self) -> None:
        _, path, digest = self.build()
        result = self.gate(path)
        self.assertEqual(result["gates"]["isolated_restore"]["status"], "REPORTED_OK")
        self.assertIn("NOT an independent proof", result["gates"]["isolated_restore"]["reason"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["site_activation"], "NOT_AUTHORIZED")
        evidence = result["isolated_restore_receipt"]
        self.assertEqual(evidence["receipt_sha256"], digest)
        self.assertEqual(evidence["bundle_sha256"], self.custody["bundle_sha256"])
        self.assertEqual(evidence["evidence"], "RECEIPT_ATTESTED_REVERIFIED_LOCALLY")
        self.assertNotEqual(evidence["restore_target_identity_sha256"], evidence["destination_identity_sha256"])

    def test_missing_option_stays_unverified_exactly_as_before(self) -> None:
        result = health.assess(None, TIMER, 30 * health.GiB, now=NOW, structural_validator=lambda _doc: None)
        self.assertEqual(result["gates"]["isolated_restore"],
                         {"status": "UNVERIFIED", "reason": "claim cannot prove actual fresh-volume isolated restore"})
        self.assertNotIn("isolated_restore_receipt", result)

    def test_rpo_rto_gaps_are_echoed_and_warn_without_blocking(self) -> None:
        _, path, _ = self.build(ready=RESTORE_STARTED + timedelta(seconds=900), completed=NOW - timedelta(minutes=5))
        evidence = self.gate(path)["isolated_restore_receipt"]
        rpo_rto = evidence["rpo_rto"]
        self.assertEqual(rpo_rto["objectives"]["software_rpo_seconds"], objectives()["software_rpo_seconds"])
        self.assertEqual(rpo_rto["rto_seconds"], 900.0)
        self.assertEqual(rpo_rto["rto_gap_seconds"], 900.0 - objectives()["software_restore_target_seconds"])
        self.assertFalse(rpo_rto["rto_objective_met"])
        self.assertFalse(rpo_rto["rpo_objective_met"])
        self.assertTrue(any(f.startswith("RTO objective missed") for f in evidence["findings"]))
        self.assertTrue(any(f.startswith("RPO objective missed") for f in evidence["findings"]))
        self.assertTrue(evidence["accepted"])

    def test_missing_rpo_rto_blocks(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["rpo_rto"].update(rto_seconds=None))
        self.assertBlocked(path, "rto_seconds")
        _, path, _ = self.build(mutate=lambda r: r.pop("rpo_rto"))
        self.assertBlocked(path, "rpo_rto missing")

    def test_inconsistent_rpo_rto_blocks(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["rpo_rto"].update(rto_seconds=1.0))
        self.assertBlocked(path, "inconsistent with the receipt timestamps")


class SiteModeTests(ReceiptCase):
    def test_rehearsal_receipt_is_blocked(self) -> None:
        _, path, _ = self.build(rehearsal=True)
        self.assertBlocked(path, "evidence_class=LOCAL_REHEARSAL_NOT_SITE_EVIDENCE")

    def test_rehearsal_receipt_relabelled_as_site_is_blocked(self) -> None:
        def relabel(receipt):
            receipt["evidence_class"] = "SITE_ISOLATED_RESTORE"
            receipt["status"] = "PASS"
        _, path, _ = self.build(rehearsal=True, mutate=relabel)
        self.assertBlocked(path, "statement")

    def test_waived_receipt_is_blocked(self) -> None:
        _, path, _ = self.build(rehearsal=True, failing=("isolation.production_unreachable",),
                                waivers=("isolation.production_unreachable",))
        self.assertBlocked(path, "rehearsal")

        def fake_site(receipt):
            receipt["evidence_class"], receipt["statement"], receipt["status"] = (
                "SITE_ISOLATED_RESTORE", ir.SITE_STATEMENT, "PASS")
        _, path, _ = self.build(failing=("isolation.production_unreachable",),
                                waivers=("isolation.production_unreachable",), mutate=fake_site)
        self.assertBlocked(path, "waivers")

    def test_failed_isolation_check_is_blocked_with_its_name(self) -> None:
        _, path, _ = self.build(failing=("isolation.container_egress_blocked",),
                                mutate=lambda r: r.update(status="PASS", failed_checks=[]))
        self.assertBlocked(path, r"isolation check\(s\) not PASS: isolation.container_egress_blocked")

    def test_failed_verification_check_is_blocked(self) -> None:
        _, path, _ = self.build(failing=("postgresql.row_counts_equal_archive",))
        self.assertBlocked(path, "status is not PASS")
        _, path, _ = self.build(failing=("postgresql.row_counts_equal_archive",),
                                mutate=lambda r: r.update(status="PASS", failed_checks=[]))
        self.assertBlocked(path, "postgresql.row_counts_equal_archive")

    def test_missing_site_mode_check_is_blocked(self) -> None:
        def drop(receipt):
            receipt["checks"] = [c for c in receipt["checks"] if c["name"] != "isolation.internet_disconnected"]
        _, path, _ = self.build(mutate=drop)
        self.assertBlocked(path, "isolation.internet_disconnected")

    def test_degraded_metadata_fidelity_is_not_ok(self) -> None:
        def degrade(receipt):
            receipt["object_storage_s3"].update(metadata_fidelity="DEGRADED", etag_missing=2)
            receipt["warnings"].append("FINDING: restored S3 metadata differs from the database for 2 object(s)")
        _, path, _ = self.build(mutate=degrade)
        self.assertBlocked(path, "metadata fidelity is not PRESERVED")

    def test_any_warning_blocks_under_the_strict_default(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["warnings"].append(
            "image telemetry architecture amd64 differs from the target arm64 (emulated)"))
        self.assertBlocked(path, "architecture")
        _, path, _ = self.build(mutate=lambda r: r["warnings"].append("something unexpected"))
        self.assertBlocked(path, "warning")

    def test_failed_or_refused_run_is_blocked(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r.update(refused="internet is reachable"))
        self.assertBlocked(path, "failed or refused run")


class IntegrityTests(ReceiptCase):
    def test_tampered_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["rpo_rto"]["rto_seconds"] = 1
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertBlocked(path, "do not match the .sha256 sidecar")

    def test_tampered_or_missing_sidecar_is_blocked(self) -> None:
        _, path, _ = self.build()
        sidecar = path.with_name(path.name + ".sha256")
        sidecar.write_text(f"{'0' * 64}  {path.name}\n", encoding="ascii")
        self.assertBlocked(path, "do not match the .sha256 sidecar")
        sidecar.write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  other.json\n", encoding="ascii")
        self.assertBlocked(path, "names another file")
        sidecar.unlink()
        self.assertBlocked(path, "sidecar is missing")

    def test_unreadable_or_invalid_receipt_is_blocked(self) -> None:
        self.assertBlocked(self.tmp / "absent.json", "restore receipt is missing")
        bogus = self.tmp / "bogus.json"
        bogus.write_bytes(b'{"kind": "x", "kind": "y"}\n')
        bogus.with_name(bogus.name + ".sha256").write_text(
            f"{hashlib.sha256(bogus.read_bytes()).hexdigest()}  {bogus.name}\n", encoding="ascii")
        self.assertBlocked(bogus, "duplicate keys")
        bogus.write_bytes(b'{"kind": "nexolab-dr-isolated-restore-receipt", "schema_version": 1, "issue": 1632}\n')
        bogus.with_name(bogus.name + ".sha256").write_text(
            f"{hashlib.sha256(bogus.read_bytes()).hexdigest()}  {bogus.name}\n", encoding="ascii")
        self.assertBlocked(bogus, "schema")

    def test_symlinked_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        link = self.evidence / "link.json"
        try:
            link.symlink_to(path)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertBlocked(link, "symlink")

    def test_missing_custody_receipt_option_is_blocked(self) -> None:
        _, path, _ = self.build()
        result = health.assess(None, TIMER, 30 * health.GiB, now=NOW, structural_validator=lambda _doc: None,
                               restore_verifier=health.restore_receipt_reverifier(path, None))
        self.assertEqual(result["gates"]["isolated_restore"]["status"], "BLOCKED")
        self.assertIn("--custody-receipt is required", result["gates"]["isolated_restore"]["reason"])


class BindingTests(ReceiptCase):
    def test_mismatched_custody_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        other = self.tmp / oc.receipt_name(self.bundle.name)
        other.write_bytes(drs.canonical_json(iso.custody_for(self.bundle, self.manifest,
                                                             copied_at="2026-11-22T10:06:00Z")))
        self.assertBlocked(path, "custody_receipt_sha256", custody=other)

    def test_mismatched_bundle_hash_is_blocked(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["inputs"].update(bundle_sha256="0" * 64))
        self.assertBlocked(path, r"does not match the custody receipt \(bundle_sha256\)")

    def test_invalid_custody_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        self.custody_path.write_bytes(json.dumps({**self.custody, "source_disk_independent": False}).encode())
        self.assertBlocked(path, "custody receipt rejected")

    def test_same_target_and_destination_identity_is_blocked(self) -> None:
        def same(receipt):
            receipt["target"]["identity_sha256"] = self.custody["destination_identity_sha256"]
        _, path, _ = self.build(mutate=same)
        self.assertBlocked(path, "equals destination_identity_sha256")

    def test_restore_from_the_restore_hosts_own_disk_is_blocked(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["warnings"].append(
            "bundle is on the same filesystem as the restore work_dir (expected: mounted off-device media)"))
        self.assertBlocked(path, "not off-device media")

    def test_restored_copy_must_be_the_newest_reverified_bundle(self) -> None:
        _, path, _ = self.build()

        def readback(**overrides):
            return lambda: {"status": "READBACK_REVERIFIED", "bundle_name": self.custody["bundle_name"],
                            "bundle_sha256": self.custody["bundle_sha256"], "destination_kind": "dedicated_media",
                            "destination_identity_sha256": self.custody["destination_identity_sha256"], **overrides}
        ok = self.gate(path, offdevice_verifier=readback())
        self.assertEqual(ok["gates"]["encrypted_off_device_copy"]["status"], "REPORTED_OK")
        self.assertEqual(ok["gates"]["isolated_restore"]["status"], "REPORTED_OK")
        self.assertTrue(ok["isolated_restore_receipt"]["bound_to_offdevice_readback"])
        self.assertBlocked(path, r"newest re-verified bundle .*bundle_sha256",
                           offdevice_verifier=readback(bundle_sha256="1" * 64))

        def unreadable():
            raise OSError("not mounted")
        result = self.assertBlocked(path, "not re-verified", offdevice_verifier=unreadable)
        self.assertEqual(result["gates"]["encrypted_off_device_copy"]["status"], "BLOCKED")

    def test_tampered_store_verification_hash_is_blocked(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r["stores"]["postgresql"]["verification"].update(ok=False))
        self.assertBlocked(path, "postgresql: verification_sha256")


class AgeTests(ReceiptCase):
    def test_stale_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        self.assertEqual(self.gate(path, now=COMPLETED + timedelta(days=35))["gates"]["isolated_restore"]["status"],
                         "REPORTED_OK")
        self.assertBlocked(path, "36 days old", now=COMPLETED + timedelta(days=36))
        with self.assertRaisesRegex(health.HealthBlocked, "maximum 7"):
            self.verify(path, now=COMPLETED + timedelta(days=8), max_age=timedelta(days=7))

    def test_future_dated_receipt_is_blocked(self) -> None:
        _, path, _ = self.build()
        self.assertBlocked(path, "dated in the future", now=COMPLETED - timedelta(minutes=2))

    def test_out_of_order_timestamps_are_blocked(self) -> None:
        _, path, _ = self.build(mutate=lambda r: r.update(completed_at=ir.iso(READY - timedelta(seconds=1))))
        self.assertBlocked(path, "out of order")


class InventoryV2Tests(ReceiptCase):
    def test_real_receipt_v2_fields_are_accepted_by_the_inventory_contract(self) -> None:
        receipt, path, digest = self.build()
        self.assertTrue(ir.verify_receipt_file(path)["sidecar_matches"])
        fields = ir.v2_fields(json.loads(path.read_text(encoding="utf-8")), digest)
        self.assertTrue(fields["storage"]["isolated_restore_verified"])
        inventory = inventory_fixtures.fixture()
        inventory["storage"].update(fields["storage"])
        inventory["storage"].update(encrypted_bundle_sha256=self.custody["bundle_sha256"],
                                    destination_kind=self.custody["destination_kind"])
        self.assertEqual(set(inventory["storage"]), v2.STORAGE_FIELDS)
        for asset in inventory["assets"]:
            asset["restore"] = fields["assets_restore"][asset["id"]]
            self.assertEqual(set(asset["restore"]), v2.RESTORE_FIELDS)
        v2.validate_site_inventory(inventory)  # raises on any field-rule violation
        self.assertEqual(self.verify(path)["receipt_sha256"], fields["storage"]["restore_receipt_sha256"])

    def test_rehearsal_v2_fields_are_rejected_by_the_inventory_contract(self) -> None:
        _, path, digest = self.build(rehearsal=True)
        fields = ir.v2_fields(json.loads(path.read_text(encoding="utf-8")), digest)
        inventory = inventory_fixtures.fixture()
        inventory["storage"].update(fields["storage"])
        for asset in inventory["assets"]:
            asset["restore"] = fields["assets_restore"][asset["id"]]
        with self.assertRaises(v2.InventoryError):
            v2.validate_site_inventory(inventory)


class CliTests(ReceiptCase):
    """The CLI uses the real clock and the default 35-day window, so timestamps are relative to now."""

    def setUp(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)
        created = ir.iso(self.now - timedelta(hours=2))
        with unittest.mock.patch.object(iso, "CREATED", created):
            super().setUp()

    def build_recent(self) -> tuple[dict, Path, str]:
        ready = self.now - timedelta(minutes=3)
        restore_started = ready - timedelta(seconds=540)
        return self.build(ready=ready, completed=self.now - timedelta(minutes=1),
                          restore_started=restore_started, started=restore_started - timedelta(seconds=5))

    def run_cli(self, *args: str) -> tuple[int, dict, str]:
        result = subprocess.run([sys.executable, "-B", str(HEALTH_SCRIPT), *args], capture_output=True, text=True,
                                timeout=60)
        return result.returncode, json.loads(result.stdout), result.stdout + result.stderr

    def snapshot(self) -> dict:
        return {str(p.relative_to(self.tmp)): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in sorted(self.tmp.rglob("*"))}

    def test_cli_reports_receipt_read_only_without_secrets(self) -> None:
        _, path, _ = self.build_recent()
        before = self.snapshot()
        code, report, raw = self.run_cli("--restore-receipt", str(path), "--custody-receipt", str(self.custody_path))
        self.assertEqual(code, 78)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["site_activation"], "NOT_AUTHORIZED")
        self.assertEqual(report["gates"]["isolated_restore"]["status"], "REPORTED_OK", report["gates"])
        self.assertEqual(self.snapshot(), before, "the health probe must not create or change files")
        lowered = raw.lower()
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, lowered)
        self.assertNotIn(iso.KEY.hex(), lowered)

    def test_cli_blocks_tampered_receipt_and_missing_custody(self) -> None:
        _, path, _ = self.build_recent()
        path.write_bytes(path.read_bytes().replace(b'"PASS"', b'"PASS" ', 1))
        code, report, _ = self.run_cli("--restore-receipt", str(path), "--custody-receipt", str(self.custody_path))
        self.assertEqual(code, 78)
        self.assertEqual(report["gates"]["isolated_restore"]["status"], "BLOCKED")
        self.assertIn("sidecar", report["gates"]["isolated_restore"]["reason"])
        code, report, _ = self.run_cli("--restore-receipt", str(path))
        self.assertEqual(report["gates"]["isolated_restore"]["status"], "BLOCKED")
        self.assertIn("--custody-receipt is required", report["gates"]["isolated_restore"]["reason"])

    def test_cli_without_option_is_unchanged(self) -> None:
        code, report, _ = self.run_cli()
        self.assertEqual(code, 78)
        self.assertEqual(report["gates"]["isolated_restore"]["status"], "UNVERIFIED")
        self.assertNotIn("isolated_restore_receipt", report)


if __name__ == "__main__":
    unittest.main()
