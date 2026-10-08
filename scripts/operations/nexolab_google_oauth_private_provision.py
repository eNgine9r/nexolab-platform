#!/usr/bin/env python3
"""Interactive local-only provisioning for an UNSTARTED NEXOLAB Google OAuth stage.

Never call this script through Commander, CI, a chat interface, or a logged
remote shell. It requires a real interactive terminal with no stdin redirection.
No service is started and no network interface, port or Funnel route is changed.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path

DEFAULT_DIR = Path("/etc/nexolab-external")
CLIENT_ID_RE = re.compile(r"[0-9]+-[a-zA-Z0-9_-]+\\.apps\\.googleusercontent\\.com\\Z")
SECRET_RE = re.compile(r"[a-zA-Z0-9_-]{12,256}\\Z")
EMAIL_RE = re.compile(r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\Z")
ENV_NAME = "google-oauth.env"
ALLOWLIST_NAME = "allowed-emails.txt"


class ProvisioningError(ValueError):
    pass


def validate(client_id: str, client_secret: str, email: str) -> None:
    if not CLIENT_ID_RE.fullmatch(client_id):
        raise ProvisioningError("Google Web OAuth client ID has an invalid format")
    if not SECRET_RE.fullmatch(client_secret):
        raise ProvisioningError("Google OAuth client secret has an invalid format")
    if not EMAIL_RE.fullmatch(email) or "*" in email or email != email.lower():
        raise ProvisioningError("approved email must be one lowercase Google identity")
    if len(email) > 254:
        raise ProvisioningError("email exceeds maximum length")


def _secure_directory(directory: Path) -> None:
    # Refuse pre-existing symlinks; never chmod an existing unrelated directory.
    if directory.is_symlink():
        raise ProvisioningError("refusing symlinked secrets directory")
    if directory.exists():
        if not directory.is_dir():
            raise ProvisioningError("secrets destination is not a directory")
        if stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise ProvisioningError("existing secrets directory must have mode 0700")
    else:
        directory.mkdir(mode=0o700, parents=False)


def _write_temp(directory: Path, data: bytes) -> Path:
    fd, filename = tempfile.mkstemp(prefix=".google-oauth.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(filename)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(filename).unlink(missing_ok=True)
        raise


def provision(
    directory: Path,
    *,
    client_id: str,
    client_secret: str,
    email: str,
    replace: bool = False,
) -> None:
    """Prepare root-private files, never log sensitive values or start services."""
    validate(client_id, client_secret, email)
    if directory.parent.is_symlink():
        raise ProvisioningError("refusing symlinked parent directory")
    _secure_directory(directory)
    env_path = directory / ENV_NAME
    allowlist_path = directory / ALLOWLIST_NAME

    for target in (env_path, allowlist_path):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ProvisioningError("refusing to overwrite special files or symlinks")
        if target.exists() and not replace:
            raise ProvisioningError("existing identity credentials: rotate only after review")

    # The cookie secret is generated ON DEVICE and is never sent to GitHub/chat.
    cookie_secret = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    environment = (
        f"OAUTH2_PROXY_CLIENT_ID={client_id}\\n"
        f"OAUTH2_PROXY_CLIENT_SECRET={client_secret}\\n"
        f"OAUTH2_PROXY_COOKIE_SECRET={cookie_secret}\\n"
    ).encode("ascii")
    allowlist = (email + "\\n").encode("ascii")
    env_tmp: Path | None = None
    allowlist_tmp: Path | None = None
    try:
        env_tmp = _write_temp(directory, environment)
        allowlist_tmp = _write_temp(directory, allowlist)
        os.replace(env_tmp, env_path)
        env_tmp = None
        os.replace(allowlist_tmp, allowlist_path)
        allowlist_tmp = None
        os.chmod(env_path, 0o600)
        os.chmod(allowlist_path, 0o600)
    finally:
        if env_tmp is not None:
            env_tmp.unlink(missing_ok=True)
        if allowlist_tmp is not None:
            allowlist_tmp.unlink(missing_ok=True)


def check_local_files(directory: Path) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ProvisioningError("secrets directory missing or symlinked")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ProvisioningError("secrets directory permissions are not 0700")
    for filename in (ENV_NAME, ALLOWLIST_NAME):
        p = directory / filename
        if p.is_symlink() or not p.is_file() or stat.S_IMODE(p.stat().st_mode) != 0o600:
            raise ProvisioningError(f"{filename} missing or unsafe permissions")
    data = (directory / ENV_NAME).read_text(encoding="ascii")
    names = [line.partition("=")[0] for line in data.splitlines()]
    if names != ["OAUTH2_PROXY_CLIENT_ID", "OAUTH2_PROXY_CLIENT_SECRET", "OAUTH2_PROXY_COOKIE_SECRET"]:
        raise ProvisioningError("unexpected credentials layout")
    lines = (directory / ALLOWLIST_NAME).read_text(encoding="ascii").splitlines()
    if len(lines) != 1 or not EMAIL_RE.fullmatch(lines[0]) or lines[0] != lines[0].lower():
        raise ProvisioningError("allowlist must contain exactly one email")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only inert Google OAuth staging credentials")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--check", action="store_true", help="only check file presence and permissions; never print secrets")
    args = parser.parse_args()

    if args.directory != DEFAULT_DIR:
        parser.error("production wizard writes only the fixed private /etc/nexolab-external path")
    if os.geteuid() != 0:
        parser.error("run from a private terminal with sudo, not through NEXUS logs")
    try:
        if args.check:
            check_local_files(args.directory)
            print("PASS: local files present with private permissions; credentials NOT verified with Google")
            return 0
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ProvisioningError("interactive terminal required; NEVER pass secrets via chat/Commander")
        client_id = getpass.getpass("Google Web OAuth Client ID (hidden): ").strip()
        client_secret = getpass.getpass("Google OAuth Client Secret (hidden): ").strip()
        email = input("Approved Google account (email only): ").strip().lower()
        if args.directory.exists():
            raise ProvisioningError("credentials directory already exists; refusing silent replacement")
        provision(args.directory, client_id=client_id, client_secret=client_secret, email=email)
        print("STAGED: private credentials written with mode 0600. No service or public route enabled.")
        print("GO_LIVE=BLOCKED: gateway/MFA/CI/IT approval/independent owner signoff still required.")
        return 0
    except (ProvisioningError, OSError, UnicodeError) as error:
        print(f"DENIED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
