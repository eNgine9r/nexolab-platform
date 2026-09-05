from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.parse import parse_qsl
from uuid import UUID

from app.backend import SnapshotClient
from app.config import Settings

_MAX_INIT_DATA_BYTES = 16 * 1024
_MAX_LINK_FILE_BYTES = 128 * 1024
_MAX_LINKS = 1000
_MAX_TELEGRAM_USER_ID = (1 << 52) - 1
_REPORT_START_RE = re.compile(r"^report_(?P<snapshot>[0-9a-fA-F-]{36})$")


class MiniAppAccessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedMiniAppInitData:
    telegram_user_id: int
    auth_date: int
    start_param: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class MiniAppIdentityLink:
    telegram_user_id: int
    organization_id: str
    identity_id: str


class MiniAppService:
    def __init__(
        self,
        settings: Settings,
        backend: SnapshotClient,
        bot_token: str,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._bot_token = bot_token
        self._clock = clock

    def get_report(self, init_data: str, *, start_hint: str | None = None) -> dict[str, Any]:
        validated = validate_init_data(
            init_data,
            bot_token=self._bot_token,
            max_age_seconds=self._settings.telegram_miniapp_init_data_max_age_seconds,
            now=self._clock(),
        )
        if start_hint is not None and start_hint.strip() != validated.start_param:
            raise MiniAppAccessError("miniapp_start_hint_mismatch")
        link = resolve_identity_link(
            self._settings.telegram_identity_links_file,
            telegram_user_id=validated.telegram_user_id,
            organization_id=self._settings.nexolab_backend_organization_id,
        )
        return self._backend.get_miniapp_snapshot(validated.snapshot_id, link.identity_id)


def validate_init_data(
    raw: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: float | None = None,
) -> ValidatedMiniAppInitData:
    encoded = raw.encode("utf-8")
    if not encoded or len(encoded) > _MAX_INIT_DATA_BYTES:
        raise MiniAppAccessError("telegram_init_data_invalid")
    if not bot_token.strip():
        raise MiniAppAccessError("telegram_init_data_configuration_invalid")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise MiniAppAccessError("telegram_init_data_invalid") from error
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise MiniAppAccessError("telegram_init_data_invalid")
    values = dict(pairs)
    supplied_hash = values.get("hash", "")
    if len(supplied_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in supplied_hash):
        raise MiniAppAccessError("telegram_init_data_invalid")
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs) if key != "hash"
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash.lower()):
        raise MiniAppAccessError("telegram_init_data_invalid")

    try:
        auth_date = int(values["auth_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise MiniAppAccessError("telegram_init_data_invalid") from error
    checked_at = int(time.time() if now is None else now)
    age = checked_at - auth_date
    if auth_date <= 0 or age < -30 or age > max_age_seconds:
        raise MiniAppAccessError("telegram_init_data_expired")

    try:
        user_payload = json.loads(values["user"])
    except (KeyError, json.JSONDecodeError) as error:
        raise MiniAppAccessError("telegram_init_data_invalid") from error
    if not isinstance(user_payload, dict):
        raise MiniAppAccessError("telegram_init_data_invalid")
    user_id = user_payload.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise MiniAppAccessError("telegram_init_data_invalid")
    if user_id <= 0 or user_id > _MAX_TELEGRAM_USER_ID:
        raise MiniAppAccessError("telegram_init_data_invalid")

    start_param = values.get("start_param", "")
    match = _REPORT_START_RE.fullmatch(start_param)
    if match is None:
        raise MiniAppAccessError("telegram_start_param_invalid")
    try:
        snapshot_id = str(UUID(match.group("snapshot")))
    except ValueError as error:
        raise MiniAppAccessError("telegram_start_param_invalid") from error
    if start_param != f"report_{snapshot_id}":
        raise MiniAppAccessError("telegram_start_param_invalid")
    return ValidatedMiniAppInitData(
        telegram_user_id=user_id,
        auth_date=auth_date,
        start_param=start_param,
        snapshot_id=snapshot_id,
    )


def validate_identity_links_file(path: str) -> None:
    _read_identity_links(path)


def resolve_identity_link(
    path: str,
    *,
    telegram_user_id: int,
    organization_id: str,
) -> MiniAppIdentityLink:
    links = _read_identity_links(path)
    normalized_organization = _uuid_text(organization_id, "miniapp_identity_links_invalid")
    for link in links:
        if link.telegram_user_id == telegram_user_id and link.organization_id == normalized_organization:
            return link
    raise MiniAppAccessError("miniapp_identity_not_linked")


def _read_identity_links(path: str) -> tuple[MiniAppIdentityLink, ...]:
    link_path = Path(path)
    try:
        if link_path.stat().st_size > _MAX_LINK_FILE_BYTES:
            raise MiniAppAccessError("miniapp_identity_links_invalid")
        payload = json.loads(link_path.read_text(encoding="utf-8"))
    except MiniAppAccessError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MiniAppAccessError("miniapp_identity_links_invalid") from error
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise MiniAppAccessError("miniapp_identity_links_invalid")
    raw_links = payload.get("links")
    if not isinstance(raw_links, list) or len(raw_links) > _MAX_LINKS:
        raise MiniAppAccessError("miniapp_identity_links_invalid")

    seen: set[tuple[int, str]] = set()
    links: list[MiniAppIdentityLink] = []
    for item in raw_links:
        if not isinstance(item, dict):
            raise MiniAppAccessError("miniapp_identity_links_invalid")
        raw_user_id = item.get("telegram_user_id")
        if isinstance(raw_user_id, bool) or not isinstance(raw_user_id, int):
            raise MiniAppAccessError("miniapp_identity_links_invalid")
        linked_user_id = raw_user_id
        if linked_user_id <= 0 or linked_user_id > _MAX_TELEGRAM_USER_ID:
            raise MiniAppAccessError("miniapp_identity_links_invalid")
        linked_organization = _uuid_text(item.get("organization_id"), "miniapp_identity_links_invalid")
        linked_identity = _uuid_text(item.get("identity_id"), "miniapp_identity_links_invalid")
        key = (linked_user_id, linked_organization)
        if key in seen:
            raise MiniAppAccessError("miniapp_identity_links_invalid")
        seen.add(key)
        links.append(
            MiniAppIdentityLink(
                telegram_user_id=linked_user_id,
                organization_id=linked_organization,
                identity_id=linked_identity,
            )
        )
    return tuple(links)


def _uuid_text(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise MiniAppAccessError(code)
    try:
        parsed = UUID(value.strip())
    except ValueError as error:
        raise MiniAppAccessError(code) from error
    if parsed.int == 0:
        raise MiniAppAccessError(code)
    return str(parsed)
