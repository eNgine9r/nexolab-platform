from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "infrastructure" / "compose" / "central-smoke.sh"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"


class _SmokeFixtureServer(ThreadingHTTPServer):
    protected_status = 200


class _SmokeFixtureHandler(BaseHTTPRequestHandler):
    server: _SmokeFixtureServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        if path == "/health/ready":
            self._send_json(200, {"status": "ready"})
            return
        if path == "/metrics":
            body = b"nexolab_telemetry_database_ready 1\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in {"/api/v1/telemetry/latest", "/api/v1/telemetry/history"}:
            if self.server.protected_status == 401:
                self._send_json(401, {"detail": {"code": "missing_bearer_token"}})
            else:
                self._send_json(200, {"count": 0, "items": []})
            return
        self._send_json(404, {"detail": "not found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _fake_docker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" config --quiet "*)
    exit 0
    ;;
  *" exec -T telemetry-service python - "*)
    cat >/dev/null
    exit 0
    ;;
esac
printf 'unexpected docker invocation: %s\\n' "$*" >&2
exit 77
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_smoke(*, auth_mode: str, protected_status: int) -> subprocess.CompletedProcess[str]:
    if shutil.which("curl") is None:
        raise RuntimeError("central smoke contract test requires curl")

    server = _SmokeFixtureServer(("127.0.0.1", 0), _SmokeFixtureHandler)
    server.protected_status = protected_status
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            _fake_docker(fake_bin / "docker")

            env_file = temp / ".env.central"
            env_file.write_text(
                "\n".join(
                    (
                        "CENTRAL_BIND_ADDRESS=127.0.0.1",
                        f"CENTRAL_API_PORT={server.server_port}",
                        "CORS_ALLOWED_ORIGINS=",
                        f"AUTH_MODE={auth_mode}",
                        "AUTH_DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001",
                        "CENTRAL_SMOKE_HTTP_ATTEMPTS=1",
                        "CENTRAL_SMOKE_HTTP_TIMEOUT_SECONDS=2",
                        "CENTRAL_SMOKE_HTTP_RETRY_DELAY_SECONDS=1",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            process_env = os.environ.copy()
            process_env["PATH"] = f"{fake_bin}{os.pathsep}{process_env['PATH']}"
            return subprocess.run(
                ["bash", str(SMOKE), str(env_file)],
                cwd=ROOT,
                env=process_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class CentralSmokeAuthContractTests(unittest.TestCase):
    def test_script_parses(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SMOKE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_smoke_reads_auth_mode_from_runtime_environment(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn('AUTH_MODE="$(read_env AUTH_MODE disabled)"', text)
        self.assertIn('authenticated_mode = auth_mode != "disabled"', text)
        self.assertIn('if authenticated_mode:', text)

    def test_disabled_mode_runs_positive_anonymous_rest_smoke(self) -> None:
        result = _run_smoke(auth_mode="disabled", protected_status=200)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("auth_mode=disabled", result.stdout)

    def test_disabled_mode_fails_when_anonymous_telemetry_is_rejected(self) -> None:
        result = _run_smoke(auth_mode="disabled", protected_status=401)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed after 1 attempts", result.stderr)

    def test_authenticated_mode_requires_fail_closed_anonymous_rest(self) -> None:
        result = _run_smoke(auth_mode="jwt", protected_status=401)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Central smoke protected REST: anonymous access rejected as expected",
            result.stdout,
        )
        self.assertIn("auth_mode=jwt", result.stdout)

    def test_authenticated_mode_fails_if_protected_rest_is_accidentally_public(self) -> None:
        result = _run_smoke(auth_mode="jwt", protected_status=200)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected HTTP 401", result.stderr)

    def test_authenticated_rest_smoke_expects_fail_closed_401(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn(
            'expect_http_status("/api/v1/telemetry/latest?limit=1", 401)',
            text,
        )
        self.assertIn(
            'expect_http_status(f"/api/v1/telemetry/history?{query}", 401)',
            text,
        )

    def test_authenticated_websocket_smoke_proves_missing_token_rejection(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        self.assertIn('"access_token": ""', text)
        self.assertIn('payload.get("code") != "missing_bearer_token"', text)
        self.assertIn(
            "Central smoke protected WebSocket: anonymous access rejected as expected",
            text,
        )

    def test_deployment_route_contract_still_requires_local_auth_and_admin_routes(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")

        self.assertIn("/api/v1/auth/local/login", text)
        self.assertIn("/api/v1/admin/users", text)

    def test_smoke_does_not_accept_operator_credentials(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")

        forbidden = (
            "AUTH_LOCAL_PRIVATE_KEY",
            "AUTH_LOCAL_PUBLIC_KEY",
            "NEXOLAB_LOCAL_AUTH_PASSWORD",
            "operator-password",
            "access_token_file",
        )
        for marker in forbidden:
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
