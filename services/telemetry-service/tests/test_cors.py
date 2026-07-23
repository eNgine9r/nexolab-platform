from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_cors_allows_only_configured_dashboard_origin(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cors.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        cors_allowed_origins=(
            "http://127.0.0.1:3000, http://localhost:3000/"
        ),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        allowed = client.get(
            "/health/live",
            headers={"Origin": "http://localhost:3000"},
        )
        denied = client.get(
            "/health/live",
            headers={"Origin": "https://untrusted.example"},
        )
        preflight = client.options(
            "/api/v1/telemetry/latest",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == (
        "http://localhost:3000"
    )
    assert "access-control-allow-origin" not in denied.headers
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == (
        "http://127.0.0.1:3000"
    )


def test_empty_cors_allowlist_disables_cross_origin_headers(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'cors-disabled.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        cors_allowed_origins="",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get(
            "/health/live",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
