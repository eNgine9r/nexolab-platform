from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.db import Database
from app.model_registry import register_models
from app.security.authorization import Role
from app.security.local_repository import LocalAuthRepository
from app.security.passwords import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-keys":
            _generate_keys(
                private_key_file=Path(args.private_key_file),
                public_key_file=Path(args.public_key_file),
            )
            return 0
        repository, database = _repository()
        try:
            if args.command in {"bootstrap-admin", "create-account"}:
                password = _read_password(Path(args.password_file))
                roles = (
                    {Role.ADMINISTRATOR}
                    if args.command == "bootstrap-admin"
                    else {Role(value) for value in args.role}
                )
                account = repository.bootstrap_account(
                    username=args.username,
                    password_hash=hash_password(password),
                    email=args.email,
                    display_name=args.display_name,
                    organization_id=args.organization_id,
                    organization_slug=args.organization_slug,
                    organization_name=args.organization_name,
                    roles=roles,
                )
                role_text = ",".join(sorted(role.value for role in roles))
                print(
                    f"created local account {account.username!r} "
                    f"with subject {account.subject} and roles {role_text}"
                )
                return 0
            if args.command == "reset-password":
                password = _read_password(Path(args.password_file))
                repository.reset_password(
                    username=args.username,
                    password_hash=hash_password(password),
                    now=datetime.now(UTC),
                )
                print(f"reset password and revoked sessions for {args.username!r}")
                return 0
            if args.command == "revoke-sessions":
                count = repository.revoke_all_sessions(
                    username=args.username,
                    now=datetime.now(UTC),
                )
                print(f"revoked {count} local sessions for {args.username!r}")
                return 0
        finally:
            database.dispose()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"local auth command failed: {error}", file=sys.stderr)
        return 1
    parser.error("unsupported command")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NEXOLAB local authentication administration")
    subcommands = parser.add_subparsers(dest="command", required=True)

    keys = subcommands.add_parser("generate-keys", help="generate a local RS256 signing key pair")
    keys.add_argument("--private-key-file", required=True)
    keys.add_argument("--public-key-file", required=True)

    bootstrap = subcommands.add_parser("bootstrap-admin", help="create the first local administrator")
    _add_account_arguments(bootstrap)

    create_account = subcommands.add_parser(
        "create-account",
        help="create an additional local account with explicit server roles",
    )
    _add_account_arguments(create_account)
    create_account.add_argument(
        "--role",
        action="append",
        required=True,
        choices=[role.value for role in Role],
        help="server-side role; repeat to assign multiple roles",
    )

    reset = subcommands.add_parser("reset-password", help="replace a password and revoke all sessions")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password-file", required=True)

    revoke = subcommands.add_parser("revoke-sessions", help="revoke every refresh session for an account")
    revoke.add_argument("--username", required=True)
    return parser


def _add_account_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--email")
    parser.add_argument("--display-name")
    parser.add_argument(
        "--organization-id",
        default="00000000-0000-0000-0000-000000000001",
    )
    parser.add_argument("--organization-slug", default="nexolab-lab")
    parser.add_argument("--organization-name", default="NEXOLAB Laboratory")


def _repository() -> tuple[LocalAuthRepository, Database]:
    register_models()
    settings = Settings()
    database = Database(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    return LocalAuthRepository(database), database


def _generate_keys(*, private_key_file: Path, public_key_file: Path) -> None:
    if private_key_file.resolve() == public_key_file.resolve():
        raise ValueError("private and public key paths must be different")
    for path in (private_key_file, public_key_file):
        if path.exists():
            raise ValueError(f"refusing to overwrite existing key file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key_file.write_bytes(private_bytes)
    public_key_file.write_bytes(public_bytes)
    os.chmod(private_key_file, 0o600)
    os.chmod(public_key_file, 0o644)
    print(f"created private key: {private_key_file}")
    print(f"created public key: {public_key_file}")


def _read_password(path: Path) -> str:
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value:
        raise ValueError("password file is empty")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
