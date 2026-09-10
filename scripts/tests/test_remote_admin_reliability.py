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
VERIFIER = ROOT / "scripts/verify-raspberry-pi-remote-admin-service.sh"
SOURCE_PIN = ROOT / "infrastructure/remote-admin/desktop-commander-source.env"


class RemoteAdminReliabilityTests(unittest.TestCase):
    def test_remote_commander_unit_is_independent_and_pinned(self) -> None:
        text = SERVICE.read_text(encoding="utf-8")
        node_version = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()

        self.assertIn("Restart=always", text)
        self.assertIn("StartLimitIntervalSec=0", text)
        self.assertIn(f"/.nvm/versions/node/v{node_version}/bin/node", text)
        self.assertIn("/nexolab-remote-admin/current/node_modules/@wonderwhy-er/desktop-commander/dist/index.js remote", text)
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("StandardOutput=null", text)
        self.assertIn("StandardError=journal", text)
        self.assertIn("SyslogIdentifier=nexolab-remote-desktop-commander", text)
        self.assertNotIn("npx", text)
        self.assertNotIn("@latest", text)
        self.assertNotIn("rpi-connect.service", text)

    def test_remote_commander_source_is_exactly_pinned(self) -> None:
        text = SOURCE_PIN.read_text(encoding="utf-8")
        installer = USER_INSTALLER.read_text(encoding="utf-8")
        verifier = VERIFIER.read_text(encoding="utf-8")

        self.assertIn("DESKTOP_COMMANDER_VERSION=0.2.48", text)
        self.assertIn("DESKTOP_COMMANDER_SOURCE_REPO=https://github.com/Darmonia/DesktopCommanderMCP.git", text)
        self.assertIn("DESKTOP_COMMANDER_SOURCE_SHA=7edee255c17101bfe50f684bd61e7f818e552205", text)
        self.assertIn("releases/${DESKTOP_COMMANDER_SOURCE_SHA}", installer)
        self.assertIn("git+${DESKTOP_COMMANDER_SOURCE_REPO}#${DESKTOP_COMMANDER_SOURCE_SHA}", installer)
        self.assertIn("writePersistedConfigSnapshot", installer)
        self.assertIn("Existing immutable release failed verification; refusing mutation", installer)
        self.assertIn("onSessionRotated", installer)
        self.assertIn("Unexpected current release", verifier)
        self.assertIn("Source SHA provenance mismatch", verifier)
        self.assertIn("Rotated-session persistence missing", verifier)

    def test_staged_remote_release_is_verified_before_immutable_promotion(self) -> None:
        installer = USER_INSTALLER.read_text(encoding="utf-8")
        verify_staging = 'verify_release "${STAGING_DIR}"'
        promote = 'mv -- "${STAGING_DIR}" "${RELEASE_DIR}"'

        self.assertIn(verify_staging, installer)
        self.assertIn("Staged pinned Desktop Commander release failed verification", installer)
        self.assertIn(promote, installer)
        self.assertLess(installer.index(verify_staging), installer.index(promote))
        self.assertGreater(installer.index("trap - EXIT"), installer.index(promote))

    def test_journald_policy_is_persistent_and_bounded(self) -> None:
        text = JOURNAL.read_text(encoding="utf-8")

        self.assertIn("Storage=persistent", text)
        self.assertIn("SystemMaxUse=256M", text)
        self.assertIn("SystemKeepFree=2G", text)
        self.assertIn("MaxRetentionSec=14day", text)
        self.assertIn("SyncIntervalSec=1m", text)
        self.assertNotIn("ForwardToNetwork", text)

    def test_shell_scripts_parse_and_installers_support_dry_run(self) -> None:
        scripts = (USER_INSTALLER, JOURNAL_INSTALLER, DIAGNOSTIC, VERIFIER)
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
            self.assertIn("desktop_commander_source_sha=7edee255c17101bfe50f684bd61e7f818e552205", user.stdout)
            self.assertIn("/releases/7edee255c17101bfe50f684bd61e7f818e552205", user.stdout)

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
        verifier_text = VERIFIER.read_text(encoding="utf-8")
        journal_text = JOURNAL_INSTALLER.read_text(encoding="utf-8")

        self.assertIn('systemd-run --user --quiet --collect', user_text)
        self.assertIn('"${VERIFIER}" --policy-only', user_text)
        self.assertIn('"${VERIFIER}" --restart', user_text)
        self.assertIn("Refusing --defer-start while the managed service is already active", user_text)
        self.assertIn("Refusing to restart the managed service from inside its own cgroup", verifier_text)
        self.assertIn('systemctl --user restart "${SERVICE_NAME}"', verifier_text)
        self.assertIn("[[ ! -r /proc/device-tree/model ]] ||", journal_text)
        self.assertIn("without verified Raspberry Pi identity", journal_text)

    def test_verifier_rejects_effective_service_overrides(self) -> None:
        text = VERIFIER.read_text(encoding="utf-8")

        self.assertIn("FragmentPath", text)
        self.assertIn("DropInPaths", text)
        self.assertIn("Restart", text)
        self.assertIn("StandardOutput", text)
        self.assertIn("StandardError", text)
        self.assertIn("KillMode", text)
        self.assertIn("ExecStart", text)
        self.assertIn("Refusing effective service drop-ins", text)
        self.assertIn("Unexpected Restart policy", text)
        self.assertIn("Unexpected StandardOutput policy", text)
        self.assertIn("Unexpected StandardError policy", text)
        self.assertIn("Unexpected ExecStart", text)
        self.assertIn("NRestarts", text)
        self.assertIn("Service did not remain stable after restart", text)

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

    def test_diagnostic_surfaces_missing_system_journal_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_journalctl = Path(temp_dir) / "journalctl"
            fake_journalctl.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'Hint: You are currently not seeing messages from other users and the system.' >&2\n"
                "echo '-- No entries --'\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_journalctl.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{temp_dir}:{env['PATH']}"
            result = subprocess.run(
                ["bash", str(DIAGNOSTIC)],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("system_journal_access=unavailable", result.stdout)
        self.assertIn("kernel_journal_access=unavailable", result.stdout)
        self.assertIn("journal_boot_list=unavailable", result.stdout)
        self.assertIn("current_boot_failure_signals=unavailable", result.stdout)
        self.assertIn("previous_boot_failure_signals=unavailable", result.stdout)

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
