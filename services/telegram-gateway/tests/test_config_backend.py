from __future__ import annotations

import json

import pytest

from app.backend import LocalSessionAccessTokenProvider, SnapshotClient
from app.config import Settings, validate_enabled_configuration
from tests.support import ORG_ID, http_response, sample_snapshot


def enabled_settings(tmp_path, **overrides) -> Settings:
    values = {
        "telegram_enabled": True,
        "telegram_state_db_path": str(tmp_path / "outbox.db"),
        "telegram_destination_chat_id": "-1001234567890",
        "telegram_mini_app_url_template": "https://t.me/nexolab_bot/nexolab?startapp=report_{snapshot_id}",
        "nexolab_backend_auth_mode": "none",
        "nexolab_backend_unauthenticated_test_mode_enabled": True,
        "nexolab_backend_organization_id": ORG_ID,
    }
    values.update(overrides)
    return Settings(**values)


def test_disabled_configuration_needs_no_telegram_secret() -> None:
    settings = Settings(telegram_enabled=False)
    assert settings.telegram_enabled is False


def test_enabled_configuration_requires_numeric_chat_and_direct_link(tmp_path) -> None:
    validate_enabled_configuration(enabled_settings(tmp_path))
    with pytest.raises(ValueError):
        validate_enabled_configuration(enabled_settings(tmp_path, telegram_destination_chat_id="Тест лаб"))
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(tmp_path, telegram_mini_app_url_template="https://example.com/app/{snapshot_id}")
        )


def test_local_auth_reads_password_file_and_keeps_secret_out_of_errors(tmp_path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("SUPER-SECRET-PASSWORD\n", encoding="utf-8")
    calls: list[tuple[str, dict[str, object]]] = []

    def transport(request, timeout_seconds):
        body = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, body))
        return http_response(
            200,
            {
                "access_token": "a" * 32,
                "refresh_token": "r" * 32,
                "expires_in": 60,
                "refresh_expires_in": 3600,
            },
        )

    provider = LocalSessionAccessTokenProvider(
        "http://telemetry-service:8082",
        "telegram-viewer",
        str(password_file),
        timeout_seconds=3,
        transport=transport,
    )
    assert provider.get_access_token() == "a" * 32
    assert calls[0][1] == {"username": "telegram-viewer", "password": "SUPER-SECRET-PASSWORD"}


def test_snapshot_client_reads_persisted_daily_report_contract() -> None:
    snapshot = sample_snapshot()
    calls: list[dict[str, str]] = []

    class StaticToken:
        refreshable = False
        def get_access_token(self):
            return "backend-token"
        def invalidate(self):
            return None

    def transport(request, timeout_seconds):
        calls.append(dict(request.header_items()))
        item = {
            "id": snapshot.id,
            "organization_id": snapshot.organization_id,
            "profile_id": snapshot.profile_id,
            "equipment_id": snapshot.equipment_id,
            "scheduled_for": snapshot.scheduled_for.isoformat(),
            "payload_sha256": snapshot.payload_sha256,
            "payload": snapshot.payload,
        }
        return http_response(200, {"items": [item], "count": 1, "limit": 50, "offset": 0})

    client = SnapshotClient(
        "http://telemetry-service:8082",
        ORG_ID,
        StaticToken(),
        timeout_seconds=3,
        transport=transport,
    )
    result = client.list_snapshots(limit=50)
    assert result == [snapshot]
    lowered = {key.lower(): value for key, value in calls[0].items()}
    assert lowered["authorization"] == "Bearer backend-token"
    assert lowered["x-organization-id"] == ORG_ID


def test_bot_api_override_requires_explicit_test_mode(tmp_path) -> None:
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(tmp_path, telegram_bot_api_base_url="http://telegram-mock:8090")
        )
    validate_enabled_configuration(
        enabled_settings(
            tmp_path,
            telegram_bot_api_base_url="http://telegram-mock:8090",
            telegram_test_api_override_enabled=True,
        )
    )


def test_direct_link_must_use_startapp_for_snapshot_identity(tmp_path) -> None:
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(
                tmp_path,
                telegram_mini_app_url_template="https://t.me/nexolab_bot/nexolab?report={snapshot_id}",
            )
        )


def test_enabled_configuration_rejects_unauthenticated_backend_without_test_gate(tmp_path) -> None:
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(
                tmp_path,
                nexolab_backend_unauthenticated_test_mode_enabled=False,
            )
        )


def test_enabled_configuration_rejects_nil_org_and_public_backend(tmp_path) -> None:
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(tmp_path, nexolab_backend_organization_id="00000000-0000-0000-0000-000000000000")
        )
    with pytest.raises(ValueError):
        Settings(nexolab_backend_base_url="http://8.8.8.8:8082")


def test_enabled_configuration_rejects_private_chat_id(tmp_path) -> None:
    with pytest.raises(ValueError):
        validate_enabled_configuration(
            enabled_settings(tmp_path, telegram_destination_chat_id="123456789")
        )
