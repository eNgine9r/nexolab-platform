"""Policy tests; no live Google/OAuth/Tailscale requests or secrets."""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "inspection" / "nexolab_google_oauth_gate.py"
CFG = ROOT / "infrastructure" / "external-access" / "oauth2-proxy-google.example.cfg"
ORIGIN = "https://nexolab-edge-01.tail7f9b04.ts.net"
SPEC = importlib.util.spec_from_file_location("google_oauth_gate", MODULE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class GoogleOAuthReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = tomllib.loads(CFG.read_text(encoding="utf-8"))

    def test_hardened_example(self) -> None:
        GATE.verify(self.cfg, expected_origin=ORIGIN)

    def test_only_exact_email_allowed(self) -> None:
        GATE.verify_allowlist("approved@example.com\n", expected_email="approved@example.com")

    def test_other_email_denied(self) -> None:
        self.assert_reject_allowlist("other@example.com\n", "approved@example.com")

    def test_domain_wildcard_denied(self) -> None:
        self.assert_reject_allowlist("*@gmail.com\n", "approved@example.com")

    def test_multiple_emails_denied(self) -> None:
        self.assert_reject_allowlist("approved@example.com\nother@example.com\n", "approved@example.com")

    def test_missing_identity_denied(self) -> None:
        self.assert_reject_allowlist("", "approved@example.com")

    def test_broad_email_domain_option_denied(self) -> None:
        self.reject(email_domains=["*"])

    def test_trusted_ips_bypass_denied(self) -> None:
        self.reject(trusted_ips=["127.0.0.1/32"])

    def test_skip_auth_bypass_denied(self) -> None:
        self.reject(skip_auth_routes=["^/healthz"])

    def test_missing_one_user_allowlist_denied(self) -> None:
        self.reject(authenticated_emails_file="")

    def test_google_secret_baked_into_template_denied(self) -> None:
        self.reject(client_secret="not-for-public-repo")

    def test_client_id_baked_into_template_denied(self) -> None:
        self.reject(client_id="unexpected-public-oauth-app")

    def test_insecure_callback_denied(self) -> None:
        self.reject(redirect_url="http://nexolab-edge-01.tail7f9b04.ts.net/oauth2/callback")

    def test_wrong_callback_domain_denied(self) -> None:
        self.reject(redirect_url="https://btc-radar.tail7f9b04.ts.net/oauth2/callback")

    def test_oauth_on_wan_denied(self) -> None:
        self.reject(http_address="0.0.0.0:4180")

    def test_trusting_all_proxy_ips_denied(self) -> None:
        self.reject(trusted_proxy_ips=["0.0.0.0/0"])

    def test_unsanitized_client_ip_denied(self) -> None:
        self.reject(real_client_ip_header="X-Forwarded-For")

    def test_untrusted_upstream_denied(self) -> None:
        self.reject(upstreams=["http://127.0.0.1:8081"])

    def test_unsafely_forwarding_google_token_denied(self) -> None:
        self.reject(pass_access_token=True)

    def test_cookie_must_be_secure_denied(self) -> None:
        self.reject(cookie_secure=False)

    def test_skip_mfa_assertion_not_in_config(self) -> None:
        self.assertNotIn("mfa_verified", self.cfg)
        self.assertNotIn("amr", self.cfg)

    def test_gateway_api_routes_are_authorized_without_html_redirect(self) -> None:
        nginx = (ROOT / "infrastructure" / "external-access" / "nginx-staging.example.conf").read_text()
        for fragment in (
            "listen 127.0.0.1:18790;",
            "server_name nexolab-edge-01.tail7f9b04.ts.net;",
            "location ^~ /api/v1/",
            "location ^~ /api/device-agent/",
            "location = /_nexolab_external_auth",
            "auth_request /_nexolab_external_auth;",
            "proxy_pass http://127.0.0.1:4180/oauth2/auth;",
            "location @nexolab_sign_in",
            "return 302 /oauth2/start?rd=%2F;",
        ):
            self.assertIn(fragment, nginx)
        for api_prefix in ("location ^~ /api/v1/", "location ^~ /api/device-agent/"):
            area = nginx.split(api_prefix, 1)[1].split("location ", 1)[0]
            self.assertIn("auth_request /_nexolab_external_auth;", area)
            self.assertNotIn("error_page 401", area)
        self.assertIn("REPLACE_WITH_APPROVED_PRIVATE_API_IP", nginx)
        self.assertNotIn("listen 0.0.0.0:18790", nginx)
        self.assertNotIn("rd=https://$host$request_uri", nginx)
        self.assertNotIn("return 302 /oauth2/start?rd=$request_uri", nginx)

    def reject(self, **modifiers) -> None:
        candidate = copy.deepcopy(self.cfg)
        candidate.update(modifiers)
        with self.assertRaises(GATE.GoogleOAuthGateError):
            GATE.verify(candidate, expected_origin=ORIGIN)

    def assert_reject_allowlist(self, content: str, expected: str) -> None:
        with self.assertRaises(GATE.GoogleOAuthGateError):
            GATE.verify_allowlist(content, expected_email=expected)


if __name__ == "__main__":
    unittest.main()
