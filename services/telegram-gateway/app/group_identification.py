from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request

from pathlib import Path
from app.http_transport import HttpTransport, HttpTransportError, urlopen_transport


class GroupIdentificationError(RuntimeError):
    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class GroupIdentity:
    bot_id: int
    bot_username: str
    chat_id: int
    chat_type: str
    title: str
    update_id: int


def identify_group(
    *,
    token: str,
    target_title: str,
    timeout_seconds: float = 10.0,
    transport: HttpTransport = urlopen_transport,
) -> GroupIdentity:
    me = _call_bot_api(token, "getMe", None, timeout_seconds, transport)
    updates = _call_bot_api(
        token,
        "getUpdates",
        {"timeout": 0, "allowed_updates": ["my_chat_member", "message"]},
        timeout_seconds,
        transport,
    )
    matches: list[tuple[int, dict[str, Any]]] = []
    observed_chats: dict[tuple[int, str, str], int] = {}
    for update in updates if isinstance(updates, list) else []:
        if not isinstance(update, dict):
            continue
        chat = _extract_chat(update)
        if chat is None:
            continue
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int):
            continue
        chat_id = chat.get("id")
        chat_type = chat.get("type")
        title = chat.get("title")
        if (
            isinstance(chat_id, int)
            and not isinstance(chat_id, bool)
            and isinstance(chat_type, str)
            and chat_type in {"group", "supergroup", "channel"}
            and isinstance(title, str)
            and title
        ):
            observed_chats[(chat_id, chat_type, title)] = max(
                update_id, observed_chats.get((chat_id, chat_type, title), update_id)
            )
        if title != target_title or chat_type not in {"group", "supergroup"}:
            continue
        matches.append((update_id, chat))
    if not matches:
        bot_username = me.get("username") if isinstance(me, dict) else None
        diagnostics = {
            "bot_username": bot_username if isinstance(bot_username, str) else None,
            "pending_update_count": len(updates) if isinstance(updates, list) else 0,
            "observed_group_chats": [
                {"chat_id": chat_id, "chat_type": chat_type, "title": title, "update_id": update_id}
                for (chat_id, chat_type, title), update_id in sorted(
                    observed_chats.items(), key=lambda item: item[1], reverse=True
                )[:10]
            ],
        }
        raise GroupIdentificationError(
            "target_group_not_found_in_pending_updates",
            details={"diagnostics": diagnostics},
        )

    update_id, chat = max(matches, key=lambda item: item[0])
    bot_id = me.get("id") if isinstance(me, dict) else None
    bot_username = me.get("username") if isinstance(me, dict) else None
    chat_id = chat.get("id")
    if (
        isinstance(bot_id, bool)
        or not isinstance(bot_id, int)
        or not isinstance(bot_username, str)
        or not bot_username
        or isinstance(chat_id, bool)
        or not isinstance(chat_id, int)
        or chat_id >= 0
    ):
        raise GroupIdentificationError("telegram_identity_response_invalid")
    return GroupIdentity(
        bot_id=bot_id,
        bot_username=bot_username,
        chat_id=chat_id,
        chat_type=str(chat["type"]),
        title=target_title,
        update_id=update_id,
    )


def _extract_chat(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("my_chat_member", "message"):
        value = update.get(key)
        if isinstance(value, dict) and isinstance(value.get("chat"), dict):
            return value["chat"]
    return None


def _call_bot_api(
    token: str,
    method: str,
    payload: dict[str, Any] | None,
    timeout_seconds: float,
    transport: HttpTransport,
) -> Any:
    url = f"https://api.telegram.org/bot{quote(token, safe=':')}/{method}"
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    try:
        response = transport(request, timeout_seconds)
    except HttpTransportError as error:
        raise GroupIdentificationError("telegram_api_unreachable") from error
    try:
        parsed = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GroupIdentificationError("telegram_api_response_invalid") from error
    if response.status != 200 or not isinstance(parsed, dict) or parsed.get("ok") is not True:
        raise GroupIdentificationError("telegram_api_response_not_ok")
    return parsed.get("result")



def _read_secret_file(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise GroupIdentificationError("telegram_bot_token_unavailable") from error
    if not value:
        raise GroupIdentificationError("telegram_bot_token_empty")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Identify one Telegram group without exposing credentials.")
    parser.add_argument("--token-file", default="/etc/nexolab/telegram/bot-token")
    parser.add_argument("--title", default="TestLAB")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    token = _read_secret_file(args.token_file)
    try:
        result = identify_group(token=token, target_title=args.title, timeout_seconds=args.timeout_seconds)
    except GroupIdentificationError as error:
        payload = {"ok": False, "error": error.code, **error.details}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "group": asdict(result)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
