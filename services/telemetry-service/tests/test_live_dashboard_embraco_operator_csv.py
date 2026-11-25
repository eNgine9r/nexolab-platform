"""Bounded operator Celsius CSV export for the actual Embraco Sync Unit 2 probes."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.contracts import TelemetryEvent
from app.live_dashboard.export import _operator_embraco_probe_columns
from app.nodes.models import CentralNode
from app.security.authorization import Role
from tests.live_dashboard_test_support import ORG_A
from tests.test_live_dashboard_api import auth_headers, secured_client


BASE = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def raw_row(**changes: object) -> dict[str, object]:
    return {
        "node_id": "edge-01",
        "equipment_id": "EMBRACO-2",
        "channel_id": "2-cabinet-temperature",
        "metric": "temperature.cabinet",
        "source": "embraco-sync",
        "unit": "degC",
        "quality": "unknown",
        "value": None,
        "raw_value": 65507,
        **changes,
    }


def event(
    *,
    channel: str,
    metric: str,
    at: int,
    raw: int,
    value: float | None = None,
    quality: str = "unknown",
    node_id: str = "edge-01",
    equipment_id: str = "EMBRACO-2",
    source: str = "embraco-sync",
    unit: str = "degC",
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id=node_id,
        captured_at=BASE + timedelta(seconds=at),
        metric=metric,
        value=value,
        unit=unit,
        quality=quality,
        source=source,
        equipment_id=equipment_id,
        channel_id=channel,
        alarm=None,
        raw_value=raw,
        raw_status=None,
    )


def test_exact_operator_probe_celsius_is_a_separate_derived_column() -> None:
    assert _operator_embraco_probe_columns(raw_row()) == {
        "raw_signed_int16": "-29",
        "operator_celsius_degC": "-0.29",
        "operator_scale_degC_per_count": "0.01",
        "operator_scale_basis": "candidate_0p01_hmi_not_calibrated",
    }
    assert (
        _operator_embraco_probe_columns(
            raw_row(
                channel_id="2-evaporator-temperature",
                metric="temperature.evaporator",
                raw_value=65468,
            )
        )["operator_celsius_degC"]
        == "-0.68"
    )
    assert _operator_embraco_probe_columns(raw_row(raw_value=0))["operator_celsius_degC"] == "0"
    # Observed Raspberry Pi FC03 words while physical controller HMI displayed
    # +0.1 °C; these candidates do NOT prove HMI probe binding or calibration.
    assert (
        _operator_embraco_probe_columns(raw_row(raw_value=65514))["operator_celsius_degC"]
        == "-0.22"
    )
    assert (
        _operator_embraco_probe_columns(
            raw_row(
                channel_id="2-evaporator-temperature", metric="temperature.evaporator", raw_value=24
            )
        )["operator_celsius_degC"]
        == "0.24"
    )
    # A physically plausible condenser 3202 -> +32.02 °C is not in this
    # two-probe export policy and must NOT derive arbitrary extra channels.
    assert (
        _operator_embraco_probe_columns(
            raw_row(
                channel_id="2-condenser-temperature", metric="temperature.condenser", raw_value=3202
            )
        )
        == {}
    )
    assert (
        _operator_embraco_probe_columns(raw_row(raw_value=65535))["operator_celsius_degC"]
        == "-0.01"
    )


def test_unverified_celsius_never_crosses_device_source_metric_or_quality_boundary() -> None:
    for change in (
        {"node_id": "edge-a"},
        {"equipment_id": "EMBRACO-1"},
        {"source": "simulated"},
        {"channel_id": "2-evaporator-2-temperature", "metric": "temperature.evaporator_2"},
        {"metric": "temperature.ambient"},
        {"quality": "communication_error"},
        {"quality": "sensor_error"},
        {"unit": "°C"},
        {"value": 1.0},
        {"raw_value": -1},
        {"raw_value": 65536},
        {"raw_value": 3.5},
        {"raw_value": None},
        {"raw_value": "65507"},
        {"raw_value": True},
    ):
        assert _operator_embraco_probe_columns(raw_row(**change)) == {}, change


def test_authenticated_saved_dashboard_csv_includes_operator_scale_without_mutating_raw_history(
    tmp_path: Path,
) -> None:
    api, _ = secured_client(tmp_path, subject="csv-embraco-owner", roles={Role.OPERATOR})
    database = api.app.state.database
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=str(uuid4()),
                    organization_id=ORG_A,
                    node_id="edge-01",
                    display_name="Embraco real-node fixture",
                    state="active",
                    state_reason="test fixture",
                    clock_warning_ms=30_000,
                    clock_critical_ms=120_000,
                    clock_status="ok",
                    created_by="tests",
                    created_at=BASE,
                    updated_at=BASE,
                )
            )

    readings = [
        event(channel="2-cabinet-temperature", metric="temperature.cabinet", at=0, raw=65507),
        event(channel="2-evaporator-temperature", metric="temperature.evaporator", at=1, raw=65468),
        event(
            channel="2-compressor-speed",
            metric="compressor.speed",
            at=2,
            raw=2198,
            value=2198.0,
            quality="valid",
            unit="rpm",
        ),
        event(
            channel="2-cabinet-temperature",
            metric="temperature.cabinet",
            at=3,
            raw=65507,
            quality="communication_error",
        ),
        event(
            channel="2-cabinet-temperature",
            metric="temperature.cabinet",
            at=4,
            raw=65507,
            source="simulated",
        ),
        event(channel="2-cabinet-temperature", metric="temperature.cabinet", at=5, raw=65536),
        event(
            channel="2-cabinet-temperature",
            metric="temperature.cabinet",
            at=6,
            raw=65507,
            node_id="edge-a",
        ),
    ]
    for reading in readings:
        assert database.persist(reading, reading.normalized_payload())

    payload = {
        "name": "Температури в вітрині",
        "description": "CSV operator evidence",
        "refresh_seconds": 10,
        "time_window": "1h",
        "items": [
            {
                "node_id": "edge-01",
                "equipment_id": "EMBRACO-2",
                "channel_id": channel,
                "metric": metric,
                "visualization": "line",
                "color": None,
                "display_unit": unit,
            }
            for channel, metric, unit in [
                ("2-cabinet-temperature", "temperature.cabinet", "degC"),
                ("2-evaporator-temperature", "temperature.evaporator", "degC"),
                ("2-compressor-speed", "compressor.speed", "rpm"),
            ]
        ],
    }
    headers = auth_headers("csv-embraco-owner")
    created = api.post("/api/v1/live-dashboards", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    path = f"/api/v1/live-dashboards/{dashboard_id}/telemetry.csv"
    params = {
        "from": (BASE - timedelta(seconds=1)).isoformat(),
        "to": (BASE + timedelta(seconds=10)).isoformat(),
        "timezone": "Europe/Kiev",
    }
    assert api.get(path, headers={"X-Organization-ID": ORG_A}, params=params).status_code == 401
    foreign = api.get(
        path,
        headers={
            "Authorization": headers["Authorization"],
            "X-Organization-ID": "22222222-2222-2222-2222-222222222222",
        },
        params=params,
    )
    assert foreign.status_code == 403
    result = api.get(path, headers=headers, params=params)
    assert result.status_code == 200, result.text
    output = list(csv.DictReader(io.StringIO(result.text)))
    assert (
        len(output) == 6
    )  # foreign node's matching series excluded; all local source rows preserved
    assert [(r["channel"], r["raw_value"]) for r in output[:3]] == [
        ("2-cabinet-temperature", "65507"),
        ("2-evaporator-temperature", "65468"),
        ("2-compressor-speed", ""),
    ]
    assert [(r["value"], r["quality"], r["operator_celsius_degC"]) for r in output[:3]] == [
        ("", "unknown", "-0.29"),
        ("", "unknown", "-0.68"),
        ("2198", "valid", ""),
    ]
    assert [r["raw_signed_int16"] for r in output[:3]] == ["-29", "-68", ""]
    assert [r["operator_scale_basis"] for r in output[:3]] == [
        "candidate_0p01_hmi_not_calibrated",
        "candidate_0p01_hmi_not_calibrated",
        "",
    ]
    assert all(r["operator_celsius_degC"] == "" for r in output[3:])
    assert [r["raw_value"] for r in output[3:]] == ["65507", "", "65536"]
    assert "+02:00" in output[0]["timestamp_local"]
    assert all(r["event_id"] for r in output)
    # Neither the repository nor storage had its `null/unknown` source evidence updated.
    with Session(database.engine) as session:
        from app.db import TelemetrySample

        stored = session.get(TelemetrySample, 1)
        assert stored is not None and stored.quality == "unknown" and stored.value is None
        assert stored.raw_value == 65507
