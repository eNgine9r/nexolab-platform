from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "offline-bundle.yml"
PRESERVATION = ROOT / "scripts" / "verify-offline-volume-preservation.sh"


class OfflineBundleWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.preservation = PRESERVATION.read_text(encoding="utf-8")

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
        upload = self.workflow.split("- name: Upload offline bundle and verification evidence", 1)[1]
        self.assertNotIn("RUNNER_TEMP", upload)
        self.assertNotIn("private.pem", upload)

    def test_persistence_helper_preserves_local_auth_overlay(self) -> None:
        self.assertIn("--local-auth) LOCAL_AUTH=true", self.preservation)
        self.assertIn("compose.local-auth.yaml", self.preservation)
        self.assertEqual(self.preservation.count('"${SMOKE_ARGS[@]}"'), 2)


if __name__ == "__main__":
    unittest.main()
