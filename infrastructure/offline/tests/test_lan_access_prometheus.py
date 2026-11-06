"""NEXOLAB #1468 hermetic offline LAN metrics collector and exporter tests."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/"infrastructure/offline/emit-lan-access-prometheus.py"
EXPORTER=ROOT/"scripts/serve-prometheus-textfile.py"
PROBE=ROOT/"infrastructure/offline/inspect-site-lan-access.py"
RULES=ROOT/"infrastructure/observability/prometheus/optional-rules/lan-access-alerts.yml"
SERVICE=ROOT/"infrastructure/systemd/nexolab-lan-access-probe.service"
TIMER=ROOT/"infrastructure/systemd/nexolab-lan-access-probe.timer"


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    assert spec and spec.loader
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


collector=load("nexolab_collector_1468",SOURCE)
exporter=load("nexolab_exporter_1468",EXPORTER)
readonly=load("nexolab_probe_1468",PROBE)
NOW=1_793_700_000


def result(green=True):
    checks={name:bool(green) for name in collector.METRICS}
    return {
        "status":readonly.READY_VALUE if green else "BLOCKED",
        "checks":checks,
        "read_only":True,
        "site_mutation":False,
        "browser_login_verified":False,
        "live_telemetry_verified":False,
        "hardware_verified":False,
    }


class LanAccessMetricsTests(unittest.TestCase):
    def test_green_only_renders_numeric_metrics_with_timestamp(self):
        out=collector.render(result(),NOW).decode()
        self.assertIn(f"nexolab_lan_access_probe_last_run_timestamp_seconds {NOW}",out)
        self.assertIn("nexolab_lan_access_all_checks_ok 1\n",out)
        for value in collector.METRICS.values():
            self.assertIn(value+" 1\n",out)
        self.assertNotIn("password",out.lower())
        self.assertNotIn("172.18.48.66",out)
        self.assertNotIn("token",out.lower())

    def test_red_probe_yields_numeric_zeroes_not_fake_green(self):
        out=collector.render(result(False),NOW).decode()
        self.assertIn("nexolab_lan_access_all_checks_ok 0\n",out)
        for value in collector.METRICS.values():
            self.assertIn(value+" 0\n",out)

    def test_missing_boolean_or_unsafe_claims_fail_closed(self):
        for edit in [
            {"read_only":False}, {"site_mutation":True},
            {"browser_login_verified":True},{"hardware_verified":True},
            {"status":"UNKNOWN"},
        ]:
            x=result()
            x.update(edit)
            with self.subTest(edit=edit),self.assertRaises(collector.CollectorBlocked):
                collector.render(x,NOW)

    def test_wrong_check_types_fail_closed(self):
        x=result()
        x["checks"]["dashboard"]=1
        with self.assertRaises(collector.CollectorBlocked):
            collector.render(x,NOW)

    def test_inconsistent_result_does_not_emit_green(self):
        x=result()
        x["checks"]["dashboard"]=False
        with self.assertRaises(collector.CollectorBlocked):
            collector.render(x,NOW)

    def test_bad_clock_time_blocks(self):
        with self.assertRaises(collector.CollectorBlocked):
            collector.render(result(),0)

    def test_atomic_publish_creates_only_one_fixed_name_and_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            dst=Path(directory)/"lan-access.prom"
            payload=collector.render(result(),NOW)
            collector.atomic_publish(dst,payload)
            self.assertEqual(dst.read_bytes(),payload)
            self.assertEqual(dst.stat().st_mode & 0o777,0o644)
            second=collector.render(result(False),NOW+60)
            collector.atomic_publish(dst,second)
            self.assertEqual(dst.read_bytes(),second)
            self.assertEqual(list(Path(directory).glob("*.tmp")),[])

    def test_publishing_to_wrong_filename_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(collector.CollectorBlocked):
                collector.atomic_publish(Path(directory)/"disaster-recovery.prom",b"x\n")

    def test_publishing_to_existing_symlink_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            other=root/"sensitive-other.txt"
            other.write_text("KEEP")
            dst=root/"lan-access.prom"
            dst.symlink_to(other)
            with self.assertRaises(collector.CollectorBlocked):
                collector.atomic_publish(dst,b"x\n")
            self.assertEqual(other.read_text(),"KEEP")

    def test_existing_exporter_single_file_contract_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"disaster-recovery.prom"
            p.write_bytes(b"nexolab_dr_status 1\n")
            self.assertEqual(exporter.read_metrics(p),b"nexolab_dr_status 1\n")

    def test_exporter_directory_aggregates_safe_files_without_changing_single_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"disaster-recovery.prom").write_bytes(b"nexolab_dr_status 1\n")
            (root/"lan-access.prom").write_bytes(collector.render(result(),NOW))
            contents=exporter.read_metrics(root)
            self.assertIn(b"nexolab_dr_status 1\n",contents)
            self.assertIn(b"nexolab_lan_access_all_checks_ok 1\n",contents)

    def test_exporter_directory_missing_files_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                exporter.read_metrics(Path(directory))

    def test_exporter_directory_symlink_prom_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"real.txt").write_text("do-not-follow")
            (root/"lan-access.prom").symlink_to(root/"real.txt")
            with self.assertRaises(ValueError):
                exporter.read_metrics(root)

    def test_exporter_directory_overflow_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"a.prom").write_bytes(b"x"*exporter.MAX_METRICS_BYTES)
            (root/"b.prom").write_bytes(b"y"*12)
            with self.assertRaises(ValueError):
                exporter.read_metrics(root)

    def test_exporter_directory_too_many_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for index in range(33):
                (root/f"x{index}.prom").write_bytes(b"a 1\n")
            with self.assertRaises(ValueError):
                exporter.read_metrics(root)

    def test_exporter_directory_nonallowlisted_prom_filename_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"bad name.prom").write_bytes(b"a 1\n")
            with self.assertRaises(ValueError):
                exporter.read_metrics(root)

    def test_rule_file_is_optin_not_auto_loaded_by_existing_source(self):
        cfg=(ROOT/"infrastructure/observability/prometheus/prometheus.yml").read_text()
        self.assertIn("/etc/prometheus/rules/*.yml",cfg)
        self.assertNotIn("optional-rules",cfg)
        self.assertTrue(RULES.exists())
        rules=RULES.read_text()
        for name in (
            "NexolabLanAccessProbeMissing", "NexolabLanAccessUnavailable",
            "NexolabLanDashboardUnavailable", "NexolabLanSessionApiUnavailable",
            "NexolabLanSessionSecurityRegression",
        ):
            self.assertIn("alert: "+name,rules)
        self.assertIn("absent(nexolab_lan_access_probe_last_run_timestamp_seconds)",rules)
        self.assertIn("time() - nexolab_lan_access_probe_last_run_timestamp_seconds > 180",rules)

    def test_optin_systemd_units_are_bound_to_unprivileged_readonly_service(self):
        service=SERVICE.read_text()
        timer=TIMER.read_text()
        self.assertIn("User=nexolab",service)
        self.assertIn("NoNewPrivileges=yes",service)
        self.assertIn("ProtectSystem=strict",service)
        self.assertIn("PrivateDevices=yes",service)
        self.assertIn("ConditionPathExists=/etc/nexolab/lan-access-probe.env",service)
        self.assertIn("TimeoutStartSec=25s",service)
        self.assertNotIn("sudo",service)
        for unsafe in ("docker ", "network connect", "compose down", "modbus", "ExecStartPre="):
            self.assertNotIn(unsafe,service.lower())
        self.assertIn("OnCalendar=*-*-* *:*:00",timer)
        self.assertIn("Persistent=false",timer)
        self.assertNotIn("OnUnitActiveSec=1s",timer)


if __name__=="__main__":
    unittest.main()
