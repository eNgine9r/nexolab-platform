from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_disabled_gateway_is_healthy_without_telegram_configuration(tmp_path) -> None:
    app = create_app(
        Settings(
            telegram_enabled=False,
            telegram_state_db_path=str(tmp_path / "disabled.db"),
        )
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "enabled": False, "mode": "disabled"}


def test_enabled_invalid_configuration_is_degraded_not_startup_crash(tmp_path) -> None:
    app = create_app(
        Settings(
            telegram_enabled=True,
            telegram_state_db_path=str(tmp_path / "invalid.db"),
            telegram_destination_chat_id=None,
            nexolab_backend_auth_mode="none",
        )
    )
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["error_code"] == "configuration_invalid"
