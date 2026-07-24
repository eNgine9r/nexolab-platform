from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_draft_binding_remove_and_reactivate_preserves_limit_history(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'binding-history.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": "create-binding-history"},
            json={
                "session_number": "NXL-M4-HISTORY-001",
                "title": "Binding history validation",
                "test_object": "K106 display cabinet",
                "actor_id": "operator-1",
            },
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["id"]

        preset = client.post(
            f"/api/v1/sessions/{session_id}/bindings/production",
            headers={"Idempotency-Key": "preset-binding-history"},
            json={"actor_id": "operator-1"},
        )
        assert preset.status_code == 201, preset.text
        binding = next(
            item
            for item in preset.json()["bindings"]
            if item["channel_id"] == "106-03"
        )

        limit_set = client.post(
            f"/api/v1/sessions/{session_id}/limits",
            headers={"Idempotency-Key": "limits-binding-history"},
            json={
                "actor_id": "engineer-1",
                "limits": [
                    {
                        "binding_id": binding["id"],
                        "metric": "temperature.probe",
                        "unit": "degC",
                        "lower_limit": -5.0,
                        "upper_limit": 8.0,
                    }
                ],
            },
        )
        assert limit_set.status_code == 201, limit_set.text
        historical_limit_id = limit_set.json()["limits"][0]["id"]

        removed = client.post(
            f"/api/v1/sessions/{session_id}/bindings/{binding['id']}/remove",
            headers={"Idempotency-Key": "remove-binding-history"},
            json={"actor_id": "operator-1"},
        )
        assert removed.status_code == 200, removed.text

        active_after_remove = client.get(
            f"/api/v1/sessions/{session_id}/bindings"
        )
        historical_after_remove = client.get(
            f"/api/v1/sessions/{session_id}/bindings?include_released=true"
        )
        assert active_after_remove.status_code == 200
        assert len(active_after_remove.json()) == 33
        released = next(
            item
            for item in historical_after_remove.json()
            if item["id"] == binding["id"]
        )
        assert released["activated_at"] is not None
        assert released["released_at"] is not None

        reactivated = client.post(
            f"/api/v1/sessions/{session_id}/bindings",
            headers={"Idempotency-Key": "reactivate-binding-history"},
            json={
                "actor_id": "operator-1",
                "node_id": "edge-01",
                "equipment_id": "K106",
                "channel_id": "106-03",
                "metric": "temperature.probe",
                "unit": "degC",
            },
        )
        assert reactivated.status_code == 201, reactivated.text
        assert reactivated.json()["binding"]["id"] == binding["id"]
        assert reactivated.json()["binding"]["activated_at"] is None
        assert reactivated.json()["binding"]["released_at"] is None

        active_after_reactivation = client.get(
            f"/api/v1/sessions/{session_id}/bindings"
        )
        version_one = client.get(
            f"/api/v1/sessions/{session_id}/limits?version=1"
        )
        assert len(active_after_reactivation.json()) == 34
        assert version_one.status_code == 200
        assert version_one.json()[0]["id"] == historical_limit_id
        assert version_one.json()[0]["binding_id"] == binding["id"]
