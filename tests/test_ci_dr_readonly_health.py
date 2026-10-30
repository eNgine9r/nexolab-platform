"""#1441 tests are offline and synthetic. No production Docker, MQTT or hardware."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nexolab-dr-readonly-health.py"
SPEC = importlib.util.spec_from_file_location("nexolab_dr_readonly_health", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dr)
NOW = datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc)
TIMER = {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active", "Persistent": "yes"}


def fixture(now=NOW):
    return {
        "schema_version": 2,
        "kind": "nexolab-site-dr-inventory",
        "profile": "LOCAL_LAN",
        "observed_at": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "assets": [{"id": name} for name in sorted(dr.EXPECTED)],
    }


def fake_validator(document):
    assert document["schema_version"] == 2


class ReadOnlyDRHealthTests(unittest.TestCase):
    def check(self, receipt=None, timer=TIMER, free=26 * dr.GiB):
        return dr.assess(receipt, timer, free, now=NOW, structural_validator=fake_validator)

    def test_no_complete_backup_and_no_timer_is_blocked(self):
        result = self.check(None, None)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["gates"]["scheduler"]["status"], "BLOCKED")
        self.assertEqual(result["gates"]["multi_store_inventory"]["status"], "BLOCKED")
        self.assertEqual(result["site_activation"], "NOT_AUTHORIZED")

    def test_even_complete_attestation_cannot_approve_site(self):
        result = self.check(fixture())
        self.assertEqual(result["gates"]["multi_store_inventory"]["status"], "UNVERIFIED")
        self.assertEqual(result["gates"]["backup_freshness"]["status"], "UNVERIFIED")
        self.assertEqual(result["gates"]["isolated_restore"]["status"], "UNVERIFIED")
        self.assertEqual(result["gates"]["encrypted_off_device_copy"]["status"], "UNVERIFIED")
        self.assertEqual(result["status"], "BLOCKED")

    def test_partial_pg_only_receipt_blocked(self):
        p = fixture()
        p["assets"] = [{"id": "postgresql"}]
        x = self.check(p)
        self.assertEqual(x["gates"]["multi_store_inventory"]["status"], "BLOCKED")

    def test_missing_edge_outbox_blocked(self):
        p = fixture()
        p["assets"] = [item for item in p["assets"] if item["id"] != "edge-sqlite-outbox"]
        x = self.check(p)
        self.assertEqual(x["gates"]["multi_store_inventory"]["status"], "BLOCKED")

    def test_duplicate_mqtt_asset_blocked(self):
        p = fixture()
        p["assets"][-1] = p["assets"][0]
        self.assertEqual(self.check(p)["gates"]["multi_store_inventory"]["status"], "BLOCKED")

    def test_stale_valid_receipt_blocked(self):
        p = fixture()
        p["observed_at"] = (NOW - timedelta(hours=27)).isoformat().replace("+00:00", "Z")
        self.assertEqual(self.check(p)["gates"]["backup_freshness"]["status"], "BLOCKED")

    def test_future_timestamp_blocked(self):
        p = fixture()
        p["observed_at"] = (NOW + timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        self.assertEqual(self.check(p)["gates"]["backup_freshness"]["status"], "BLOCKED")

    def test_disabled_timer_blocked(self):
        t = dict(TIMER, UnitFileState="disabled")
        self.assertEqual(self.check(fixture(), t)["gates"]["scheduler"]["status"], "BLOCKED")

    def test_inactive_timer_blocked(self):
        t = dict(TIMER, ActiveState="inactive")
        self.assertEqual(self.check(fixture(), t)["gates"]["scheduler"]["status"], "BLOCKED")

    def test_non_persistent_timer_blocked(self):
        t = dict(TIMER, Persistent="no")
        self.assertEqual(self.check(fixture(), t)["gates"]["scheduler"]["status"], "BLOCKED")

    def test_missing_systemd_metadata_blocked(self):
        t = dict(TIMER)
        t.pop("Persistent")
        self.assertEqual(self.check(fixture(), t)["gates"]["scheduler"]["status"], "BLOCKED")

    def test_root_headroom_below_20gib_blocks(self):
        self.assertEqual(self.check(fixture(), free=19 * dr.GiB)["gates"]["root_headroom"]["status"], "BLOCKED")
        self.assertEqual(self.check(fixture(), free=20 * dr.GiB)["gates"]["root_headroom"]["status"], "REPORTED_OK")

    def test_invalid_structural_contract_is_blocked(self):
        p = fixture()
        def deny(_):
            raise ValueError("invalid claimed v2 receipt")
        result = dr.assess(p, TIMER, 27 * dr.GiB, now=NOW, structural_validator=deny)
        self.assertEqual(result["gates"]["multi_store_inventory"]["status"], "BLOCKED")

    def test_read_only_systemctl_uses_allowlisted_argv(self):
        stdout = "\n".join(f"{key}={value}" for key, value in TIMER.items()) + "\n"
        with patch.object(dr.subprocess, "run", return_value=Mock(returncode=0, stdout=stdout)) as run:
            self.assertEqual(dr.read_timer(), TIMER)
            argv = run.call_args.args[0]
            self.assertEqual(argv[:3], ["systemctl", "show", dr.TIMER])
            self.assertFalse(any(token in argv for token in ("start", "enable", "stop", "restart", "exec")))
            self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_malformed_or_duplicate_systemd_fields_block(self):
        with patch.object(dr.subprocess, "run", return_value=Mock(returncode=0, stdout="LoadState=loaded\nLoadState=loaded\n")):
            with self.assertRaises(dr.HealthBlocked):
                dr.read_timer()

    def test_missing_systemd_tool_is_blocked(self):
        with patch.object(dr.subprocess, "run", side_effect=OSError("systemctl missing")):
            with self.assertRaisesRegex(dr.HealthBlocked, "not available"):
                dr.read_timer()

    def test_protected_receipt_permissions_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(fixture()), encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(dr.HealthBlocked, "mode 0600"):
                dr.read_sanitized_receipt(path)
            path.chmod(0o600)
            self.assertEqual(dr.read_sanitized_receipt(path)["kind"], "nexolab-site-dr-inventory")

    def test_symlink_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "real.json"
            file.write_text(json.dumps(fixture()), encoding="utf-8")
            file.chmod(0o600)
            link = Path(tmp) / "link.json"
            link.symlink_to(file)
            with self.assertRaisesRegex(dr.HealthBlocked, "symlink"):
                dr.read_sanitized_receipt(link)

    def test_missing_inventory_cli_is_blocked_and_readonly(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 78)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "BLOCKED")
        self.assertEqual(data["site_activation"], "NOT_AUTHORIZED")
        self.assertEqual(data["production_backup"], "NOT_PERFORMED_BY_PROBE")

    def test_source_never_executes_write_actions(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for token in ("docker exec", "docker compose up", "modbus write", "pg_dump -", "service.start", "systemctl enable", "systemctl start", "shutil.rmtree", "unlink(", "open(\"w", "shell=True"):
            self.assertNotIn(token, source.lower())


if __name__ == "__main__":
    unittest.main()
