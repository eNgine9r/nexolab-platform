from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"


class ControlledDeploymentAuthContractTests(unittest.TestCase):
    def test_deploy_script_parses(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(DEPLOY)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_auth_is_rejected_before_runtime_build_or_start(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        disabled_guard = text.index('AUTH_MODE=disabled is development-only')
        device_agent_build = text.index('log "Building current Device Agent image"')
        central_start = text.index('log "Starting central backend, MinIO and observability"')

        self.assertLess(disabled_guard, device_agent_build)
        self.assertLess(disabled_guard, central_start)

    def test_local_auth_overlay_requires_admin_and_login_routes(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")

        self.assertIn('LOCAL_AUTH_OVERLAY_ENABLED="false"', text)
        self.assertIn('LOCAL_AUTH_OVERLAY_ENABLED="true"', text)
        self.assertIn('"$LOCAL_AUTH_OVERLAY_ENABLED"', text)
        self.assertIn('"/api/v1/auth/local/login"', text)
        self.assertIn('"/api/v1/admin/users"', text)
        self.assertIn("if local_auth_enabled:", text)

    def test_local_auth_overlay_generates_complete_frontend_auth_contract(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")

        self.assertIn('FRONTEND_AUTH_PROVIDER="disabled"', text)
        self.assertIn('FRONTEND_AUTH_PROVIDER="local"', text)
        self.assertIn(
            'FRONTEND_ORGANIZATION_ID="$(env_get "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID)"',
            text,
        )
        self.assertIn('NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$FRONTEND_AUTH_PROVIDER', text)
        self.assertIn('NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$FRONTEND_ORGANIZATION_ID', text)

        contract_guard = text.index(
            "local-auth overlay requires NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local before dashboard build"
        )
        frontend_build = text.index('log "Installing and building current frontend"')
        self.assertLess(contract_guard, frontend_build)

    def test_frontend_build_receives_explicit_auth_contract(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        start = text.index('log "Installing and building current frontend"')
        end = text.index('log "Starting central backend, MinIO and observability"')
        build_section = text[start:end]

        self.assertIn(
            'NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="$FRONTEND_AUTH_PROVIDER"',
            build_section,
        )
        self.assertIn(
            'NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$FRONTEND_ORGANIZATION_ID"',
            build_section,
        )
        self.assertIn("NEXT_TELEMETRY_DISABLED=1 npm run build", build_section)

    def test_deployment_evidence_records_dashboard_auth_contract(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")

        self.assertIn('echo "dashboard_auth_provider=$FRONTEND_AUTH_PROVIDER"', text)
        self.assertIn('echo "dashboard_organization_id=$FRONTEND_ORGANIZATION_ID"', text)

    def test_deploy_never_generates_local_signing_keys(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")

        self.assertNotIn('ensure_secret "$CENTRAL_ENV" AUTH_LOCAL_PRIVATE_KEY', text)
        self.assertNotIn('ensure_secret "$CENTRAL_ENV" AUTH_LOCAL_PUBLIC_KEY', text)
        self.assertNotIn("openssl genrsa", text)
        self.assertNotIn("openssl genpkey", text)


if __name__ == "__main__":
    unittest.main()
