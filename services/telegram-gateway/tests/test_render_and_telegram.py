from __future__ import annotations

import json

import pytest

from app.http_transport import HttpTransportError
from app.render import render_report
from app.telegram import TelegramApiError, TelegramClient
from tests.support import http_response, sample_snapshot


DIRECT_LINK = "https://t.me/nexolab_bot/nexolab?startapp=report_{snapshot_id}"


def test_renderer_preserves_valid_zero_and_defrost_duration_only() -> None:
    rendered = render_report(sample_snapshot(), mini_app_url_template=DIRECT_LINK)
    assert "Tmin  +0.0 °C" in rendered.text
    assert "⚙️ Компресор: 0.0 %" in rendered.text
    assert "⚡ Енергія: 0.00 kWh / 12 год" in rendered.text
    assert "🔄 Відтайка: 0 хв" in rendered.text
    assert "Кипіння: недоступно" in rendered.text
    assert "Перегрів: недоступно" in rendered.text
    assert rendered.button_url.endswith("startapp=report_snapshot-1")


def test_renderer_bounds_untrusted_display_text_and_message_length() -> None:
    snapshot = sample_snapshot()
    snapshot.payload["identity"]["equipment_name"] = "Line 1\n" + ("X" * 500)
    rendered = render_report(snapshot, mini_app_url_template=DIRECT_LINK, max_chars=512)
    assert "Line 1 X" in rendered.text
    assert len(rendered.text) <= 512
    assert "\nX" not in rendered.text


def test_telegram_payload_uses_url_button_without_parse_mode_or_web_app() -> None:
    captured: dict[str, object] = {}

    def transport(request, timeout_seconds):
        captured["url"] = request.full_url
        captured["timeout"] = timeout_seconds
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return http_response(200, {"ok": True, "result": {"message_id": 42}})

    client = TelegramClient("https://api.telegram.test", "123:SECRET", timeout_seconds=3, transport=transport)
    result = client.send_message(chat_id="-100123", text="hello", button_url="https://t.me/bot/app?startapp=x")
    assert result.message_id == 42
    body = captured["body"]
    assert isinstance(body, dict)
    assert "parse_mode" not in body
    button = body["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Відкрити NEXOLAB", "url": "https://t.me/bot/app?startapp=x"}
    assert "web_app" not in json.dumps(body)


def test_telegram_errors_are_sanitized_and_retry_classified() -> None:
    secret = "123:VERY-SECRET-TOKEN"

    def rate_limited(request, timeout_seconds):
        return http_response(429, {"ok": False, "parameters": {"retry_after": 17}})

    client = TelegramClient("https://api.telegram.test", secret, timeout_seconds=3, transport=rate_limited)
    with pytest.raises(TelegramApiError) as caught:
        client.send_message(chat_id="-1001", text="x", button_url="https://t.me/b/a?startapp=x")
    assert caught.value.code == "telegram_rate_limited"
    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 17
    assert secret not in str(caught.value)

    def network_failure(request, timeout_seconds):
        raise HttpTransportError(f"failed URL {request.full_url}")

    client = TelegramClient("https://api.telegram.test", secret, timeout_seconds=3, transport=network_failure)
    with pytest.raises(TelegramApiError) as network_error:
        client.send_message(chat_id="-1001", text="x", button_url="https://t.me/b/a?startapp=x")
    assert network_error.value.code == "telegram_network_error"
    assert secret not in str(network_error.value)


def test_telegram_non_retryable_4xx_fails_closed() -> None:
    def bad_request(request, timeout_seconds):
        return http_response(400, {"ok": False, "error_code": 400})

    client = TelegramClient("https://api.telegram.test", "123:SECRET", timeout_seconds=3, transport=bad_request)
    with pytest.raises(TelegramApiError) as caught:
        client.send_message(chat_id="-1001", text="x", button_url="https://t.me/b/a?startapp=x")
    assert caught.value.code == "telegram_http_400"
    assert caught.value.retryable is False
