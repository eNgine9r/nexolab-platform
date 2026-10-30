"""#1437: production-safe, bounded offline synthetic multi-store DR acceptance."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "nexolab-site-dr-fixture-harness.py"
SPEC = importlib.util.spec_from_file_location("dr_fixture_harness", PATH)
assert SPEC and SPEC.loader
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)


class FixtureHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nexolab-ci-dr-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.source = self.root / "source"
        self.source.mkdir(mode=0o700)
        h.seed_fixture(self.source)
        self.key = bytes(range(32))

    def test_eight_store_round_trip_restores_clean_sibling_and_source_unchanged(self):
        initial = h.read_fixture(self.source)
        blob = h.create_bundle(self.source, self.key)
        manifest = h.restore_isolated(blob, self.key, self.source, self.root / "restored")
        self.assertEqual(len(manifest["assets"]), 8)
        self.assertFalse(manifest["site_backup"])
        self.assertEqual(h.read_fixture(self.source), initial)
        for ident, data in initial.items():
            self.assertEqual((self.root / "restored" / f"{ident}.fixture").read_bytes(), data)

    def test_wrong_key_and_tamper_fail_closed(self):
        blob = h.create_bundle(self.source, self.key)
        with self.assertRaisesRegex(h.FixtureBlocked, "authenticated"):
            h.verify_bundle(blob, bytes([255]) * 32)
        with self.assertRaisesRegex(h.FixtureBlocked, "authenticated"):
            h.verify_bundle(blob[:-1] + bytes([blob[-1] ^ 1]), self.key)

    def test_failed_authentication_creates_no_restore_destination(self):
        blob = h.create_bundle(self.source, self.key)
        target = self.root / "restored"
        with self.assertRaisesRegex(h.FixtureBlocked, "authenticated"):
            h.restore_isolated(blob, bytes([0]) * 32, self.source, target)
        self.assertFalse(target.exists())

    def test_missing_asset_fails_closed(self):
        (self.source / "edge-sqlite-outbox.fixture").unlink()
        with self.assertRaisesRegex(h.FixtureBlocked, "missing or unexpected"):
            h.create_bundle(self.source, self.key)

    def test_unknown_extra_protected_state_fails_closed(self):
        (self.source / "unknown-data.fixture").write_text("simulated unknown")
        with self.assertRaisesRegex(h.FixtureBlocked, "missing or unexpected"):
            h.create_bundle(self.source, self.key)

    def test_symlink_fixture_asset_fails_closed(self):
        file = self.source / "postgresql.fixture"
        file.unlink()
        file.symlink_to(self.source / "object-storage.fixture")
        with self.assertRaisesRegex(h.FixtureBlocked, "symlink"):
            h.create_bundle(self.source, self.key)

    def test_symlink_fixture_root_fails_closed(self):
        link = self.root / "link"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(h.FixtureBlocked, "symlink"):
            h.read_fixture(link)

    def test_non_synthetic_source_data_rejected(self):
        path = self.source / "mqtt-dynamic-security.fixture"
        path.write_text(json.dumps({"asset": "mqtt-dynamic-security", "synthetic": False}))
        with self.assertRaisesRegex(h.FixtureBlocked, "cannot treat real data"):
            h.create_bundle(self.source, self.key)

    def test_missing_marker_rejected(self):
        (self.source / ".nexolab-synthetic-only").unlink()
        with self.assertRaisesRegex(h.FixtureBlocked, "missing or unexpected|missing fixture"):
            h.create_bundle(self.source, self.key)

    def test_archive_limits_and_wrong_magic_rejected(self):
        with self.assertRaisesRegex(h.FixtureBlocked, "magic"):
            h.verify_bundle(b"INVALID" + bytes(40), self.key)
        with self.assertRaisesRegex(h.FixtureBlocked, "oversized"):
            h.verify_bundle(h.MAGIC + bytes(h.MAX_TOTAL + 40000), self.key)

    def test_wrong_length_key_rejected(self):
        with self.assertRaisesRegex(h.FixtureBlocked, "32-byte"):
            h.create_bundle(self.source, bytes(16))
        with self.assertRaisesRegex(h.FixtureBlocked, "32-byte"):
            h.verify_bundle(b"1234", bytes(16))

    def test_restore_to_existing_target_is_forbidden(self):
        target = self.root / "restored"
        target.mkdir()
        with self.assertRaisesRegex(h.FixtureBlocked, "already exists"):
            h.restore_isolated(h.create_bundle(self.source, self.key), self.key, self.source, target)

    def test_restore_outside_fixture_workspace_forbidden(self):
        blob = h.create_bundle(self.source, self.key)
        with tempfile.TemporaryDirectory(prefix="other-root-") as tmp:
            with self.assertRaisesRegex(h.FixtureBlocked, "isolated fixture"):
                h.restore_isolated(blob, self.key, self.source, Path(tmp) / "restored")

    def test_unsafe_tar_entries_denied_even_if_encrypted_with_correct_key(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        valid = h.create_bundle(self.source, self.key)
        nonce = valid[len(h.MAGIC):len(h.MAGIC) + 12]
        tar_bytes = AESGCM(self.key).decrypt(nonce, valid[len(h.MAGIC) + 12:], h.AAD)
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as tf:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as src:
                for member in src.getmembers():
                    file = src.extractfile(member)
                    assert file
                    tf.addfile(member, file)
            entry = tarfile.TarInfo("../unsafe.fixture")
            entry.size = 1
            tf.addfile(entry, io.BytesIO(b"x"))
        evil = h.MAGIC + nonce + AESGCM(self.key).encrypt(nonce, output.getvalue(), h.AAD)
        with self.assertRaisesRegex(h.FixtureBlocked, "unsafe or unexpected"):
            h.verify_bundle(evil, self.key)

    def test_archive_duplicate_member_denied(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        valid = h.create_bundle(self.source, self.key)
        nonce = valid[len(h.MAGIC):len(h.MAGIC) + 12]
        tar_bytes = AESGCM(self.key).decrypt(nonce, valid[len(h.MAGIC) + 12:], h.AAD)
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as tf:
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as src:
                for member in src.getmembers():
                    file = src.extractfile(member)
                    assert file
                    tf.addfile(member, file)
            item = tarfile.TarInfo("postgresql.fixture")
            item.size = 1
            tf.addfile(item, io.BytesIO(b"x"))
        with self.assertRaisesRegex(h.FixtureBlocked, "duplicate"):
            h.verify_bundle(h.MAGIC + nonce + AESGCM(self.key).encrypt(nonce, out.getvalue(), h.AAD), self.key)

    def test_manifest_false_site_claim_denied(self):
        archive = h.archive_content(h.read_fixture(self.source))
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
            manifest = json.loads(tf.extractfile("manifest.json").read())
        self.assertIs(manifest["site_backup"], False)
        self.assertIs(manifest["hardware_verified"], False)
        self.assertEqual(manifest["scope"], "eight-store-synthetic-only")

    def test_self_test_returns_only_synthetic_accepted_state(self):
        result = h.self_test()
        self.assertEqual(result["status"], "SYNTHETIC_ONLY_PASS")
        self.assertEqual(result["asset_count"], 8)
        self.assertFalse(result["hardware_verified"])
        self.assertEqual(result["site_activation"], "NOT_AUTHORIZED")
        self.assertEqual(result["site_backup"], "NOT_PERFORMED")

    def test_check_cli_never_emits_backup_success(self):
        result = subprocess.run(
            [sys.executable, str(PATH), "--check"],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["site_backup"], "NOT_PERFORMED")

    def test_self_test_cli_is_synthetic_and_offline(self):
        result = subprocess.run(
            [sys.executable, str(PATH), "--self-test"],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        obj = json.loads(result.stdout)
        self.assertEqual(obj["status"], "SYNTHETIC_ONLY_PASS")
        self.assertEqual(obj["site_activation"], "NOT_AUTHORIZED")

    def test_no_production_path_or_write_api_in_cli(self):
        source = PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("docker exec", "docker compose", "pg_dump", "modbus write", "subprocess.run", "production_key", "--source", "--destination"):
            self.assertNotIn(forbidden, source)

    def test_legacy_v1_policy_untouched_and_still_declares_five_assets(self):
        data = json.loads((ROOT / "security" / "disaster-recovery-assets.json").read_text())
        self.assertEqual(data["bundle"]["format"], "nexolab-dr-v1")
        self.assertEqual(len(data["assets"]), 5)


if __name__ == "__main__":
    unittest.main()
