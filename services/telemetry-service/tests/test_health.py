from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_endpoints(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'health.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["database"] == "ready"
        assert response.json()["mqtt"] == "ready"
