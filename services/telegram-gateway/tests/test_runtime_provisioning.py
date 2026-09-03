from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from app.group_identification import GroupIdentity
from app.http_transport import HttpResponse
from app.runtime_provisioning import (
    BackendAdminClient,
    RuntimeProvisioningError,
    provision_runtime,
)


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout_seconds: float) -> HttpResponse:
        self.requests.append((request, timeout_seconds))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def response(status: int, payload: dict | None = None) -> HttpResponse:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    return HttpResponse(status=status, body=body, headers={})


def admin_login() -> HttpResponse:
    return response(200, {"access_token": "a" * 32, "refresh_token": "r" * 32})


def admin_session() -> HttpResponse:
    return response(
        200,
        {
            "memberships": [
                {
                    "organization_id": "00000000-0000-0000-0000-000000000001",
                    "permissions": ["memberships.manage"],
                }
            ]
        },
    )


def target_record() -> dict[str, object]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "identity_id": "22222222-2222-2222-2222-222222222222",
        "username": "nexolab-telegram",
        "is_active": True,
        "role": "laboratory_technician",
        "granted_permissions": ["reports.read"],
        "effective_permissions": ["reports.read"],
    }


def target_login() -> HttpResponse:
    return response(200, {"access_token": "b" * 32, "refresh_token": "s" * 32})


def group() -> GroupIdentity:
    return GroupIdentity(
        bot_id=123,
        bot_username="nex0lab_bot",
        chat_id=-1001460648759,
        chat_type="supergroup",
        title="TestLAB",
        update_id=694686666,
    )


def test_fresh_provisioning_creates_least_privilege_account_and_disabled_env(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            admin_login(),
            admin_session(),
            response(200, {"items": [], "count": 0}),
            response(201, target_record()),
            target_login(),
            response(204),
            response(204),
        ]
    )

    result = provision_runtime(
        admin_username="admin",
        admin_password="admin-password-not-logged",
        backend_base_url="http://telemetry-service:8082",
        secret_dir=tmp_path,
        group=group(),
        transport=transport,
    )
    assert result.backend_username == "nexolab-telegram"
    assert result.backend_role == "laboratory_technician"
    assert result.backend_permissions == ("reports.read",)
    password_path = tmp_path / "nexolab-backend-password"
    assert password_path.exists()
    assert stat.S_IMODE(password_path.stat().st_mode) == 0o600
    password = password_path.read_text(encoding="utf-8").strip()
    assert len(password) >= 32

    env_path = tmp_path / "telegram.env"
    env_text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_ENABLED=false" in env_text
    assert "TELEGRAM_MINIAPP_ENABLED=false" in env_text
    assert "TELEGRAM_DESTINATION_CHAT_ID=-1001460648759" in env_text
    assert "https://t.me/nex0lab_bot?startapp=report_{snapshot_id}" in env_text
    assert "TELEGRAM_NEXOLAB_BACKEND_USERNAME=nexolab-telegram" in env_text
    assert password not in env_text

    create_body = json.loads(transport.requests[3][0].data.decode("utf-8"))
    assert create_body["role"] == "laboratory_technician"
    assert create_body["permissions"] == ["reports.read"]
    assert create_body["password"] == password


def test_existing_account_without_managed_secret_fails_closed(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            admin_login(),
            admin_session(),
            response(200, {"items": [target_record()], "count": 1}),
            response(204),
        ]
    )
    with pytest.raises(RuntimeProvisioningError) as exc:
        provision_runtime(
            admin_username="admin",
            admin_password="admin-password-not-logged",
            backend_base_url="http://telemetry-service:8082",
            secret_dir=tmp_path,
            group=group(),
            transport=transport,
        )

    assert exc.value.code == "backend_principal_exists_without_managed_secret"
    assert not (tmp_path / "telegram.env").exists()


def test_pending_secret_recovers_existing_account_without_rotation(tmp_path: Path) -> None:
    pending = tmp_path / ".nexolab-backend-password.pending"
    pending.write_text("pending-secret-value-12345678901234567890", encoding="utf-8")
    pending.chmod(0o600)
    transport = FakeTransport(
        [
            admin_login(),
            admin_session(),
            response(200, {"items": [target_record()], "count": 1}),
            target_login(),
            response(204),
            response(204),
        ]
    )

    provision_runtime(
        admin_username="admin",
        admin_password="admin-password-not-logged",
        backend_base_url="http://telemetry-service:8082",
        secret_dir=tmp_path,
        group=group(),
        transport=transport,
    )

    assert not pending.exists()
    assert (tmp_path / "nexolab-backend-password").read_text(encoding="utf-8").strip().startswith("pending-secret")


def test_public_backend_origin_is_rejected() -> None:
    with pytest.raises(RuntimeProvisioningError) as exc:
        BackendAdminClient("https://example.com")
    assert exc.value.code == "backend_origin_not_local"


def test_logout_failure_does_not_mask_successful_provisioning(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            admin_login(),
            admin_session(),
            response(200, {"items": [], "count": 0}),
            response(201, target_record()),
            target_login(),
            response(500, {"detail": "cleanup unavailable"}),
            response(500, {"detail": "cleanup unavailable"}),
        ]
    )
    result = provision_runtime(
        admin_username="admin",
        admin_password="admin-password-not-logged",
        backend_base_url="http://telemetry-service:8082",
        secret_dir=tmp_path,
        group=group(),
        transport=transport,
    )
    assert result.backend_permissions == ("reports.read",)
    assert (tmp_path / "nexolab-backend-password").exists()
