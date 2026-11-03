"""NEXOLAB #1474 hermetic source-only, provenance-gated offline monitor assets."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BUILDER=ROOT/"scripts/build-offline-bundle.sh"
VERIFY=ROOT/"scripts/verify-offline-bundle.py"
GENERATE=ROOT/"scripts/generate-offline-bundle-manifest.py"

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

v=load("nexolab_lan_monitor_bundle_verifier_1474",VERIFY)
g=load("nexolab_lan_monitor_bundle_manifest_1474",GENERATE)

class LanMonitorOfflinePayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/"evidence").mkdir()
        self.paths=set()
        self.caps=[]

    def add_payload(self):
        for name in sorted(v.LAN_MONITOR_ASSETS):
            p=self.root/name
            p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,p)
            self.paths.add(name)

    def save_provenance(self):
        (self.root/"evidence/provenance.json").write_text(
            json.dumps({"tooling_capabilities":self.caps})+"\n"
        )

    def check(self):
        self.save_provenance()
        v.verify_backup_policy_inventory(self.root,self.paths)

    def test_legacy_bundle_without_monitor_stays_compatible(self):
        self.check()

    def test_all_five_optin_sources_pass_pinned_inventory(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        self.check()
        files={p.relative_to(self.root).as_posix() for p in g.relative_files(self.root)}
        self.assertTrue(v.LAN_MONITOR_ASSETS <= files)

    def test_source_only_bundle_has_no_secrets_or_auto_activate(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        self.check()
        all_data=b"\n".join((self.root/n).read_bytes() for n in v.LAN_MONITOR_ASSETS)
        self.assertNotIn(b"BEGIN PRIVATE KEY",all_data)
        self.assertNotIn(b"systemctl enable",all_data)
        self.assertNotIn(b"docker network connect",all_data)
        self.assertNotIn(b"ExecStartPre=",all_data)

    def test_declared_capability_with_missing_source_rejected(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        omitted=sorted(self.paths)[-1]
        self.paths.remove(omitted)
        with self.assertRaisesRegex(SystemExit,"Incomplete or unclaimed"):
            self.check()

    def test_unclaimed_payload_missing_entire_provenance_rejected(self):
        self.add_payload()
        with self.assertRaisesRegex(SystemExit,"Incomplete or unclaimed"):
            v.verify_backup_policy_inventory(self.root,self.paths)

    def test_payload_without_declared_capability_rejected(self):
        self.add_payload()
        with self.assertRaisesRegex(SystemExit,"Incomplete or unclaimed"):
            self.check()

    def test_partial_payload_without_capability_rejected(self):
        self.add_payload()
        self.paths={next(iter(self.paths))}
        with self.assertRaisesRegex(SystemExit,"Incomplete or unclaimed"):
            self.check()

    def test_tooling_provenance_symlink_is_rejected_before_following(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        self.save_provenance()
        provenance=self.root/"evidence/provenance.json"
        payload=provenance.read_bytes()
        provenance.unlink()
        other=self.root/"foreign_provenance.json"
        other.write_bytes(payload)
        provenance.symlink_to(other)
        with self.assertRaisesRegex(SystemExit,"Unsafe tooling provenance symlink"):
            v.verify_backup_policy_inventory(self.root,self.paths)

    def test_source_symlink_rejected_even_when_listed(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        name=sorted(self.paths)[0]
        p=self.root/name
        p.unlink()
        p.symlink_to(ROOT/name)
        with self.assertRaisesRegex(SystemExit,"Unsafe or missing"):
            self.check()

    def test_source_absent_on_disk_even_when_listed_rejected(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]
        (self.root/next(iter(self.paths))).unlink()
        with self.assertRaisesRegex(SystemExit,"Unsafe or missing"):
            self.check()

    def test_provenance_capability_must_be_a_list(self):
        self.add_payload()
        self.save_provenance()
        (self.root/"evidence/provenance.json").write_text(
            json.dumps({"tooling_capabilities":"lan-access-monitor-source-only"})
        )
        with self.assertRaisesRegex(SystemExit,"Invalid tooling capabilities"):
            v.verify_backup_policy_inventory(self.root,self.paths)

    def test_duplicate_capabilities_rejected(self):
        self.add_payload()
        self.caps=[v.LAN_MONITOR_CAPABILITY]*2
        with self.assertRaisesRegex(SystemExit,"Duplicate tooling"):
            self.check()

    def test_builder_flag_is_explicit_not_default(self):
        s=BUILDER.read_text()
        self.assertIn("INCLUDE_LAN_MONITOR_SOURCES=false",s)
        self.assertIn("--include-lan-monitor-sources) INCLUDE_LAN_MONITOR_SOURCES=true",s)
        self.assertIn('if [[ "$INCLUDE_LAN_MONITOR_SOURCES" == true ]]',s)
        self.assertIn('"tooling_capabilities"].append("lan-access-monitor-source-only")',s)
        for name in v.LAN_MONITOR_ASSETS:
            self.assertIn(name,s)

    def actual_builder_copy_block(self, enabled: bool):
        source=BUILDER.read_text()
        source_marker='if [[ "$INCLUDE_LAN_MONITOR_SOURCES" == true ]]; then'
        snippet=source_marker+source.split(source_marker,1)[1]
        snippet=snippet.split("\ncp scripts/verify-offline-bundle.py",1)[0]
        environment={
            "STAGING":str(self.root),
            "INCLUDE_LAN_MONITOR_SOURCES":"true" if enabled else "false",
        }
        # This runs only the source-staging loop in a hermetic test directory;
        # full Docker image/archive build is separately owned by Offline Bundle CI.
        return subprocess.run(
            ["bash","-euo","pipefail","-c",snippet],cwd=ROOT,
            env=environment,capture_output=True,text=True,timeout=8,
        )

    def test_actual_builder_copy_loop_stages_exact_allowlist(self):
        result=self.actual_builder_copy_block(True)
        self.assertEqual(result.returncode,0,result.stderr)
        present={
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*") if p.is_file()
        }
        self.assertEqual(present,v.LAN_MONITOR_ASSETS)

    def test_actual_builder_copy_loop_default_does_not_stage_payload(self):
        result=self.actual_builder_copy_block(False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(list(self.root.rglob("*.py")))
        self.assertFalse(list(self.root.rglob("*.service")))

    def test_standard_verifier_hashes_staged_files(self):
        s=VERIFY.read_text()
        self.assertIn('require(sha256(path) == record.get("sha256")',s)
        self.assertIn("verify_lan_monitor_payload(bundle_root, seen_paths, capabilities)",s)
        self.assertEqual(len(v.LAN_MONITOR_ASSETS),5)

if __name__=="__main__":
    unittest.main()
