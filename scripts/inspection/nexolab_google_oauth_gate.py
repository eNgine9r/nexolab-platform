#!/usr/bin/env python3
"""Offline safety checks for NEXOLAB's unstarted Google OAuth2 Proxy example.

This verifies static configuration only; it CANNOT prove that Google enforced MFA.
No OAuth, Tailscale, production API, operator secrets or network operations occur.
"""
from __future__ import annotations

import argparse
import pathlib
import tomllib
from urllib.parse import urlparse

class GoogleOAuthGateError(ValueError):
    pass

EXPECTED_KEYS = {
    "provider", "http_address", "redirect_url", "upstreams", "reverse_proxy",
    "trusted_proxy_ips", "real_client_ip_header", "force_https",
    "authenticated_emails_file", "scope", "skip_provider_button",
    "cookie_name", "cookie_path", "cookie_secure", "cookie_httponly",
    "cookie_samesite", "cookie_expire", "cookie_refresh",
    "ssl_insecure_skip_verify", "skip_auth_preflight",
    "pass_access_token", "pass_authorization_header", "pass_user_headers",
    "set_xauthrequest", "api_routes", "request_logging", "auth_logging",
}

def verify(config: dict[str, object], *, expected_origin: str) -> None:
    """Fail closed when any risky or unreviewed OAuth option is introduced."""
    keys = set(config)
    if keys != EXPECTED_KEYS:
        raise GoogleOAuthGateError(
            f"unexpected or missing Google OAuth options: extra={sorted(keys-EXPECTED_KEYS)} missing={sorted(EXPECTED_KEYS-keys)}"
        )

    parsed = urlparse(expected_origin)
    if parsed.scheme != "https" or parsed.netloc == "" or parsed.path not in ("", "/"):
        raise GoogleOAuthGateError("expected origin must be HTTPS with no path")
    if config["provider"] != "google":
        raise GoogleOAuthGateError("Google is the only allowed provider")
    if config["redirect_url"] != expected_origin.rstrip("/") + "/oauth2/callback":
        raise GoogleOAuthGateError("Google redirect URL must exactly match the dedicated HTTPS origin")
    if config["http_address"] != "127.0.0.1:4180":
        raise GoogleOAuthGateError("OAuth2 Proxy must listen on loopback only")
    if config["upstreams"] != ["static://202"]:
        raise GoogleOAuthGateError("Google proxy must not forward untrusted upstreams")
    if config["reverse_proxy"] is not True or config["trusted_proxy_ips"] != ["127.0.0.1/32"]:
        raise GoogleOAuthGateError("proxy must trust only loopback reverse-proxy metadata")
    if config["real_client_ip_header"] != "X-Real-IP":
        raise GoogleOAuthGateError("proxy client-IP attribution must use NGINX-overwritten X-Real-IP")
    if config["authenticated_emails_file"] != "/etc/nexolab-external/allowed-emails.txt":
        raise GoogleOAuthGateError("exact operator identity allowlist file is mandatory")
    if config["scope"] != "openid email profile":
        raise GoogleOAuthGateError("Google identity requires OIDC/email scopes")
    if config["cookie_name"] != "__Host-nexolab_gateway" or config["cookie_path"] != "/":
        raise GoogleOAuthGateError("host-only secure cookie naming and path are mandatory")
    for key in ("force_https", "cookie_secure", "cookie_httponly"):
        if config[key] is not True:
            raise GoogleOAuthGateError(f"{key} must be true")
    for key in (
        "ssl_insecure_skip_verify", "skip_auth_preflight", "pass_access_token",
        "pass_authorization_header", "pass_user_headers", "set_xauthrequest",
        "request_logging", "auth_logging",
    ):
        if config[key] is not False:
            raise GoogleOAuthGateError(f"{key} must be false")
    if config["cookie_samesite"] != "lax" or config["cookie_expire"] != "2h" or config["cookie_refresh"] != "15m":
        raise GoogleOAuthGateError("cookie lifetime/SameSite policy changed")
    if config["api_routes"] != ["^/api/"] or config["skip_provider_button"] is not True:
        raise GoogleOAuthGateError("API and browser routing policy changed")


def verify_allowlist(content: str, *, expected_email: str) -> None:
    """Operator-only gate; both actual email and allowlist stay off GitHub."""
    if not isinstance(expected_email, str) or not expected_email or "\n" in expected_email:
        raise GoogleOAuthGateError("expected email is missing or malformed")
    lines = [part.strip() for part in content.splitlines() if part.strip()]
    if len(lines) != 1 or lines[0] != expected_email or "*" in lines[0]:
        raise GoogleOAuthGateError("allowlist must contain exactly one approved email")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, type=pathlib.Path)
    p.add_argument("--expected-origin", required=True)
    p.add_argument("--allowlist", type=pathlib.Path)
    p.add_argument("--expected-email-file", type=pathlib.Path)
    args = p.parse_args()
    try:
        data = tomllib.loads(args.config.read_text(encoding="utf-8"))
        verify(data, expected_origin=args.expected_origin)
        if bool(args.allowlist) != bool(args.expected_email_file):
            raise GoogleOAuthGateError("both allowlist and expected-identity file are required together")
        if args.allowlist:
            verify_allowlist(
                args.allowlist.read_text(encoding="utf-8"),
                expected_email=args.expected_email_file.read_text(encoding="utf-8").strip(),
            )
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: static Google OAuth configuration is restrictive and has no embedded credentials")
    print("PUBLICATION=BLOCKED: real Google OAuth client, protected allowlist, MFA enforcement evidence, IT approval, browser E2E and CVE gate still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
