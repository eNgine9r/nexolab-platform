from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request

from app.http_transport import HttpTransport, HttpTransportError, urlopen_transport


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    message_id: int


class TelegramApiError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class TelegramClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float,
        transport: HttpTransport = urlopen_transport,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        button_url: str,
        message_thread_id: int | None = None,
    ) -> TelegramSendResult:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [[{"text": "Відкрити NEXOLAB", "url": button_url}]]
            },
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        request = Request(
            f"{self._base_url}/bot{self._token}/sendMessage",
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            response = self._transport(request, self._timeout_seconds)
        except HttpTransportError as error:
            raise TelegramApiError("telegram_network_error", retryable=True) from error
        if response.status == 429:
            retry_after = _retry_after(response.body)
            raise TelegramApiError(
                "telegram_rate_limited",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if response.status >= 500:
            raise TelegramApiError("telegram_server_error", retryable=True)
        if response.status < 200 or response.status >= 300:
            raise TelegramApiError(f"telegram_http_{response.status}", retryable=False)
        value = _json_object(response.body)
        if value.get("ok") is not True:
            error_code = value.get("error_code")
            if error_code == 429:
                retry_after = _retry_after(response.body)
                raise TelegramApiError(
                    "telegram_rate_limited",
                    retryable=True,
                    retry_after_seconds=retry_after,
                )
            retryable = isinstance(error_code, int) and error_code >= 500
            raise TelegramApiError("telegram_api_rejected", retryable=retryable)
        result = value.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
            raise TelegramApiError("telegram_contract_error", retryable=True)
        return TelegramSendResult(message_id=int(result["message_id"]))


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TelegramApiError("telegram_contract_error", retryable=True) from error
    if not isinstance(value, dict):
        raise TelegramApiError("telegram_contract_error", retryable=True)
    return value


def _retry_after(body: bytes) -> float | None:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    parameters = value.get("parameters")
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, bool) or not isinstance(retry_after, int | float):
        return None
    return max(0.0, float(retry_after))
