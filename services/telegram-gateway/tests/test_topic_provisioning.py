from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from app.http_transport import HttpResponse
from app.topic_provisioning import (
    TopicProvisioningError,
    identify_topic,
    parse_runtime_env,
    write_topic_runtime_env,
)

TOKEN = "123456789:test-only-bot-token"
CHAT_ID = -1001460648759
CHALLENGE = "/nexolab_topic_0123456789abcdef"


class FakeTransport:
    def __init__(self, updates: list[dict]) -> None:
        self.updates = updates

    def __call__(self, request, timeout_seconds: float) -> HttpResponse:
        return HttpResponse(
            status=200,
            body=json.dumps({"ok": True, "result": self.updates}).encode(),
            headers={},
        )


def message(update_id: int, *, thread_id: int | None, text: str = CHALLENGE, chat_id: int = CHAT_ID):
    payload = {
        "chat": {"id": chat_id, "type": "supergroup", "title": "TestLAB"},
        "text": text,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
        payload["is_topic_message"] = True
    return {"update_id": update_id, "message": payload}


def test_identify_topic_accepts_only_exact_challenge_in_expected_group() -> None:
    transport = FakeTransport(
        [
            message(10, thread_id=71, text="other"),
            message(11, thread_id=72, chat_id=-100999),
            message(12, thread_id=73),
            message(13, thread_id=73),
        ]
    )
    result = identify_topic(
        token=TOKEN,
        target_chat_id=CHAT_ID,
        challenge=CHALLENGE,
        transport=transport,
    )
    assert result.message_thread_id == 73
    assert result.update_id == 13


def test_identify_topic_fails_closed_for_general_or_ambiguous_topic() -> None:
    with pytest.raises(TopicProvisioningError, match="challenge_was_not_posted_in_forum_topic"):
        identify_topic(
            token=TOKEN,
            target_chat_id=CHAT_ID,
            challenge=CHALLENGE,
            transport=FakeTransport([message(1, thread_id=None)]),
        )
    with pytest.raises(TopicProvisioningError, match="topic_challenge_ambiguous"):
        identify_topic(
            token=TOKEN,
            target_chat_id=CHAT_ID,
            challenge=CHALLENGE,
            transport=FakeTransport([message(2, thread_id=70), message(3, thread_id=71)]),
        )


def test_runtime_env_update_preserves_delivery_off_and_hides_topic_in_result_contract(tmp_path: Path) -> None:
    tmp_path.chmod(0o750)
    path = tmp_path / "telegram.env"
    path.write_text(
        "# protected\nTELEGRAM_ENABLED=false\n"
        f"TELEGRAM_DESTINATION_CHAT_ID={CHAT_ID}\n"
        "TELEGRAM_MINIAPP_ENABLED=true\n",
        encoding="utf-8",
    )
    lines, chat_id = parse_runtime_env(path)
    assert chat_id == CHAT_ID
    write_topic_runtime_env(path, lines, 73)
    text = path.read_text(encoding="utf-8")
    assert "TELEGRAM_ENABLED=false" in text
    assert "TELEGRAM_DESTINATION_MESSAGE_THREAD_ID=73" in text
    assert text.count("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID=") == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o750


def test_runtime_env_rejects_delivery_enabled_and_invalid_chat(tmp_path: Path) -> None:
    path = tmp_path / "telegram.env"
    path.write_text("TELEGRAM_ENABLED=true\nTELEGRAM_DESTINATION_CHAT_ID=-1001\n", encoding="utf-8")
    with pytest.raises(TopicProvisioningError, match="persistent_delivery_must_remain_disabled"):
        parse_runtime_env(path)
    path.write_text("TELEGRAM_ENABLED=false\nTELEGRAM_DESTINATION_CHAT_ID=1001\n", encoding="utf-8")
    with pytest.raises(TopicProvisioningError, match="telegram_destination_chat_id_invalid"):
        parse_runtime_env(path)
