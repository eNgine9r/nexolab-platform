from __future__ import annotations

import shutil
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
        self.assertIn("Setup Node.js for WHATWG URL validation", self.workflow)
        self.assertIn("node-version-file: .nvmrc", self.workflow)
        self.assertIn("new URL(raw)", self.workflow)
        self.assertIn("must use canonical browser serialization", self.workflow)
        self.assertIn("must use the same LOCAL_LAN host", self.workflow)
        self.assertIn("Runtime URLs must use a LOCAL_LAN hostname", self.workflow)
        self.assertIn("Runtime URLs must use a non-global LOCAL_LAN IP address", self.workflow)
        self.assertIn("is not a valid WHATWG browser URL", self.workflow)
        self.assertIn("must use a usable destination port, not port 0", self.workflow)
        self.assertIn("must use canonical ASCII DNS labels", self.workflow)
        self.assertIn("WebSocket scheme must be", self.workflow)


    def _run_url_contract(self, dashboard: str, api: str, websocket: str) -> subprocess.CompletedProcess[str]:
        node_marker = "            node - \"$dashboard_origin\" \"$api_base_url\" \"$websocket_url\" <<'JSURL'\n"
        node_code = self.workflow.split(node_marker, 1)[1].split("\n          JSURL", 1)[0]
        node_code = "\n".join(
            line[10:] if line.startswith("          " ) else line
            for line in node_code.splitlines()
        )
        node_binary = shutil.which("node")
        if node_binary is None:
            node_version = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
            candidate = Path.home() / ".nvm" / "versions" / "node" / f"v{node_version}" / "bin" / "node"
            if not candidate.is_file():
                self.fail(f"Exact Node {node_version} is unavailable for WHATWG contract validation")
            node_binary = str(candidate)
        node_result = subprocess.run(
            [node_binary, "-", dashboard, api, websocket],
            input=node_code,
            capture_output=True,
            text=True,
            check=False,
        )
        if node_result.returncode != 0:
            return node_result

        python_marker = '          python3 - "$local_host" <<\'PYIP\'\n'
        python_code = self.workflow.split(python_marker, 1)[1].split("\n          PYIP", 1)[0]
        python_code = "\n".join(
            line[10:] if line.startswith("          " ) else line
            for line in python_code.splitlines()
        )
        return subprocess.run(
            [sys.executable, "-c", python_code, node_result.stdout],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_runtime_urls_require_canonical_same_host_local_lan_contract(self) -> None:
        valid_cases = (
            ("http://172.18.48.66:3000", "http://172.18.48.66:8082", "ws://172.18.48.66:8082/api/v1/telemetry/live"),
            ("http://nexolab.local:3000", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://xn--bcher-kva.local:3000", "http://xn--bcher-kva.local:8082", "ws://xn--bcher-kva.local:8082/api/v1/telemetry/live"),
            ("http://xn--zca.local:3000", "http://xn--zca.local:8082", "ws://xn--zca.local:8082/api/v1/telemetry/live"),
        )
        for dashboard, api, websocket in valid_cases:
            with self.subTest(dashboard=dashboard):
                result = self._run_url_contract(dashboard, api, websocket)
                self.assertEqual(result.returncode, 0, result.stderr)

        invalid_cases = (
            ("http://NEXOLAB.local:80", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local", "http://api.example.com:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local", "https://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("https://nexolab.local", "https://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local/", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("https://example.com", "https://example.com:8082", "wss://example.com:8082/api/v1/telemetry/live"),
            ("https://8.8.8.8", "https://8.8.8.8:8082", "wss://8.8.8.8:8082/api/v1/telemetry/live"),
            ("http://[fd00:0:0:0:0:0:0:1]:3000", "http://[fd00:0:0:0:0:0:0:1]:8082", "ws://[fd00:0:0:0:0:0:0:1]:8082/api/v1/telemetry/live"),
            ("http://nexoláb.local:3000", "http://nexoláb.local:8082", "ws://nexoláb.local:8082/api/v1/telemetry/live"),
            ("http://134744072:3000", "http://134744072:8082", "ws://134744072:8082/api/v1/telemetry/live"),
            ("http://0x08080808:3000", "http://0x08080808:8082", "ws://0x08080808:8082/api/v1/telemetry/live"),
            ("http://nexolab%2elocal:3000", "http://nexolab%2elocal:8082", "ws://nexolab%2elocal:8082/api/v1/telemetry/live"),
            ("http://nexolab.local:0", "http://nexolab.local:8082", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local:3000", "http://nexolab.local:0", "ws://nexolab.local:8082/api/v1/telemetry/live"),
            ("http://nexolab.local:3000", "http://nexolab.local:8082", "ws://nexolab.local:0/api/v1/telemetry/live"),
            ("http://foo\\bar.local:3000", "http://foo\\bar.local:8082", "ws://foo\\bar.local:8082/api/v1/telemetry/live"),
            ("http://foo^bar.local:3000", "http://foo^bar.local:8082", "ws://foo^bar.local:8082/api/v1/telemetry/live"),
            ("http://foo|bar.local:3000", "http://foo|bar.local:8082", "ws://foo|bar.local:8082/api/v1/telemetry/live"),
            ("http://foo_bar.local:3000", "http://foo_bar.local:8082", "ws://foo_bar.local:8082/api/v1/telemetry/live"),
            ("http://-nexolab.local:3000", "http://-nexolab.local:8082", "ws://-nexolab.local:8082/api/v1/telemetry/live"),
            ("http://xn--a.local:3000", "http://xn--a.local:8082", "ws://xn--a.local:8082/api/v1/telemetry/live"),
            ("http://xn--rv6q.local:3000", "http://xn--rv6q.local:8082", "ws://xn--rv6q.local:8082/api/v1/telemetry/live"),
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
        self.assertIn("--local-auth-refresh-token-file", self.workflow)
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

    def test_local_auth_continuity_spans_update_and_rollback(self) -> None:
        seed_index = self.workflow.index("- name: Seed local authentication continuity state")
        drill_index = self.workflow.index("- name: Prove update and rollback preserve persistent data")
        accepted_index = self.workflow.index("- name: Upload accepted offline bundle and verification evidence")
        self.assertLess(seed_index, drill_index)
        self.assertLess(drill_index, accepted_index)
        self.assertIn("python -m app.security.local_cli create-account", self.workflow)
        self.assertIn("/api/v1/auth/local/login", self.workflow)
        self.assertIn("--local-auth-refresh-token-file", self.workflow)
        self.assertIn("refresh_local_auth_session update false", self.preservation)
        self.assertIn("refresh_local_auth_session rollback true", self.preservation)
        self.assertIn("/api/v1/auth/local/refresh", self.preservation)
        self.assertIn("/api/v1/auth/session", self.preservation)
        self.assertIn("/api/v1/auth/local/logout", self.preservation)
        self.assertIn("local-auth-continuity.txt", self.preservation)

    def test_compose_contract_evidence_does_not_upload_credentials(self) -> None:
        self.assertIn('$RUNNER_TEMP/nexolab-offline-central-compose.json', self.workflow)
        self.assertIn('$RUNNER_TEMP/nexolab-offline-edge-compose.json', self.workflow)
        self.assertNotIn('$CI_ROOT/evidence/central-compose.json', self.workflow)
        self.assertNotIn('$CI_ROOT/evidence/edge-compose.json', self.workflow)

    def test_persistence_helper_preserves_local_auth_overlay(self) -> None:
        self.assertIn("--local-auth) LOCAL_AUTH=true", self.preservation)
        self.assertIn("--local-auth-refresh-token-file", self.preservation)
        self.assertIn("compose.local-auth.yaml", self.preservation)
        self.assertEqual(self.preservation.count('"${SMOKE_ARGS[@]}"'), 2)


if __name__ == "__main__":
    unittest.main()
