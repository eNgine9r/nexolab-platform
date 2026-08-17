from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'binding-options.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        cors_allowed_origins="http://127.0.0.1:3000",
    )
    return TestClient(create_app(settings))


def test_production_binding_options_match_server_authoritative_contract(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/api/v1/sessions/binding-options/production")

    assert response.status_code == 200, response.text
    options = response.json()
    assert len(options) == 34

    identities = {
        (
            item["node_id"],
            item["equipment_id"],
            item["channel_id"],
            item["metric"],
            item["unit"],
        )
        for item in options
    }
    assert (
        "edge-01",
        "K106",
        "106-03",
        "temperature.probe",
        "degC",
    ) in identities
    assert (
        "edge-01",
        "LE01MP-203",
        "203-active-power",
        "electrical.power.active",
        "W",
    ) in identities
    assert len(identities) == 34
    assert all(item["profile_version"] for item in options)
    assert all(item["register_key"] for item in options)
    assert all(isinstance(item["register_address"], int) for item in options)
