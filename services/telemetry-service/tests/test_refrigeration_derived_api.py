from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.refrigeration.derived_api import create_derived_read_router
from tests.test_refrigeration_derived_read import ORG, T0, _role, _sample, _scope


def _client(service) -> TestClient:
    app = FastAPI()
    app.include_router(create_derived_read_router(service, default_organization_id=ORG))
    return TestClient(app)


def test_derived_endpoint_returns_typed_kernel_provenance(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    event_id = _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=10),
        value=2.5,
        event_suffix=101,
    )

    response = _client(service).get(
        f"/api/v1/refrigeration/circuits/{circuit.id}/derived",
        params={
            "observation_at": (T0 + timedelta(seconds=20)).isoformat(),
            "metric": "refrigeration.temperature.evaporation_saturation",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["circuit_id"] == circuit.id
    assert len(payload["metrics"]) == 1
    item = payload["metrics"][0]
    assert item["availability"] == "available"
    assert item["reason_codes"] == []
    kernel = item["kernel_result"]
    assert kernel["formula_version"] == "refrigeration-derived/v1"
    assert kernel["context"]["calculation_enabled"] is True
    assert kernel["policy"]["maximum_age_ms"] == 60_000
    assert kernel["sources"][0]["event_id"] == event_id
    assert kernel["sources"][0]["acquisition_source_id"] == source.id
    assert kernel["provider"]["provider_profile"] == "coolprop-heos/8.0.0"


def test_derived_endpoint_rejects_naive_timestamp_and_unknown_metric(
    tmp_path: Path,
) -> None:
    *_, service = _scope(tmp_path)
    client = _client(service)
    naive = client.get(
        "/api/v1/refrigeration/circuits/not-used/derived",
        params={"observation_at": "2026-09-07T20:00:00"},
    )
    assert naive.status_code == 422

    unknown = client.get(
        "/api/v1/refrigeration/circuits/not-used/derived",
        params={
            "observation_at": T0.isoformat(),
            "metric": "refrigeration.capacity.cooling",
        },
    )
    assert unknown.status_code == 422
