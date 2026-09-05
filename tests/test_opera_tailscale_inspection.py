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

    def test_config_rejects_plain_http_for_non_loopback_private_login_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "expected_user": "viewer@example.invalid",
                        "expected_client_ip": "100.64.0.10",
                        "expected_host": "nexolab.example.ts.net:8443",
                        "credential_file": "/tmp/credential.json",
                        "login_url": "http://172.18.48.66:8082/api/v1/auth/local/login",
                        "redirect_path": "/",
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "must use HTTPS"):
                MODULE.load_config(path)

    def test_config_accepts_https_for_non_loopback_private_login_target(self):
        MODULE.validate_local_login_url(
            "https://172.18.48.66:8443/api/v1/auth/local/login"
        )

    def test_config_accepts_https_login_target_matching_expected_host(self):
        MODULE.validate_local_login_url(
            "https://nexolab.example.ts.net:8443/api/v1/auth/local/login",
            "nexolab.example.ts.net:8443",
        )

    def test_config_rejects_https_login_target_not_matching_expected_host(self):
        with self.assertRaisesRegex(ValueError, "must match expected_host"):
            MODULE.validate_local_login_url(
                "https://other.example.ts.net:8443/api/v1/auth/local/login",
                "nexolab.example.ts.net:8443",
            )

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

    def test_handler_returns_503_when_runtime_config_cannot_be_loaded(self):
        handler = object.__new__(MODULE.InspectionLoginHandler)
        handler.path = "/inspection-login"
        handler.headers = {}
        observed = {}

        def record(status, body, content_type, **headers):
            observed.update(status=status, body=body, content_type=content_type, headers=headers)

        handler._write = record
        original = MODULE._config_from_environment
        try:
            MODULE._config_from_environment = lambda: (_ for _ in ()).throw(ValueError("bad config"))
            handler.do_GET()
        finally:
            MODULE._config_from_environment = original

        self.assertEqual(observed["status"], 503)
        self.assertEqual(observed["body"], b"Inspection login unavailable")

    def test_installer_enforces_isolated_runtime_paths_and_safe_migration(self):
        installer = (
            ROOT / "scripts" / "inspection" / "install_opera_tailscale_inspection.sh"
        ).read_text()
        self.assertIn('SERVICE_USER="nexolab-inspection"', installer)
        self.assertIn('PRIVATE_ROOT="/var/lib/nexolab-opera-inspection"', installer)
        self.assertIn('HELPER_ROOT="/usr/local/lib/nexolab-opera-inspection"', installer)
        self.assertIn('document["credential_file"]', installer)
        self.assertIn('f"https://{expected_host}/api/v1/auth/local/login"', installer)
        self.assertIn("runuser -u nexolab -- test -r", installer)
        self.assertNotIn("cat \"${CREDENTIAL_PATH}\"", installer)

    def test_systemd_socket_is_root_only_and_service_is_unprivileged(self):
        systemd = ROOT / "scripts" / "inspection" / "systemd"
        socket_unit = (systemd / "nexolab-opera-inspection-login.socket").read_text()
        service_unit = (systemd / "nexolab-opera-inspection-login.service").read_text()
        self.assertIn("SocketMode=0600", socket_unit)
        self.assertIn("SocketUser=root", socket_unit)
        self.assertIn("SocketGroup=root", socket_unit)
        self.assertIn("User=nexolab-inspection", service_unit)
        self.assertIn("Group=nexolab-inspection", service_unit)
        self.assertNotIn("User=nexolab\n", service_unit)
        self.assertIn(
            "ExecStart=/usr/bin/python3 /usr/local/lib/nexolab-opera-inspection/opera_tailscale_login.py",
            service_unit,
        )
        self.assertIn(
            "NEXOLAB_INSPECTION_CONFIG=/var/lib/nexolab-opera-inspection/config.json",
            service_unit,
        )
        self.assertIn("NoNewPrivileges=true", service_unit)
        self.assertIn("ProtectSystem=strict", service_unit)
        self.assertIn("ProtectHome=true", service_unit)


if __name__ == "__main__":
    unittest.main()
