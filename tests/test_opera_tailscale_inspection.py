from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "inspection" / "opera_tailscale_login.py"
SPEC = importlib.util.spec_from_file_location("opera_tailscale_login", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OperaTailscaleInspectionTests(unittest.TestCase):
    def config(self):
        return MODULE.InspectionConfig(
            expected_user="viewer@example.invalid",
            expected_client_ip="100.64.0.10",
            expected_host="nexolab.example.ts.net:8443",
            credential_file=Path("/nonexistent/credential.json"),
            login_url="http://127.0.0.1:8082/api/v1/auth/local/login",
            redirect_path="/",
        )

    def test_authorized_headers_require_exact_tailnet_identity_and_last_forwarded_ip(self):
        headers = {
            "tailscale-user-login": "viewer@example.invalid",
            "x-forwarded-for": "203.0.113.9, 100.64.0.10",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "nexolab.example.ts.net:8443",
        }
        self.assertTrue(MODULE.headers_authorized(headers, self.config()))
        headers["x-forwarded-for"] = "100.64.0.11"
        self.assertFalse(MODULE.headers_authorized(headers, self.config()))

    def test_authorized_headers_fail_closed_when_identity_header_is_missing(self):
        headers = {
            "x-forwarded-for": "100.64.0.10",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "nexolab.example.ts.net:8443",
        }
        self.assertFalse(MODULE.headers_authorized(headers, self.config()))

    def test_session_html_does_not_embed_tokens_as_plain_html(self):
        tokens = MODULE.TokenPair(
            access_token="access-sensitive-value",
            refresh_token="refresh-sensitive-value",
            expires_in=900,
        )
        body, nonce = MODULE.build_session_html(tokens, "/")
        text = body.decode("utf-8")
        self.assertNotIn(tokens.access_token, text)
        self.assertNotIn(tokens.refresh_token, text)
        self.assertIn(nonce, text)
    def test_peer_uid_reports_unix_peer_credentials(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.assertEqual(MODULE.peer_uid(left), os.getuid())
            self.assertEqual(MODULE.peer_uid(right), os.getuid())
        finally:
            left.close()
            right.close()

    def test_config_rejects_external_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "expected_user": "viewer@example.invalid",
                        "expected_client_ip": "100.64.0.10",
                        "expected_host": "nexolab.example.ts.net:8443",
                        "credential_file": "/tmp/credential.json",
                        "login_url": "http://127.0.0.1:8082/api/v1/auth/local/login",
                        "redirect_path": "https://example.invalid/",
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                MODULE.load_config(path)

    def test_config_rejects_public_login_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "expected_user": "viewer@example.invalid",
                        "expected_client_ip": "100.64.0.10",
                        "expected_host": "nexolab.example.ts.net:8443",
                        "credential_file": "/tmp/credential.json",
                        "login_url": "https://8.8.8.8/api/v1/auth/local/login",
                        "redirect_path": "/",
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                MODULE.load_config(path)

    def test_private_file_permissions_and_owner_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                MODULE.validate_private_file(path, os.geteuid())
            path.chmod(0o600)
            MODULE.validate_private_file(path, os.geteuid())
            with self.assertRaises(ValueError):
                MODULE.validate_private_file(path, os.geteuid() + 1)

    def test_systemd_socket_is_root_only_and_service_is_unprivileged(self):
        systemd = ROOT / "scripts" / "inspection" / "systemd"
        socket_unit = (systemd / "nexolab-opera-inspection-login.socket").read_text()
        service_unit = (systemd / "nexolab-opera-inspection-login.service").read_text()
        self.assertIn("SocketMode=0600", socket_unit)
        self.assertIn("SocketUser=root", socket_unit)
        self.assertIn("SocketGroup=root", socket_unit)
        self.assertIn("User=nexolab", service_unit)
        self.assertIn("NoNewPrivileges=true", service_unit)
        self.assertIn("ProtectSystem=strict", service_unit)
        self.assertIn("ProtectHome=read-only", service_unit)


if __name__ == "__main__":
    unittest.main()
