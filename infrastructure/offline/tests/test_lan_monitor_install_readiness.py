"""Hermetic #1472 monitor activation gates, no privileged side effects."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT / "infrastructure/offline/inspect-lan-monitor-install-readiness.py"
spec=importlib.util.spec_from_file_location("nexolab_1472_guard", SOURCE)
assert spec and spec.loader
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

SHA="f"*40
HOST=str(gate.HOST_DIR)

def fixture():
    return {
        "installed_source": SHA, "required_source": SHA,
        "authority": True, "updates_idle": True,
        "exporter": {
            "name":gate.EXPORTER,"running":True,
            "project":"nexolab-central","role":"observability-textfile",
            "path":gate.CONTAINER_DIR + '/' + gate.LEGACY,
            "mounts":[
                {"Type":"bind","Source":HOST,"Destination":gate.CONTAINER_DIR,"RW":False},
                {"Type":"bind","Source":"/home/nexolab/nexolab-platform/scripts/serve-prometheus-textfile.py",
                 "Destination":"/opt/nexolab/scripts/serve-prometheus-textfile.py","RW":False},
            ],
        },
        "directory":{
            "is_directory":True,"is_symlink":False,
            "owner":"nexolab","mode":0o700,
            "same_local_filesystem":True,"new_target_safe":True,
        },
        "legacy":{
            "regular":True,"symlink":False,
            "owner":"nexolab","mode":0o600,"size":969,
        },
        "source_complete":True,
        "timer_loaded":False,
        "alerts_loaded":False,
    }

class ProtectedSiteInstallTests(unittest.TestCase):
    def setUp(self):
        self.values=fixture()

    def result(self):
        return gate.assess(**self.values)

    def blocked(self, reason):
        result=self.result()
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["reason"],reason)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["site_mutation"])
        self.assertFalse(result["site_activation_authorized"])
        self.assertFalse(result["hardware_verified"])
        self.assertFalse(result["checks"]["site_rollback_and_activation_approved"])
        return result

    def test_all_software_checks_pass_but_owner_activation_still_blocked(self):
        result=self.blocked("protected_install_rollback_and_owner_activation_required")
        for k,v in result["checks"].items():
            if k!="site_rollback_and_activation_approved":
                self.assertTrue(v,k)

    def test_package_authority_missing(self):
        self.values["authority"]=False
        self.blocked("protected_package_authority_unavailable")

    def test_installed_source_differs_from_requested_release(self):
        self.values["installed_source"]="a"*40
        self.blocked("requested_source_not_accepted_on_site")

    def test_malformed_requested_commit_refused(self):
        self.values["required_source"]="main"
        self.blocked("requested_source_not_accepted_on_site")

    def test_active_update_lock_blocks(self):
        self.values["updates_idle"]=False
        self.blocked("protected_site_update_active")

    def test_wrong_metrics_host_bind_blocks(self):
        self.values["exporter"]["mounts"][0]["Source"]="/var/lib/nexolab-observability"
        self.blocked("exporter_host_bind_or_legacy_mode_mismatch")

    def test_host_bind_must_be_read_only_to_container(self):
        self.values["exporter"]["mounts"][0]["RW"]=True
        self.blocked("exporter_host_bind_or_legacy_mode_mismatch")

    def test_exporter_script_bind_must_be_read_only_and_pinned(self):
        for key,value in (("RW",True),("Source","/tmp/alternate.py")):
            with self.subTest(key=key):
                original=copy.deepcopy(self.values["exporter"]["mounts"][1])
                self.values["exporter"]["mounts"][1][key]=value
                self.blocked("exporter_host_bind_or_legacy_mode_mismatch")
                self.values["exporter"]["mounts"][1]=original

    def test_missing_or_duplicated_bind_blocks(self):
        for mounts in ([],fixture()["exporter"]["mounts"]*2):
            with self.subTest(count=len(mounts)):
                self.values["exporter"]["mounts"]=mounts
                self.blocked("exporter_host_bind_or_legacy_mode_mismatch")

    def test_exporter_legacy_mode_preserved_until_separate_approval(self):
        self.values["exporter"]["path"]=gate.CONTAINER_DIR
        self.blocked("exporter_host_bind_or_legacy_mode_mismatch")

    def test_exporter_identity_or_shutdown_blocks(self):
        for k,value in (("name","other"),("role","telemetry-service"),
                        ("project","other-project"),("running",False)):
            with self.subTest(key=k):
                original=self.values["exporter"][k]
                self.values["exporter"][k]=value
                self.blocked("exporter_host_bind_or_legacy_mode_mismatch")
                self.values["exporter"][k]=original

    def test_metrics_directory_must_be_private_and_owned(self):
        for k,value in (("is_directory",False),("is_symlink",True),
                        ("owner","root"),("mode",0o775),
                        ("same_local_filesystem",False),("new_target_safe",False)):
            with self.subTest(key=k):
                original=self.values["directory"][k]
                self.values["directory"][k]=value
                self.blocked("unsafe_or_unmapped_site_metrics_directory")
                self.values["directory"][k]=original

    def test_legacy_disaster_recovery_metrics_must_survive(self):
        for k,value in (("regular",False),("symlink",True),
                        ("owner","root"),("mode",0o777),("size",0)):
            with self.subTest(key=k):
                original=self.values["legacy"][k]
                self.values["legacy"][k]=value
                self.blocked("existing_dr_metrics_untrusted")
                self.values["legacy"][k]=original

    def test_missing_source_or_unapproved_unit_blocks(self):
        self.values["source_complete"]=False
        self.blocked("source_artifacts_or_host_path_mismatch")

    def test_preexisting_loaded_timer_requires_manual_review(self):
        self.values["timer_loaded"]=True
        self.blocked("site_probe_timer_unreviewed_or_active")

    def test_early_prometheus_rule_activation_blocks(self):
        self.values["alerts_loaded"]=True
        self.blocked("optional_alerts_activated_before_probe")

    def test_source_unit_paths_and_sandbox_guards_match_site_host_bind(self):
        source=(ROOT/"infrastructure/systemd/nexolab-lan-access-probe.service").read_text()
        self.assertIn("--output "+HOST+"/lan-access.prom",source)
        self.assertIn("ReadWritePaths="+HOST,source)
        self.assertIn("ProtectHome=read-only",source)
        self.assertIn("ProtectSystem=strict",source)
        self.assertIn("NoNewPrivileges=yes",source)
        self.assertIn("User=nexolab",source)
        self.assertIn("PrivateDevices=yes",source)
        self.assertNotIn("--output /var/lib/nexolab-observability",source)

    def test_install_gate_has_no_mutating_execution_mode(self):
        text=SOURCE.read_text()
        for command in ("--execute","docker compose up","systemctl enable",
                        "systemctl restart","docker network connect","modbus write"):
            self.assertNotIn(command,text.lower())

if __name__=="__main__":
    unittest.main()
