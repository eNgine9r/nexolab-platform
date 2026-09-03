from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from app.config import Settings
from app.miniapp import MiniAppAccessError, MiniAppService, resolve_identity_link, validate_init_data

BOT_TOKEN = "123456789:test-only-bot-token"
TELEGRAM_USER_ID = 987654321
ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
IDENTITY_ID = "11111111-1111-1111-1111-111111111111"
SNAPSHOT_ID = "22222222-2222-2222-2222-222222222222"
NOW = int(datetime(2026, 9, 3, 0, 0, tzinfo=UTC).timestamp())


def signed_init_data(*, auth_date: int = NOW, start_param: str | None = None) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAE-test-query",
        "start_param": start_param or f"report_{SNAPSHOT_ID}",
        "user": json.dumps(
            {"id": TELEGRAM_USER_ID, "first_name": "NEXOLAB Test"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def write_links(path: Path, links: list[dict[str, object]] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "links": links
                or [
                    {
                        "telegram_user_id": TELEGRAM_USER_ID,
                        "organization_id": ORGANIZATION_ID,
                        "identity_id": IDENTITY_ID,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_miniapp_snapshot(self, snapshot_id: str, identity_id: str) -> dict[str, object]:
        self.calls.append((snapshot_id, identity_id))
        return {"id": snapshot_id, "payload": {"schema": "refrigeration-daily-report/v1"}}


def test_valid_init_data_uses_signed_user_and_start_param() -> None:
    result = validate_init_data(
        signed_init_data(),
        bot_token=BOT_TOKEN,
        max_age_seconds=300,
        now=NOW,
    )
    assert result.telegram_user_id == TELEGRAM_USER_ID
    assert result.snapshot_id == SNAPSHOT_ID
    assert result.start_param == f"report_{SNAPSHOT_ID}"


@pytest.mark.parametrize(
    ("raw", "now", "code"),
    [
        (lambda: signed_init_data() + "&chat_type=group", NOW, "telegram_init_data_invalid"),
        (lambda: signed_init_data(auth_date=NOW - 301), NOW, "telegram_init_data_expired"),
        (lambda: signed_init_data(auth_date=NOW + 31), NOW, "telegram_init_data_expired"),
        (lambda: signed_init_data(start_param="equipment-showcase-1"), NOW, "telegram_start_param_invalid"),
    ],
)
def test_init_data_rejects_tampered_expired_future_or_non_report_start_param(raw, now: int, code: str) -> None:
    with pytest.raises(MiniAppAccessError) as exc:
        validate_init_data(raw(), bot_token=BOT_TOKEN, max_age_seconds=300, now=now)
    assert exc.value.code == code


def test_identity_link_is_exact_and_duplicate_mapping_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "identity-links.json"
    write_links(path)
    link = resolve_identity_link(
        str(path),
        telegram_user_id=TELEGRAM_USER_ID,
        organization_id=ORGANIZATION_ID,
    )
    assert link.identity_id == IDENTITY_ID

    duplicate = [
        {
            "telegram_user_id": TELEGRAM_USER_ID,
            "organization_id": ORGANIZATION_ID,
            "identity_id": IDENTITY_ID,
        },
        {
            "telegram_user_id": TELEGRAM_USER_ID,
            "organization_id": ORGANIZATION_ID,
            "identity_id": str(uuid4()),
        },
    ]
    write_links(path, duplicate)
    with pytest.raises(MiniAppAccessError) as exc:
        resolve_identity_link(
            str(path),
            telegram_user_id=TELEGRAM_USER_ID,
            organization_id=ORGANIZATION_ID,
        )
    assert exc.value.code == "miniapp_identity_links_invalid"


def test_service_uses_only_validated_start_param_and_linked_identity(tmp_path: Path) -> None:
    link_path = tmp_path / "identity-links.json"
    write_links(link_path)
    settings = Settings(
        telegram_identity_links_file=str(link_path),
        telegram_miniapp_init_data_max_age_seconds=300,
        nexolab_backend_organization_id=ORGANIZATION_ID,
    )
    backend = FakeBackend()
    service = MiniAppService(settings, backend, BOT_TOKEN, clock=lambda: NOW)  # type: ignore[arg-type]

    result = service.get_report(
        signed_init_data(),
        start_hint=f"report_{SNAPSHOT_ID}",
    )
    assert result["id"] == SNAPSHOT_ID
    assert backend.calls == [(SNAPSHOT_ID, IDENTITY_ID)]

    with pytest.raises(MiniAppAccessError) as exc:
        service.get_report(signed_init_data(), start_hint=f"report_{uuid4()}")
    assert exc.value.code == "miniapp_start_hint_mismatch"
    assert backend.calls == [(SNAPSHOT_ID, IDENTITY_ID)]


def miniapp_settings(tmp_path: Path) -> Settings:
    token_path = tmp_path / "bot-token"
    token_path.write_text(BOT_TOKEN, encoding="utf-8")
    link_path = tmp_path / "identity-links.json"
    write_links(link_path)
    return Settings(
        telegram_miniapp_enabled=True,
        telegram_bot_token_file=str(token_path),
        telegram_identity_links_file=str(link_path),
        nexolab_backend_organization_id=ORGANIZATION_ID,
        nexolab_backend_auth_mode="none",
        nexolab_backend_unauthenticated_test_mode_enabled=True,
    )


def test_http_boundary_is_no_store_and_maps_auth_failures(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    backend = FakeBackend()
    current_init_data = signed_init_data(
        auth_date=int(datetime.now(tz=UTC).timestamp())
    )
    with TestClient(create_app(miniapp_settings(tmp_path), snapshot_client=backend)) as client:  # type: ignore[arg-type]
        valid = client.post(
            "/miniapp/report",
            json={"init_data": current_init_data, "start_hint": f"report_{SNAPSHOT_ID}"},
        )
        tampered = client.post(
            "/miniapp/report",
            json={"init_data": current_init_data + "&chat_type=group"},
        )
        mismatched = client.post(
            "/miniapp/report",
            json={"init_data": current_init_data, "start_hint": f"report_{uuid4()}"},
        )

    assert valid.status_code == 200
    assert valid.headers["cache-control"] == "no-store"
    assert valid.json()["report"]["id"] == SNAPSHOT_ID
    assert tampered.status_code == 401
    assert mismatched.status_code == 403
    assert backend.calls == [(SNAPSHOT_ID, IDENTITY_ID)]


def test_http_boundary_stays_disabled_by_default() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(Settings())) as client:
        response = client.post("/miniapp/report", json={"init_data": "not-used"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "miniapp_disabled"
