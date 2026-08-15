from __future__ import annotations

from pathlib import Path

from app.security.authorization import Role
from tests.test_live_dashboard_api import auth_headers, secured_client


def test_viewer_can_read_bounded_channel_inventory_without_latest_samples(
    tmp_path: Path,
) -> None:
    api, _ = secured_client(
        tmp_path,
        subject="inventory-viewer",
        roles={Role.VIEWER},
    )
    headers = auth_headers("inventory-viewer")

    first = api.get(
        "/api/v1/live-dashboards/channel-inventory?limit=1&offset=0",
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["has_more"] is True
    assert first.json()["items"] == [
        {
            "channel_ref_id": first.json()["items"][0]["channel_ref_id"],
            "node_id": "edge-a",
            "equipment_id": "controller-a",
            "equipment_name": "Controller a",
            "climate_chamber_id": first.json()["items"][0]["climate_chamber_id"],
            "climate_chamber_code": "KK-A",
            "climate_chamber_name": "Камера a",
            "equipment_type": "temperature_controller",
            "laboratory": None,
            "zone": None,
            "channel_id": "a-temperature-01",
            "channel_name": "Temperature 1 a",
            "metric": "temperature",
            "native_unit": "°C",
            "source": "temperature_controller",
            "quality": "unknown",
            "alarm": None,
            "latest": None,
        }
    ]

    second = api.get(
        "/api/v1/live-dashboards/channel-inventory?limit=1&offset=1",
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["has_more"] is False
    assert second.json()["items"][0]["channel_id"] == "a-temperature-02"

    assert api.get(
        "/api/v1/live-dashboards/channel-inventory?limit=501",
        headers=headers,
    ).status_code == 422
    assert api.get(
        "/api/v1/live-dashboards/channel-inventory?offset=10001",
        headers=headers,
    ).status_code == 422
