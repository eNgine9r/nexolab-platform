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
            "equipment_id": "K108",
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


def test_connected_channels_round_trip_with_exact_device_scope(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta
    from tests.test_live_dashboard_api import export_event, payload

    api, _ = secured_client(tmp_path, subject="dashboard-operator", roles={Role.OPERATOR})
    headers = auth_headers("dashboard-operator")
    database = api.app.state.database
    now = datetime.now(UTC)
    channel = "standalone-temperature"
    sources = [
        ("edge-a", "XJP60D-S:test:1", channel, 4.0),
        ("edge-a", "XJP60D-S:test:7", channel, 7.0),
        ("edge-b", "XJP60D-S:foreign:1", channel, 99.0),
        ("edge-a", "K108", "a-temperature-01", 3.0),
    ]
    for node, equipment, channel_id, value in sources:
        event = export_event(
            captured_at=now, channel_id=channel_id, value=value,
            node_id=node, equipment_id=equipment,
        )
        assert database.persist(event, event.normalized_payload())

    route = "/api/v1/live-dashboards"
    catalog = api.get(route + "/channel-inventory", headers=headers)
    assert catalog.json()["total"] == 2
    page = api.get(
        route + "/channel-inventory?include_observed=true&offset=1&limit=2", headers=headers
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 4
    assert page.json()["has_more"]
    legacy, observed = page.json()["items"]
    assert legacy["channel_id"] == "a-temperature-02"
    assert legacy["latest"] is None
    assert observed["channel_ref_id"] is None
    assert observed["climate_chamber_id"] is None
    assert observed["equipment_id"] == "XJP60D-S:test:1"
    last = api.get(
        route + "/channel-inventory?include_observed=true&offset=3&limit=2", headers=headers
    )
    assert [row["equipment_id"] for row in last.json()["items"]] == ["XJP60D-S:test:7"]

    request = payload(channels=[channel])
    request["items"][0].update(node_id="edge-b", equipment_id="XJP60D-S:foreign:1")
    assert api.post(route, headers=headers, json=request).status_code == 422
    request["items"][0].update(node_id="edge-a", equipment_id="XJP60D-S:test:1")
    request["items"].append({**request["items"][0], "equipment_id": "XJP60D-S:test:7"})
    created = api.post(route, headers=headers, json=request)
    assert created.status_code == 201, created.text
    dashboard_route = route + "/" + created.json()["id"]
    saved = api.get(dashboard_route, headers=headers)
    assert [
        (item["channel_ref_id"], item["node_id"], item["equipment_id"])
        for item in saved.json()["items"]
    ] == [(None, "edge-a", "XJP60D-S:test:1"), (None, "edge-a", "XJP60D-S:test:7")]

    edited = api.put(
        dashboard_route, headers={**headers, "If-Match": saved.headers["ETag"]}, json=request
    )
    assert edited.status_code == 200, edited.text
    exported = api.get(
        dashboard_route + "/telemetry.csv", headers=headers,
        params={
            "from": (now - timedelta(seconds=1)).isoformat(),
            "to": (now + timedelta(seconds=1)).isoformat(),
        },
    )
    assert exported.status_code == 200, exported.text
    assert "XJP60D-S:test:1" in exported.text and "XJP60D-S:test:7" in exported.text
    assert "foreign" not in exported.text
