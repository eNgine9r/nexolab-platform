from __future__ import annotations

import json

import pytest

from app.group_identification import GroupIdentificationError, identify_group
from app.http_transport import HttpResponse


TOKEN = "123456789:test-only-bot-token"


class FakeTransport:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout_seconds: float) -> HttpResponse:
        self.requests.append((request, timeout_seconds))
        payload = self._responses.pop(0)
        return HttpResponse(status=200, body=json.dumps(payload).encode(), headers={})


def test_identify_group_returns_latest_matching_group_only() -> None:
    transport = FakeTransport(
        [
            {"ok": True, "result": {"id": 42, "username": "NexoLabBot"}},
            {
                "ok": True,
                "result": [
                    {"update_id": 10, "message": {"chat": {"id": -1001, "type": "supergroup", "title": "Other"}}},
                    {"update_id": 11, "my_chat_member": {"chat": {"id": -1002, "type": "supergroup", "title": "TestLAB"}}},
                    {"update_id": 12, "message": {"chat": {"id": -1003, "type": "group", "title": "TestLAB"}}},
                ],
            },
        ]
    )

    result = identify_group(token=TOKEN, target_title="TestLAB", transport=transport)

    assert result.bot_id == 42
    assert result.bot_username == "NexoLabBot"
    assert result.chat_id == -1003
    assert result.chat_type == "group"
    assert result.update_id == 12


def test_identify_group_fails_when_target_is_absent_with_sanitized_diagnostics() -> None:
    transport = FakeTransport(
        [
            {"ok": True, "result": {"id": 42, "username": "NexoLabBot"}},
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 20,
                        "message": {
                            "chat": {"id": -1009, "type": "supergroup", "title": "Other lab"},
                            "from": {"id": 777, "username": "must-not-leak"},
                            "text": "must-not-leak",
                        },
                    }
                ],
            },
        ]
    )

    with pytest.raises(GroupIdentificationError, match="target_group_not_found_in_pending_updates") as exc:
        identify_group(token=TOKEN, target_title="TestLAB", transport=transport)

    assert exc.value.details == {
        "diagnostics": {
            "bot_username": "NexoLabBot",
            "pending_update_count": 1,
            "observed_group_chats": [
                {"chat_id": -1009, "chat_type": "supergroup", "title": "Other lab", "update_id": 20}
            ],
        }
    }
    assert "must-not-leak" not in json.dumps(exc.value.details, ensure_ascii=False)


def test_identify_group_rejects_invalid_bot_identity() -> None:
    transport = FakeTransport(
        [
            {"ok": True, "result": {"id": "42", "username": "NexoLabBot"}},
            {
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"chat": {"id": -1001, "type": "supergroup", "title": "TestLAB"}}}
                ],
            },
        ]
    )

    with pytest.raises(GroupIdentificationError, match="telegram_identity_response_invalid"):
        identify_group(token=TOKEN, target_title="TestLAB", transport=transport)
