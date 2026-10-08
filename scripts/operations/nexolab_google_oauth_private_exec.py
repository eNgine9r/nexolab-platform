#!/usr/bin/env python3
"""Draft unprivileged launcher for NEXOLAB OAuth2 Proxy.

This is never deployed by the PR. systemd LoadCredential passes the legacy
root-only credential environment file into a private credentials directory.
The launcher extracts secrets into private *ephemeral files*, NOT into process
environment variables, command-line arguments, logs or repository content.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

PROXY_BINARY = "/opt/nexolab-external/bin/oauth2-proxy"
PROXY_CONFIG = "/opt/nexolab-external/oauth2-proxy.cfg"
ID_RE = re.compile(r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com\Z")
SECRET_RE = re.compile(r"[A-Za-z0-9_-]{12,256}\Z")
KEYS = (
    "OAUTH2_PROXY_CLIENT_ID",
    "OAUTH2_PROXY_CLIENT_SECRET",
    "OAUTH2_PROXY_COOKIE_SECRET",
)


class CredentialError(ValueError):
    pass


def read_private_credentials(path: Path) -> tuple[str, str, str]:
    """Accept only the three exact expected keys, and never echo their values."""
    try:
        content = path.read_bytes()
        if len(content) > 2048:
            raise CredentialError("unexpected credential payload size")
        text = content.decode("ascii")
        lines = text.splitlines()
        pairs = [line.split("=", 1) for line in lines]
        if len(pairs) != 3 or any(len(pair) != 2 for pair in pairs):
            raise CredentialError("invalid credential format")
        if [pair[0] for pair in pairs] != list(KEYS):
            raise CredentialError("unexpected or reordered credential fields")
        client_id, client_secret, cookie_secret = (pair[1] for pair in pairs)
        if not ID_RE.fullmatch(client_id) or not SECRET_RE.fullmatch(client_secret):
            raise CredentialError("invalid Google client credential format")
        try:
            decoded_cookie = base64.b64decode(cookie_secret, validate=True)
        except ValueError:
            raise CredentialError("invalid cookie secret encoding") from None
        if len(decoded_cookie) != 32:
            raise CredentialError("cookie secret is not 32 bytes")
        return client_id, client_secret, cookie_secret
    except (OSError, UnicodeError):
        raise CredentialError("credential file cannot be read safely") from None


def _write_private_file(directory: Path, name: str, content: str) -> Path:
    target = directory / name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise CredentialError("unsafe secret destination")
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".secret-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as output:
            output.write(content.encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, target)
        return target
    finally:
        Path(tmp).unlink(missing_ok=True)


def prepare_arguments(
    credentials_directory: Path,
    runtime_directory: Path,
    *,
    proxy_binary: str = PROXY_BINARY,
    proxy_config: str = PROXY_CONFIG,
    config_test: bool = False,
) -> list[str]:
    if (
        credentials_directory.is_symlink()
        or not credentials_directory.is_dir()
        or runtime_directory.is_symlink()
        or not runtime_directory.is_dir()
    ):
        raise CredentialError("private systemd directories unavailable")
    if stat.S_IMODE(runtime_directory.stat().st_mode) != 0o700:
        raise CredentialError("private runtime directory must have mode 0700")
    allowlist = credentials_directory / "allowed-emails.txt"
    legacy_env = credentials_directory / "google-oauth.env"
    if allowlist.is_symlink() or not allowlist.is_file() or legacy_env.is_symlink():
        raise CredentialError("missing or unsafe systemd credentials")
    client_id, client_secret, cookie_secret = read_private_credentials(legacy_env)
    # The identity list and actual user email never enter argv or stdout.
    if len(allowlist.read_bytes()) > 320:
        raise CredentialError("unexpected allowlist size")
    secret_path = _write_private_file(runtime_directory, "google-client-secret", client_secret)
    cookie_path = _write_private_file(runtime_directory, "oauth-cookie-secret", cookie_secret)
    args = [
        proxy_binary,
        "--config", proxy_config,
        "--authenticated-emails-file", str(allowlist),
        "--client-id", client_id,
        "--client-secret-file", str(secret_path),
        "--cookie-secret-file", str(cookie_path),
    ]
    if config_test:
        args.append("--config-test")
    return args


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--offline-config-test", action="store_true")
    parser.add_argument("--test-binary", default=PROXY_BINARY)
    parser.add_argument("--test-config", default=PROXY_CONFIG)
    args = parser.parse_args()

    # Inert test mode requires an explicit trusted local test environment.
    # Production mode permits NO caller-supplied binary/config overrides.
    if args.run and (args.test_binary != PROXY_BINARY or args.test_config != PROXY_CONFIG):
        parser.error("cannot override live binary or configuration")
    if args.offline_config_test and os.environ.get("NEXOLAB_OFFLINE_SYNTHETIC_TEST") != "yes":
        parser.error("offline-config-test requires explicit synthetic fixture mode")
    try:
        credential_base = Path(os.environ["CREDENTIALS_DIRECTORY"])
        runtime_base = Path(os.environ["RUNTIME_DIRECTORY"])
        options = prepare_arguments(
            credential_base, runtime_base,
            proxy_binary=args.test_binary, proxy_config=args.test_config,
            config_test=args.offline_config_test,
        )
        # os.execv replaces Python, never launches an independent background job.
        # In offline-config-test OAuth2 Proxy exits without binding TCP ports.
        os.execv(options[0], options)
    except (CredentialError, KeyError, OSError) as exc:
        # Never include untrusted file contents, client secrets or paths in logs.
        print(f"DENIED: isolated Google OAuth credential handoff failed ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
