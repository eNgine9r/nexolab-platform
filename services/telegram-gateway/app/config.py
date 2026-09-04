from __future__ import annotations

from pathlib import Path
import ipaddress
import re
from uuid import UUID
from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_TELEGRAM_PRODUCTION_API = "https://api.telegram.org"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "nexolab-telegram-gateway"
    log_level: str = "INFO"
    telegram_enabled: bool = False
    telegram_miniapp_enabled: bool = False
    telegram_miniapp_init_data_max_age_seconds: int = Field(default=300, ge=30, le=3600)
    telegram_identity_links_file: str = "/run/secrets/telegram/identity-links.json"
    telegram_state_db_path: str = "data/telegram-delivery/outbox.db"
    telegram_poll_interval_seconds: float = Field(default=30.0, ge=2.0, le=3600.0)
    telegram_snapshot_page_size: int = Field(default=100, ge=1, le=200)
    telegram_snapshot_max_pages: int = Field(default=20, ge=1, le=100)
    telegram_max_deliveries_per_run: int = Field(default=100, ge=1, le=1000)
    telegram_max_snapshot_age_hours: int = Field(default=36, ge=1, le=168)
    telegram_max_attempts: int = Field(default=6, ge=1, le=50)
    telegram_retry_initial_seconds: float = Field(default=5.0, ge=0.1, le=3600.0)
    telegram_retry_max_seconds: float = Field(default=300.0, ge=0.1, le=86_400.0)
    telegram_stale_sending_seconds: float = Field(default=60.0, ge=5.0, le=86_400.0)
    telegram_request_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    telegram_bot_api_base_url: str = _TELEGRAM_PRODUCTION_API
    telegram_test_api_override_enabled: bool = False
    telegram_bot_token_file: str = "/run/secrets/telegram/bot-token"
    telegram_destination_chat_id: str | None = None
    telegram_destination_message_thread_id: int | None = Field(default=None, ge=1)
    telegram_mini_app_url_template: str | None = None
    telegram_message_max_chars: int = Field(default=3900, ge=512, le=4096)

    nexolab_backend_base_url: str = "http://telemetry-service:8082"
    nexolab_backend_organization_id: str = ""
    nexolab_backend_auth_mode: Literal["none", "bearer", "local"] = "local"
    nexolab_backend_username: str | None = None
    nexolab_backend_password_file: str | None = "/run/secrets/telegram/nexolab-backend-password"
    nexolab_backend_bearer_token_file: str | None = None
    nexolab_backend_unauthenticated_test_mode_enabled: bool = False

    @field_validator("telegram_destination_message_thread_id", mode="before")
    @classmethod
    def normalize_optional_message_thread_id(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID must be a positive integer")
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_delivery_configuration(self) -> "Settings":
        if self.telegram_retry_max_seconds < self.telegram_retry_initial_seconds:
            raise ValueError(
                "TELEGRAM_RETRY_MAX_SECONDS must be greater than or equal to "
                "TELEGRAM_RETRY_INITIAL_SECONDS"
            )
        _validate_local_backend_url(self.nexolab_backend_base_url)
        if not self.telegram_state_db_path.strip():
            raise ValueError("TELEGRAM_STATE_DB_PATH must not be empty")
        return self


def validate_miniapp_configuration(settings: Settings) -> None:
    if not settings.telegram_bot_token_file.strip():
        raise ValueError("TELEGRAM_BOT_TOKEN_FILE is required for Mini App authentication")
    if not settings.telegram_identity_links_file.strip():
        raise ValueError("TELEGRAM_IDENTITY_LINKS_FILE is required for Mini App authorization")
    _validate_backend_configuration(settings)


def validate_enabled_configuration(settings: Settings) -> None:
    normalized_bot_api = settings.telegram_bot_api_base_url.strip().rstrip("/")
    is_override = normalized_bot_api != _TELEGRAM_PRODUCTION_API
    if is_override and not settings.telegram_test_api_override_enabled:
        raise ValueError("TELEGRAM_BOT_API_BASE_URL override requires explicit test mode")
    _validate_base_url(
        normalized_bot_api,
        field="TELEGRAM_BOT_API_BASE_URL",
        allow_http=settings.telegram_test_api_override_enabled,
    )
    required = {
        "TELEGRAM_DESTINATION_CHAT_ID": settings.telegram_destination_chat_id,
        "TELEGRAM_MINI_APP_URL_TEMPLATE": settings.telegram_mini_app_url_template,
        "TELEGRAM_BOT_TOKEN_FILE": settings.telegram_bot_token_file,
    }
    missing = [name for name, value in required.items() if value is None or not str(value).strip()]
    if missing:
        raise ValueError("Telegram delivery configuration is incomplete")
    assert settings.telegram_destination_chat_id is not None
    if not _group_chat_id(settings.telegram_destination_chat_id):
        raise ValueError("TELEGRAM_DESTINATION_CHAT_ID must be a negative Telegram group/supergroup chat ID")
    assert settings.telegram_mini_app_url_template is not None
    _validate_mini_app_template(settings.telegram_mini_app_url_template)
    _validate_backend_configuration(settings)


def _validate_backend_configuration(settings: Settings) -> None:
    _validate_organization_id(settings.nexolab_backend_organization_id)
    if (
        settings.nexolab_backend_auth_mode == "none"
        and not settings.nexolab_backend_unauthenticated_test_mode_enabled
    ):
        raise ValueError("Unauthenticated NEXOLAB backend access is test-only")
    if settings.nexolab_backend_auth_mode == "local":
        if not settings.nexolab_backend_username or not settings.nexolab_backend_username.strip():
            raise ValueError("NEXOLAB_BACKEND_USERNAME is required in local auth mode")
        if not settings.nexolab_backend_password_file or not settings.nexolab_backend_password_file.strip():
            raise ValueError("NEXOLAB_BACKEND_PASSWORD_FILE is required in local auth mode")
    if settings.nexolab_backend_auth_mode == "bearer":
        if not settings.nexolab_backend_bearer_token_file or not settings.nexolab_backend_bearer_token_file.strip():
            raise ValueError("NEXOLAB_BACKEND_BEARER_TOKEN_FILE is required in bearer auth mode")


def _group_chat_id(value: str) -> bool:
    normalized = value.strip()
    return normalized.startswith("-") and len(normalized) > 1 and normalized[1:].isdigit()


def _validate_base_url(value: str, *, field: str, allow_http: bool) -> None:
    parsed = urlparse(value.strip())
    allowed_schemes = {"https"}
    if allow_http:
        allowed_schemes.add("http")
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute {'/'.join(sorted(allowed_schemes))} URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{field} must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError(f"{field} must be a service origin without a path")


def _validate_local_backend_url(value: str) -> None:
    _validate_base_url(value, field="NEXOLAB_BACKEND_BASE_URL", allow_http=True)
    host = urlparse(value.strip()).hostname
    assert host is not None
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host) is None:
            raise ValueError(
                "NEXOLAB_BACKEND_BASE_URL must use loopback, private IP, or a local single-label service name"
            )
    else:
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise ValueError("NEXOLAB_BACKEND_BASE_URL must not target a public IP")


def _validate_organization_id(value: str) -> None:
    try:
        organization_id = UUID(value.strip())
    except (AttributeError, ValueError) as error:
        raise ValueError("NEXOLAB_BACKEND_ORGANIZATION_ID must be a valid UUID") from error
    if organization_id.int == 0:
        raise ValueError("NEXOLAB_BACKEND_ORGANIZATION_ID must not be the nil UUID")


def _validate_mini_app_template(value: str) -> None:
    if value.count("{snapshot_id}") != 1:
        raise ValueError("TELEGRAM_MINI_APP_URL_TEMPLATE must contain exactly one {snapshot_id}")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"t.me", "telegram.me"}:
        raise ValueError("TELEGRAM_MINI_APP_URL_TEMPLATE must be a Telegram HTTPS direct link")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("TELEGRAM_MINI_APP_URL_TEMPLATE must not contain credentials or a fragment")
    if not parsed.path.strip("/"):
        raise ValueError("TELEGRAM_MINI_APP_URL_TEMPLATE must include a bot/app path")
    startapp = parse_qs(parsed.query, keep_blank_values=True).get("startapp")
    if startapp != ["report_{snapshot_id}"]:
        raise ValueError(
            "TELEGRAM_MINI_APP_URL_TEMPLATE startapp must be exactly report_{snapshot_id}"
        )


def read_secret_file(path: str, *, label: str) -> str:
    secret_path = Path(path)
    try:
        value = secret_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"{label} secret file is unavailable") from error
    if not value:
        raise ValueError(f"{label} secret file is empty")
    return value
