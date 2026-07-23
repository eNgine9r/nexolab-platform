from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_openapi_contains_versioned_telemetry_endpoints(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'openapi.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
        )
    )

    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

    paths = schema["paths"]
    assert "/api/v1/telemetry/latest" in paths
    assert "/api/v1/telemetry/history" in paths

    response_schema = schema["components"]["schemas"][
        "TelemetrySampleResponse"
    ]
    required = set(response_schema["required"])
    assert {
        "event_id",
        "captured_at",
        "value",
        "quality",
        "alarm",
        "raw_value",
        "raw_status",
    }.issubset(required)
