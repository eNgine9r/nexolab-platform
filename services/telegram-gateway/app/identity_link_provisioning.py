from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import getpass
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any
from uuid import UUID

from app.group_identification import _call_bot_api
from app.http_transport import HttpTransport, urlopen_transport
from app.miniapp import validate_identity_links_file
from app.runtime_provisioning import (
    BackendAdminClient,
    RuntimeProvisioningError,
    _admin_organization,
    _best_effort_logout,
    _read_required_secret,
    _write_private_file,
)

_DEFAULT_BACKEND_BASE_URL = "http://172.18.48.66:8082"
_DEFAULT_SECRET_DIR = "/etc/nexolab/telegram"
_LINK_COMMAND = "/nexolab_link"
_REQUIRED_PERMISSION = "reports.read"
_MAX_TELEGRAM_USER_ID = (1 << 52) - 1


class IdentityLinkProvisioningError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    organization_id: str
    username: str
    identity_id: str


@dataclass(frozen=True, slots=True)
class IdentityLinkResult:
    bot_username: str
    nexolab_username: str
    organization_id: str
    identity_id: str
    identity_links_file: str


def resolve_target_identity(
    client: BackendAdminClient,
    *,
    access_token: str,
    organization_id: str,
    username: str,
) -> TargetIdentity:
    normalized = username.strip().casefold()
    if not normalized:
        raise IdentityLinkProvisioningError("target_username_required")
    users = client.list_users(access_token, organization_id)
    matches = [item for item in users if item.get("username") == normalized]
    if len(matches) != 1:
        raise IdentityLinkProvisioningError("target_nexolab_user_not_found")
    record = matches[0]
    if record.get("is_active") is not True:
        raise IdentityLinkProvisioningError("target_nexolab_user_inactive")
    permissions = record.get("effective_permissions")
    if not isinstance(permissions, list) or _REQUIRED_PERMISSION not in permissions:
        raise IdentityLinkProvisioningError("target_nexolab_user_missing_reports_read")
    identity_id = record.get("identity_id")
    if not isinstance(identity_id, str) or not identity_id.strip():
        raise IdentityLinkProvisioningError("target_nexolab_identity_invalid")
    return TargetIdentity(
        organization_id=organization_id,
        username=normalized,
        identity_id=identity_id.strip(),
    )


def _bot_username(token: str, transport: HttpTransport) -> str:
    me = _call_bot_api(token, "getMe", None, 10.0, transport)
    username = me.get("username") if isinstance(me, dict) else None
    if not isinstance(username, str) or not username.strip():
        raise IdentityLinkProvisioningError("telegram_bot_identity_invalid")
    return username.strip()


def find_challenge_user_id(
    updates: object,
    *,
    expected_text: str,
    min_message_date: int,
) -> int | None:
    if not isinstance(updates, list):
        return None
    matches: list[tuple[int, int]] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        message = update.get("message")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        message_date = message.get("date")
        text = message.get("text")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            continue
        chat_id = chat.get("id")
        sender_id = sender.get("id")
        if (
            chat.get("type") != "private"
            or isinstance(chat_id, bool)
            or not isinstance(chat_id, int)
            or isinstance(sender_id, bool)
            or not isinstance(sender_id, int)
            or chat_id != sender_id
        ):
            continue
        if (
            isinstance(message_date, bool)
            or not isinstance(message_date, int)
            or message_date < min_message_date
            or text != expected_text
            or sender_id <= 0
        ):
            continue
        matches.append((update_id, sender_id))
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def wait_for_private_challenge(
    *,
    token: str,
    expected_text: str,
    min_message_date: int,
    timeout_seconds: int,
    transport: HttpTransport = urlopen_transport,
    monotonic=time.monotonic,
    sleeper=time.sleep,
) -> int:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        updates = _call_bot_api(
            token,
            "getUpdates",
            {"timeout": 0, "allowed_updates": ["message"]},
            10.0,
            transport,
        )
        user_id = find_challenge_user_id(
            updates,
            expected_text=expected_text,
            min_message_date=min_message_date,
        )
        if user_id is not None:
            return user_id
        sleeper(2.0)
    raise IdentityLinkProvisioningError("telegram_private_link_challenge_timeout")


def write_identity_link(
    path: Path,
    *,
    telegram_user_id: int,
    target: TargetIdentity,
) -> None:
    if (
        isinstance(telegram_user_id, bool)
        or not isinstance(telegram_user_id, int)
        or telegram_user_id <= 0
        or telegram_user_id > _MAX_TELEGRAM_USER_ID
    ):
        raise IdentityLinkProvisioningError("telegram_user_id_invalid")
    try:
        canonical_organization = str(UUID(target.organization_id))
        canonical_identity = str(UUID(target.identity_id))
    except ValueError as error:
        raise IdentityLinkProvisioningError("nexolab_identity_link_invalid") from error
    if (
        canonical_organization != target.organization_id
        or canonical_identity != target.identity_id
        or UUID(canonical_organization).int == 0
        or UUID(canonical_identity).int == 0
    ):
        raise IdentityLinkProvisioningError("nexolab_identity_link_invalid")
    if path.exists():
        try:
            validate_identity_links_file(str(path))
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise IdentityLinkProvisioningError("identity_links_existing_file_invalid") from error
        raw_links = payload.get("links")
        if not isinstance(raw_links, list):
            raise IdentityLinkProvisioningError("identity_links_existing_file_invalid")
        links = list(raw_links)
    else:
        links = []

    exact = False
    for item in links:
        if not isinstance(item, dict):
            raise IdentityLinkProvisioningError("identity_links_existing_file_invalid")
        same_org = item.get("organization_id") == target.organization_id
        if same_org and item.get("telegram_user_id") == telegram_user_id:
            if item.get("identity_id") != target.identity_id:
                raise IdentityLinkProvisioningError("telegram_user_already_linked_elsewhere")
            exact = True
        if same_org and item.get("identity_id") == target.identity_id:
            if item.get("telegram_user_id") != telegram_user_id:
                raise IdentityLinkProvisioningError("nexolab_identity_already_linked_elsewhere")
    if not exact:
        links.append(
            {
                "telegram_user_id": telegram_user_id,
                "organization_id": target.organization_id,
                "identity_id": target.identity_id,
            }
        )
    document = {"version": 1, "links": links}
    _write_private_file(
        path,
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
    )
    try:
        validate_identity_links_file(str(path))
    except Exception as error:
        raise IdentityLinkProvisioningError("identity_links_written_file_invalid") from error


def resolve_authorized_target(
    *,
    client: BackendAdminClient,
    admin_username: str,
    admin_password: str,
    target_username: str,
) -> TargetIdentity:
    tokens = client.login(admin_username, admin_password)
    try:
        organization_id = _admin_organization(client.session(tokens.access_token))
        return resolve_target_identity(
            client,
            access_token=tokens.access_token,
            organization_id=organization_id,
            username=target_username,
        )
    finally:
        _best_effort_logout(client, tokens.refresh_token)


def provision_identity_link(
    *,
    admin_username: str,
    admin_password: str,
    target_username: str,
    backend_base_url: str,
    secret_dir: Path,
    challenge_timeout_seconds: int,
    transport: HttpTransport = urlopen_transport,
) -> IdentityLinkResult:
    client = BackendAdminClient(backend_base_url, transport=transport)
    target = resolve_authorized_target(
        client=client,
        admin_username=admin_username,
        admin_password=admin_password,
        target_username=target_username,
    )
    token = _read_required_secret(secret_dir / "bot-token", "telegram_bot_token_unavailable")
    username = _bot_username(token, transport)
    nonce = secrets.token_urlsafe(24)
    command = f"{_LINK_COMMAND} {nonce}"
    started_at = int(time.time()) - 2
    print(
        json.dumps(
            {
                "ok": True,
                "action_required": "send_private_link_challenge",
                "bot_username": username,
                "command": command,
                "timeout_seconds": challenge_timeout_seconds,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    telegram_user_id = wait_for_private_challenge(
        token=token,
        expected_text=command,
        min_message_date=started_at,
        timeout_seconds=challenge_timeout_seconds,
        transport=transport,
    )
    link_path = secret_dir / "identity-links.json"
    write_identity_link(
        link_path,
        telegram_user_id=telegram_user_id,
        target=target,
    )
    return IdentityLinkResult(
        bot_username=username,
        nexolab_username=target.username,
        organization_id=target.organization_id,
        identity_id=target.identity_id,
        identity_links_file=str(link_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Link one explicitly confirmed Telegram user to one authorized NEXOLAB identity."
    )
    parser.add_argument("--backend-base-url", default=_DEFAULT_BACKEND_BASE_URL)
    parser.add_argument("--secret-dir", default=_DEFAULT_SECRET_DIR)
    parser.add_argument("--challenge-timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "root_required"}))
        return 2
    if args.challenge_timeout_seconds < 30 or args.challenge_timeout_seconds > 600:
        print(json.dumps({"ok": False, "error": "challenge_timeout_out_of_bounds"}))
        return 2
    admin_username = input("NEXOLAB admin username: ").strip()
    admin_password = getpass.getpass("NEXOLAB admin password: ")
    target_username = input(f"NEXOLAB user to link [{admin_username}]: ").strip() or admin_username
    if not admin_username or not admin_password or not target_username:
        print(json.dumps({"ok": False, "error": "link_credentials_required"}))
        return 2
    try:
        result = provision_identity_link(
            admin_username=admin_username,
            admin_password=admin_password,
            target_username=target_username,
            backend_base_url=args.backend_base_url,
            secret_dir=Path(args.secret_dir),
            challenge_timeout_seconds=args.challenge_timeout_seconds,
        )
    except (IdentityLinkProvisioningError, RuntimeProvisioningError) as error:
        print(json.dumps({"ok": False, "error": error.code}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as error:
        code = getattr(error, "code", "identity_link_provisioning_failed")
        print(json.dumps({"ok": False, "error": str(code)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "result": asdict(result)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
