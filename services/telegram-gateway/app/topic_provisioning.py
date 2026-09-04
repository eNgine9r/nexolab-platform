from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
from typing import Any

from app.group_identification import _call_bot_api, _read_secret_file
from app.http_transport import HttpTransport, urlopen_transport

_DEFAULT_SECRET_DIR = "/etc/nexolab/telegram"
_ENV_NAME = "telegram.env"
_THREAD_KEY = "TELEGRAM_DESTINATION_MESSAGE_THREAD_ID"


class TopicProvisioningError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TopicIdentity:
    message_thread_id: int
    update_id: int


def identify_topic(
    *,
    token: str,
    target_chat_id: int,
    challenge: str,
    timeout_seconds: float = 10.0,
    transport: HttpTransport = urlopen_transport,
) -> TopicIdentity:
    updates = _call_bot_api(
        token,
        "getUpdates",
        {"timeout": 0, "allowed_updates": ["message"]},
        timeout_seconds,
        transport,
    )
    matches: list[TopicIdentity] = []
    matched_without_topic = False
    for update in updates if isinstance(updates, list) else []:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        message = update.get("message")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("id") != target_chat_id:
            continue
        if message.get("text") != challenge:
            continue
        thread_id = message.get("message_thread_id")
        if message.get("is_topic_message") is not True or isinstance(thread_id, bool) or not isinstance(thread_id, int) or thread_id <= 0:
            matched_without_topic = True
            continue
        matches.append(TopicIdentity(message_thread_id=thread_id, update_id=update_id))
    if not matches:
        if matched_without_topic:
            raise TopicProvisioningError("challenge_was_not_posted_in_forum_topic")
        raise TopicProvisioningError("topic_challenge_not_found_in_pending_updates")
    thread_ids = {item.message_thread_id for item in matches}
    if len(thread_ids) != 1:
        raise TopicProvisioningError("topic_challenge_ambiguous")
    return max(matches, key=lambda item: item.update_id)


def parse_runtime_env(path: Path) -> tuple[list[str], int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise TopicProvisioningError("telegram_runtime_env_unavailable") from error
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in values:
            raise TopicProvisioningError("telegram_runtime_env_duplicate_key")
        values[key] = value.strip()
    if values.get("TELEGRAM_ENABLED", "").lower() != "false":
        raise TopicProvisioningError("persistent_delivery_must_remain_disabled")
    chat_value = values.get("TELEGRAM_DESTINATION_CHAT_ID", "")
    if not chat_value.startswith("-") or not chat_value[1:].isdigit():
        raise TopicProvisioningError("telegram_destination_chat_id_invalid")
    return lines, int(chat_value)


def write_topic_runtime_env(path: Path, lines: list[str], message_thread_id: int) -> None:
    if isinstance(message_thread_id, bool) or not isinstance(message_thread_id, int) or message_thread_id <= 0:
        raise TopicProvisioningError("message_thread_id_invalid")
    try:
        parent_mode = path.parent.stat().st_mode & 0o777
        current = path.lstat()
    except OSError as error:
        raise TopicProvisioningError("telegram_runtime_env_unavailable") from error
    if not path.is_file() or path.is_symlink() or current.st_nlink != 1:
        raise TopicProvisioningError("telegram_runtime_env_unsafe")
    updated: list[str] = []
    inserted = False
    for raw in lines:
        if raw.startswith(f"{_THREAD_KEY}="):
            continue
        updated.append(raw)
        if raw.startswith("TELEGRAM_DESTINATION_CHAT_ID="):
            updated.append(f"{_THREAD_KEY}={message_thread_id}")
            inserted = True
    if not inserted:
        raise TopicProvisioningError("telegram_destination_chat_id_missing")
    temporary = path.with_name(f".{path.name}.topic-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join(updated) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        if (path.parent.stat().st_mode & 0o777) != parent_mode:
            raise TopicProvisioningError("telegram_secret_directory_mode_changed")
    finally:
        if temporary.exists():
            temporary.unlink()


def _challenge() -> str:
    return f"/nexolab_topic_{secrets.token_hex(8)}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture one Telegram forum topic as the protected NEXOLAB delivery destination."
    )
    parser.add_argument("--secret-dir", default=_DEFAULT_SECRET_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "root_required"}, sort_keys=True))
        return 2
    secret_dir = Path(args.secret_dir)
    env_path = secret_dir / _ENV_NAME
    try:
        lines, target_chat_id = parse_runtime_env(env_path)
        token = _read_secret_file(str(secret_dir / "bot-token"))
        challenge = _challenge()
        print(
            json.dumps(
                {
                    "ok": True,
                    "action": "post_exact_command_in_target_forum_topic",
                    "command": challenge,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        input("After posting the exact command in the intended topic, press Enter: ")
        identity = identify_topic(
            token=token,
            target_chat_id=target_chat_id,
            challenge=challenge,
            timeout_seconds=args.timeout_seconds,
        )
        write_topic_runtime_env(env_path, lines, identity.message_thread_id)
    except TopicProvisioningError as error:
        print(json.dumps({"ok": False, "error": error.code}, sort_keys=True))
        return 2
    except Exception as error:
        code = getattr(error, "code", "topic_provisioning_failed")
        print(json.dumps({"ok": False, "error": str(code)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "configured": True,
                "update_id": identity.update_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
