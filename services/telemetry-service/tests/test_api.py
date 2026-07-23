from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app


def event(
    *,
    captured_at: datetime,
    metric: str,
    channel_id: str,
    value: float,
    equipment_id: str = "LE01MP-201",
) -> TelemetryEvent:
    unit = "V" if metric == "electrical.voltage" else "degC"
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit=unit,
        quality="valid",
        source="f-and-f-le-01mp",
        equipment_id=equipment_id,
        channel_id=channel_id,
        alarm=None,
        raw_value=int(value * 10),
        raw_status=None,
    )


def app_client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        history_max_range_days=31,
        api_max_page_size=1000,
    )
    app = create_app(settings)
    return TestClient(app), app


def test_latest_returns_one_newest_sample_per_channel_metric(tmp_path: Path) -> None:
    client, app = app_client(tmp_path)
    base = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)

    with client:
        database = app.state.database
        older = event(
            captured_at=base,
            metric="electrical.voltage",
            channel_id="201-voltage",
            value=226.1,
        )
        newer = event(
            captured_at=base + timedelta(seconds=5),
            metric="electrical.voltage",
            channel_id="201-voltage",
            value=227.3,
        )
        temperature = event(
            captured_at=base + timedelta(seconds=5),
            metric="temperature.internal",
            channel_id="201-internal-temperature",
            value=35.0,
        )
        for sample in (older, newer, temperature):
            assert database.persist(sample, sample.normalized_payload())

        response = client.get(
            "/api/v1/telemetry/latest",
            params={"node_id": "edge-01"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 2
        assert payload["next_offset"] is None
        values = {item["channel_id"]: item["value"] for item in payload["items"]}
        assert values == {
            "201-voltage": 227.3,
            "201-internal-temperature": 35.0,
        }

        filtered = client.get(
            "/api/v1/telemetry/latest",
            params={"metric": "electrical.voltage"},
        )
        assert filtered.status_code == 200
        assert filtered.json()["count"] == 1
        assert filtered.json()["items"][0]["value"] == 227.3


def test_history_is_bounded_filtered_and_deterministically_paginated(
    tmp_path: Path,
) -> None:
    client, app = app_client(tmp_path)
    base = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)

    with client:
        database = app.state.database
        for seconds, value in ((0, 226.1), (5, 227.3), (10, 228.0)):
            sample = event(
                captured_at=base + timedelta(seconds=seconds),
                metric="electrical.voltage",
                channel_id="201-voltage",
                value=value,
            )
            assert database.persist(sample, sample.normalized_payload())

        params = {
            "from": base.isoformat(),
            "to": (base + timedelta(seconds=11)).isoformat(),
            "channel_id": "201-voltage",
            "limit": 2,
        }
        first = client.get("/api/v1/telemetry/history", params=params)
        assert first.status_code == 200
        first_payload = first.json()
        assert [item["value"] for item in first_payload["items"]] == [228.0, 227.3]
        assert first_payload["next_offset"] == 2

        second = client.get(
            "/api/v1/telemetry/history",
            params={**params, "offset": 2},
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert [item["value"] for item in second_payload["items"]] == [226.1]
        assert second_payload["next_offset"] is None

        oversized = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": base.isoformat(),
                "to": (base + timedelta(days=32)).isoformat(),
            },
        )
        assert oversized.status_code == 422
        assert "31 days" in oversized.json()["detail"]

        reversed_range = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": (base + timedelta(seconds=1)).isoformat(),
                "to": base.isoformat(),
            },
        )
        assert reversed_range.status_code == 422
