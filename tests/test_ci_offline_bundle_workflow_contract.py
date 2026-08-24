from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "offline-bundle.yml"
PRESERVATION = ROOT / "scripts" / "verify-offline-volume-preservation.sh"
INSTALLER = ROOT / "scripts" / "install-offline-bundle.sh"


class OfflineBundleWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.preservation = PRESERVATION.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_dispatch_exposes_bounded_recovery_inputs(self) -> None:
        for input_name in (
            "platform:",
            "runtime_source_ref:",
            "dashboard_origin:",
            "api_base_url:",
            "websocket_url:",
            "auth_provider:",
        ):
            self.assertIn(input_name, self.workflow)
        self.assertIn("- linux/amd64", self.workflow)
        self.assertIn("- linux/arm64", self.workflow)
        self.assertIn("git merge-base --is-ancestor", self.workflow)
        self.assertIn("default_ports =", self.workflow)
        self.assertIn("must use canonical browser serialization", self.workflow)
        self.assertIn("must use the same LOCAL_LAN host", self.workflow)
        self.assertIn("WebSocket scheme must be", self.workflow)


    def _run_url_contract(self, dashboard: str, api: str, websocket: str) -> subprocess.CompletedProcess[str]:
        marker = 'python3 - "$dashboard_origin" "$api_base_url" "$websocket_url" <<\'PYURL\'\n'
        code = self.workflow.split(marker, 1)[1].split('\n          PYURL', 1)[0]
        code = "\n".join(line[10:] if line.startswith("          ") else line for line in code.splitlines())
        return subprocess.run(
            [sys.executable, "-c", code, dashboard, api, websocket],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_runtime_urls_require_canonical_same_host_local_lan_contract(self) -> None:
        valid = self._run_url_contract(
            "http://172.18.48.66:3000",
            "http://172.18.48.66:8082",
            "ws://172.18.48.66:8082/api/v1/telemetry/live",
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

        invalid_cases = (
            ("http://NEXOLAB.local:80", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local", "http://api.example.com:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local", "https://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("https://nexolab.local", "https://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local/", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
        )
        for dashboard, api, websocket in invalid_cases:
            with self.subTest(dashboard=dashboard, api=api, websocket=websocket):
                result = self._run_url_contract(dashboard, api, websocket)
                self.assertNotEqual(result.returncode, 0)

    def test_pull_request_lane_keeps_existing_safe_defaults(self) -> None:
        self.assertIn('platform="linux/amd64"', self.workflow)
        self.assertIn('dashboard_origin="http://127.0.0.1:3000"', self.workflow)
        self.assertIn('api_base_url="http://127.0.0.1:8082"', self.workflow)
        self.assertIn(
            'websocket_url="ws://127.0.0.1:8082/api/v1/telemetry/live"',
            self.workflow,
        )
        self.assertIn('auth_provider="disabled"', self.workflow)

    def test_arm64_uses_qemu_and_split_runtime_tooling_build(self) -> None:
        self.assertIn("Setup QEMU for ARM64 runtime proof", self.workflow)
        self.assertIn(
            "if: ${{ steps.contract.outputs.platform == 'linux/arm64' }}",
            self.workflow,
        )
        self.assertIn('--runtime-source-ref "$RUNTIME_SOURCE_SHA"', self.workflow)
        self.assertIn("runtime-source-head.txt", self.workflow)
        self.assertIn("tooling-head.txt", self.workflow)

    def test_local_auth_is_ephemeral_and_propagated(self) -> None:
        self.assertIn("openssl genpkey -algorithm RSA", self.workflow)
        self.assertIn("$RUNNER_TEMP/nexolab-offline-local-auth", self.workflow)
        self.assertIn("install_args+=(--local-auth)", self.workflow)
        self.assertIn("preservation_args+=(--local-auth)", self.workflow)
        accepted_upload = self.workflow.split("- name: Upload accepted offline bundle and verification evidence", 1)[1]
        self.assertNotIn("RUNNER_TEMP", accepted_upload)
        self.assertNotIn("private.pem", accepted_upload)
        chmod_index = self.workflow.index('chmod 0400 "$private_key_file"')
        chown_index = self.workflow.index('sudo chown 10001:10001 "$private_key_file" "$public_key_file"')
        self.assertLess(chmod_index, chown_index)

    def test_installer_allows_runner_local_dashboard_bind_override(self) -> None:
        self.assertIn('python3 - "$MANIFEST" "$CENTRAL_ENV"', self.installer)
        self.assertIn('configured_bind = env.get("DASHBOARD_BIND_ADDRESS", "")', self.installer)
        self.assertIn('host = urlparse(manifest["dashboard"]["origin"]).hostname', self.installer)

    def test_failed_runtime_proof_does_not_publish_stageable_bundle(self) -> None:
        accepted = self.workflow.split("- name: Upload accepted offline bundle and verification evidence", 1)[1].split("- name: Upload failed validation diagnostics", 1)[0]
        failed = self.workflow.split("- name: Upload failed validation diagnostics", 1)[1]
        self.assertIn("if: ${{ success() }}", accepted)
        self.assertIn("dist/offline/*.tar.gz", accepted)
        self.assertIn("if: ${{ failure() }}", failed)
        self.assertNotIn("dist/offline/*.tar.gz", failed)
        self.assertIn("-failed-diagnostics", failed)

    def test_persistence_helper_preserves_local_auth_overlay(self) -> None:
        self.assertIn("--local-auth) LOCAL_AUTH=true", self.preservation)
        self.assertIn("compose.local-auth.yaml", self.preservation)
        self.assertEqual(self.preservation.count('"${SMOKE_ARGS[@]}"'), 2)


if __name__ == "__main__":
    unittest.main()
