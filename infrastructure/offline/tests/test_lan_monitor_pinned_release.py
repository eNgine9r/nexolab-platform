"""#1476 hermetic checks for source-pinned LAN monitor release, not site installation."""
from __future__ import annotations
import importlib.util
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infrastructure/offline/inspect-lan-monitor-pinned-release.py"
TEMPLATE = (ROOT / "infrastructure/systemd/nexolab-lan-access-probe.service").read_text()
spec = importlib.util.spec_from_file_location("nexolab_monitor_pinned_1476", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SOURCE = "b" * 40
ASSETS = sorted(gate.ASSETS)
DIGEST = hashlib.sha256(b"exact-safe-source").hexdigest()


def fixture():
    source_files = {
        name: {"regular": True, "symlink": False, "uid": 0,
               "mode": 0o644, "size_bytes": 17, "sha256": DIGEST}
        for name in ASSETS
    }
    directories = {
        name: {"directory": True, "symlink": False, "uid": 0, "mode": 0o755}
        for name in (
            "/opt", "/opt/nexolab-lan-monitor",
            str(gate.RELEASES), str(gate.RELEASES / SOURCE),
        )
    }
    return {
        "accepted_source": SOURCE, "required_source": SOURCE,
        "package_authority": True,
        "provenance": {"tooling_capabilities": [gate.CAPABILITY]},
        "manifest_records": {
            name: {"sha256": DIGEST, "size_bytes": 17} for name in ASSETS
        },
        "packaged": {name: dict(item) for name, item in source_files.items()},
        "release_dirs": directories,
        "materialized": {name: dict(item) for name, item in source_files.items()},
        "service_template": TEMPLATE,
    }


class PinnedReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.args = fixture()

    def blocked(self, code):
        result = gate.evaluate(**self.args)
        self.assertEqual(result["reason"], code)
        self.assertEqual(result["status"], "BLOCKED")
        for key in ("site_mutation", "activation_authorized", "hardware_verified"):
            self.assertFalse(result[key])
        self.assertTrue(result["read_only"])
        return result

    def test_fully_pinned_software_still_requires_operator_acceptance(self):
        r = self.blocked("operator_rollback_and_site_activation_unverified")
        self.assertTrue(all(
            v for k, v in r["checks"].items()
            if k != "operator_rollback_site_acceptance"
        ))
        self.assertFalse(r["checks"]["operator_rollback_site_acceptance"])

    def test_immutable_package_authority_required(self):
        self.args["package_authority"] = False
        self.blocked("accepted_package_unverified")

    def test_older_accepted_source_is_not_candidate(self):
        self.args["accepted_source"] = "a" * 40
        self.blocked("accepted_source_does_not_match_candidate")

    def test_invalid_requested_source_is_not_allowed(self):
        self.args["required_source"] = "main"
        self.blocked("accepted_source_does_not_match_candidate")

    def test_missing_or_invalid_provenance_refuses(self):
        for capabilities in ([], "string", [gate.CAPABILITY, gate.CAPABILITY], [123]):
            with self.subTest(capabilities=capabilities):
                self.args["provenance"]["tooling_capabilities"] = capabilities
                self.blocked("monitor_provenance_missing_or_invalid")
        self.args["provenance"]["tooling_capabilities"] = [gate.CAPABILITY]

    def test_missing_manifest_asset_blocks(self):
        self.args["manifest_records"].pop(ASSETS[0])
        self.blocked("required_manifest_assets_missing")

    def test_bad_manifest_sha_or_size_blocks(self):
        for key, value in (("sha256", "unknown"), ("size_bytes", 0), ("size_bytes", 100_001)):
            with self.subTest(key=key, value=value):
                before = self.args["manifest_records"][ASSETS[0]][key]
                self.args["manifest_records"][ASSETS[0]][key] = value
                self.blocked("sealed_file_manifest_record_invalid")
                self.args["manifest_records"][ASSETS[0]][key] = before

    def test_monitor_like_extra_manifest_asset_rejected(self):
        self.args["manifest_records"]["infrastructure/systemd/nexolab-lan-access-probe-evil.service"] = {
            "sha256": DIGEST, "size_bytes": 17
        }
        self.blocked("required_manifest_assets_missing")

    def test_source_asset_missing_or_symlink_or_mismatch_blocks(self):
        for attr, value in (("regular", False), ("symlink", True),
                            ("sha256", "a" * 64), ("size_bytes", 123)):
            with self.subTest(attr=attr):
                before = self.args["packaged"][ASSETS[0]][attr]
                self.args["packaged"][ASSETS[0]][attr] = value
                self.blocked("packaged_asset_mismatch_or_unsafe")
                self.args["packaged"][ASSETS[0]][attr] = before

    def test_protected_catalog_without_materialized_release_fails(self):
        self.args["release_dirs"].pop(str(gate.RELEASES / SOURCE))
        self.blocked("pinned_release_directory_not_ready")

    def test_non_root_or_mutable_or_nontraversable_release_rejected(self):
        for key, value in (("directory", False), ("symlink", True),
                           ("uid", 1000), ("mode", 0o777), ("mode", 0o750)):
            with self.subTest(key=key, value=value):
                info = self.args["release_dirs"][str(gate.RELEASES)]
                old = info[key]
                info[key] = value
                self.blocked("pinned_release_directory_not_ready")
                info[key] = old

    def test_bad_opt_ancestor_is_rejected(self):
        self.args["release_dirs"]["/opt"]["uid"] = 1000
        self.blocked("pinned_release_directory_not_ready")

    def test_untrusted_or_unreadable_materialized_asset_rejected(self):
        for key, value in (("regular", False), ("symlink", True),
                           ("uid", 1000), ("mode", 0o600),
                           ("mode", 0o664), ("sha256", "0" * 64)):
            with self.subTest(key=key, value=value):
                info = self.args["materialized"][ASSETS[0]]
                old = info[key]
                info[key] = value
                self.blocked("pinned_release_asset_missing_or_drifted")
                info[key] = old

    def test_valid_immutable_execstart_source_is_rendered(self):
        unit = gate.render_unit(TEMPLATE, SOURCE)
        command = str(gate.RELEASES / SOURCE / gate.SOURCE_SCRIPT)
        self.assertIn("ExecStart=/usr/bin/python3 -I -B " + command, unit)
        self.assertNotIn(gate.OLD_UNIT_SCRIPT, unit)
        self.assertIn("User=nexolab", unit)
        self.assertIn("PrivateDevices=yes", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ReadWritePaths=/home/nexolab/nexolab-platform/runtime/observability", unit)

    def test_changed_unit_unauthorized_execstart_must_fail(self):
        changed = TEMPLATE.replace(gate.OLD_UNIT_SCRIPT, "/tmp/suspicious.py")
        with self.assertRaisesRegex(gate.GateBlocked,"source_service_template_untrusted"):
            gate.render_unit(changed, SOURCE)

    def test_duplicate_or_overridden_systemd_user_refused(self):
        changed = TEMPLATE + "\nUser=root\n"
        with self.assertRaisesRegex(gate.GateBlocked, "source_service_template_untrusted"):
            gate.render_unit(changed, SOURCE)

    def test_dropped_unit_sandbox_must_fail(self):
        changed = TEMPLATE.replace("NoNewPrivileges=yes", "NoNewPrivileges=no")
        with self.assertRaisesRegex(gate.GateBlocked,"source_service_template_untrusted"):
            gate.render_unit(changed, SOURCE)

    def test_prestart_hooks_cannot_be_injected(self):
        changed = TEMPLATE + "\nExecStartPre=/bin/sh -c arbitrary\n"
        with self.assertRaisesRegex(gate.GateBlocked,"source_service_template_untrusted"):
            gate.render_unit(changed, SOURCE)

    def test_missing_source_unit_template_blocks(self):
        self.args["service_template"] = ""
        self.blocked("source_service_template_untrusted")

    def test_inspector_has_no_site_execution_or_mutations(self):
        text = SCRIPT.read_text()
        for unsafe in ("systemctl enable", "docker network", "subprocess.run",
                       "os.chmod(", "os.replace(", "shutil.copy"):
            self.assertNotIn(unsafe, text)

if __name__ == "__main__":
    unittest.main()
