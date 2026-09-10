from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "infrastructure/systemd/user/nexolab-remote-desktop-commander.service"
JOURNAL = ROOT / "infrastructure/systemd/journald/60-nexolab-persistent.conf"
USER_INSTALLER = ROOT / "scripts/install-raspberry-pi-remote-admin.sh"
JOURNAL_INSTALLER = ROOT / "scripts/install-raspberry-pi-persistent-journal.sh"
DIAGNOSTIC = ROOT / "scripts/diagnose-raspberry-pi-remote-admin.sh"


class RemoteAdminReliabilityTests(unittest.TestCase):
    def test_remote_commander_unit_is_independent_and_pinned(self) -> None:
        text = SERVICE.read_text(encoding="utf-8")
        node_version = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()

        self.assertIn("Restart=always", text)
        self.assertIn("StartLimitIntervalSec=0", text)
        self.assertIn(f"/.nvm/versions/node/v{node_version}/bin/node", text)
        self.assertIn("@wonderwhy-er/desktop-commander/dist/index.js remote", text)
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("StandardOutput=null", text)
        self.assertIn("StandardError=journal", text)
        self.assertIn("SyslogIdentifier=nexolab-remote-desktop-commander", text)
        self.assertNotIn("npx", text)
        self.assertNotIn("@latest", text)
        self.assertNotIn("rpi-connect.service", text)

    def test_journald_policy_is_persistent_and_bounded(self) -> None:
        text = JOURNAL.read_text(encoding="utf-8")

        self.assertIn("Storage=persistent", text)
        self.assertIn("SystemMaxUse=256M", text)
        self.assertIn("SystemKeepFree=2G", text)
        self.assertIn("MaxRetentionSec=14day", text)
        self.assertIn("SyncIntervalSec=1m", text)
        self.assertNotIn("ForwardToNetwork", text)

    def test_shell_scripts_parse_and_installers_support_dry_run(self) -> None:
        scripts = (USER_INSTALLER, JOURNAL_INSTALLER, DIAGNOSTIC)
        for script in scripts:
            subprocess.run(["bash", "-n", str(script)], cwd=ROOT, check=True)

        with tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env["NEXOLAB_REMOTE_ADMIN_HOME"] = home
            user = subprocess.run(
                ["bash", str(USER_INSTALLER), "--dry-run"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("dry_run=true", user.stdout)
            self.assertIn("desktop_commander_version=0.2.48", user.stdout)
            self.assertIn("nexolab-remote-desktop-commander.service", user.stdout)

            deferred = subprocess.run(
                ["bash", str(USER_INSTALLER), "--dry-run", "--defer-start"],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("defer_start=1", deferred.stdout)

        journal = subprocess.run(
            ["bash", str(JOURNAL_INSTALLER), "--dry-run"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("dry_run=true", journal.stdout)
        self.assertIn("Storage=persistent", journal.stdout)
        self.assertIn("SystemMaxUse=256M", journal.stdout)

    def test_installers_fail_closed_and_apply_updated_service(self) -> None:
        user_text = USER_INSTALLER.read_text(encoding="utf-8")
        journal_text = JOURNAL_INSTALLER.read_text(encoding="utf-8")

        self.assertIn('systemctl --user restart "${SERVICE_NAME}"', user_text)
        self.assertIn("Refusing --defer-start while the managed service is already active", user_text)
        self.assertIn("[[ ! -r /proc/device-tree/model ]] ||", journal_text)
        self.assertIn("without verified Raspberry Pi identity", journal_text)

    def test_journal_installer_checks_every_effective_bound(self) -> None:
        text = JOURNAL_INSTALLER.read_text(encoding="utf-8")

        self.assertIn("systemd-analyze cat-config systemd/journald.conf", text)
        self.assertIn("while IFS='=' read -r key expected", text)
        self.assertIn('actual="$(effective_value "${key}" <<<"${EFFECTIVE}" || true)"', text)
        self.assertIn("Effective journald %s mismatch", text)
        for key in ("Storage", "SystemMaxUse", "SystemKeepFree", "MaxRetentionSec", "SyncIntervalSec"):
            self.assertIn(key, JOURNAL.read_text(encoding="utf-8"))

    def test_diagnostic_reports_remote_channel_connectivity(self) -> None:
        text = DIAGNOSTIC.read_text(encoding="utf-8")

        self.assertIn("tailscale status --json", text)
        self.assertIn("tailscale_backend_state=", text)
        self.assertIn("tailscale_self_online=", text)
        self.assertIn("rpi-connect status", text)
        self.assertIn("rpi_connect_status_rc=", text)
        self.assertIn("_TRANSPORT=kernel", text)
        self.assertIn("SYSLOG_IDENTIFIER=tailscaled", text)
        self.assertIn("SYSLOG_IDENTIFIER=rpi-connect", text)

    def test_diagnostic_script_remains_read_only(self) -> None:
        text = DIAGNOSTIC.read_text(encoding="utf-8")
        forbidden = (
            "systemctl restart",
            "systemctl stop",
            "systemctl disable",
            "sudo ",
            "swapon ",
            "mount ",
            "kill ",
            "pkill ",
        )
        for token in forbidden:
            self.assertNotIn(token, text)
        self.assertIn("modbus_write=none", text)
        self.assertIn("hardware_write=none", text)
        self.assertIn("production_application_mutation=none", text)


if __name__ == "__main__":
    unittest.main()
