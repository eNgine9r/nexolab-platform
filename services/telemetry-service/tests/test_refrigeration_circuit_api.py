from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import AcceptanceAppendRequest, InstrumentCreate, SignalCreate
from app.model_registry import register_models
from app.refrigeration.circuit_api import create_refrigeration_circuit_router
from app.refrigeration.circuit_repository import RefrigerationCircuitRepository
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
AT = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


def _equipment() -> RefrigerationEquipmentRecord:
    return RefrigerationEquipmentRecord(
        id="equipment-1",
        organization_id=ORGANIZATION_ID,
        code="RFX06-EQ",
        name="RFX06 equipment",
        location="Lab",
        laboratory="Lab",
        zone=None,
        node_id=None,
        climate_chamber_id=None,
        equipment_type="Холодильна вітрина",
        manufacturer="Test",
        model="Test",
        serial_number="RFX06-SN",
        temperature_class="3M1",
        installed_at=None,
        serviced_at=None,
        lifecycle_status="active",
        status="offline",
        average_temperature_c=0.0,
        min_temperature_c=0.0,
        max_temperature_c=0.0,
        online_sensors=0,
        total_sensors=48,
        active_alarms=0,
        last_seen_at=None,
        version=1,
        created_by="test-suite",
        created_at=AT,
        updated_at=AT,
        deleted_by=None,
        deleted_at=None,
    )


def _client(tmp_path: Path):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'rfx06-api.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID, slug="default", name="Default"
    )
    with Session(database.engine) as session:
        with session.begin():
            session.add(_equipment())
    circuit_repository = RefrigerationCircuitRepository(database)
    instrumentation = InstrumentationRepository(database)
    app = FastAPI()
    app.include_router(
        create_refrigeration_circuit_router(
            circuit_repository,
            security_repository=security,
        )
    )
    return TestClient(app), database, security, instrumentation


def _accepted_pressure_signal(
    instrumentation: InstrumentationRepository,
    *,
    key: str,
    kind: str,
    reference: str,
    unit: str,
):
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key=f"INST-{key}",
            display_name=key,
            instrument_kind=kind,
            pressure_reference=reference,
        ),
        actor_id="test-suite",
    )
    instrumentation.append_acceptance(
        instrument.id,
        AcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=AT,
        ),
        actor_id="test-suite",
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"SIG-{key}",
            display_name=key,
            physical_quantity="pressure",
            engineering_unit=unit,
        ),
        actor_id="test-suite",
    )
    return signal


def _create_circuit(api: TestClient) -> str:
    response = api.post(
        "/api/v1/refrigeration/circuits",
        headers={"X-Audit-Reason": "RFX-06 API regression"},
        json={
            "equipment_id": "equipment-1",
            "business_key": "CIRCUIT-API",
            "display_name": "API circuit",
            "initial_state": "active",
            "valid_from": "2026-09-06T00:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_circuit_api_exposes_versioned_lifecycle_and_configuration_without_provider_fallback(
    tmp_path: Path,
) -> None:
    api, _, security, _ = _client(tmp_path)
    circuit_id = _create_circuit(api)

    missing = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}/configuration-effective",
        params={"at": "2026-09-06T01:00:00Z"},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "refrigeration_circuit_resolution_unavailable"

    configured = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/configuration-history",
        json={
            "refrigerant_code": "r404a",
            "calculation_policy_version": "rfx06-policy-v1",
            "property_provider_profile": None,
            "valid_from": "2026-09-06T02:00:00Z",
        },
    )
    assert configured.status_code == 201, configured.text
    assert configured.json()["refrigerant_code"] == "R404A"
    assert configured.json()["property_provider_profile"] is None
    assert "property_provider_ready" not in configured.json()

    lifecycle = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/lifecycle-history",
        json={"state": "inactive", "valid_from": "2026-09-07T00:00:00Z"},
    )
    assert lifecycle.status_code == 201
    assert lifecycle.json()["calculation_enabled"] is False

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        limit=20,
    )
    assert {event.action for event in events} >= {
        "refrigeration.circuit.created",
        "refrigeration.circuit.configuration.appended",
        "refrigeration.circuit.lifecycle.appended",
    }


def test_circuit_api_binding_preserves_pressure_reference_and_has_no_normalization(
    tmp_path: Path,
) -> None:
    api, _, _, instrumentation = _client(tmp_path)
    circuit_id = _create_circuit(api)
    suction = _accepted_pressure_signal(
        instrumentation,
        key="SUCTION",
        kind="pressure_transmitter",
        reference="gauge",
        unit="bar",
    )
    atmospheric = _accepted_pressure_signal(
        instrumentation,
        key="ATM",
        kind="barometric_pressure_sensor",
        reference="absolute",
        unit="kPa",
    )

    suction_response = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings",
        json={
            "role": "suction_pressure",
            "signal_id": suction.id,
            "valid_from": "2026-09-06T01:00:00Z",
        },
    )
    assert suction_response.status_code == 201, suction_response.text
    assert suction_response.json()["engineering_unit"] == "bar"
    assert suction_response.json()["pressure_reference"] == "gauge"

    atmospheric_response = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings",
        json={
            "role": "atmospheric_pressure",
            "signal_id": atmospheric.id,
            "valid_from": "2026-09-06T01:00:00Z",
        },
    )
    assert atmospheric_response.status_code == 201, atmospheric_response.text
    assert atmospheric_response.json()["engineering_unit"] == "kPa"
    assert atmospheric_response.json()["pressure_reference"] == "absolute"
    binding_id = atmospheric_response.json()["id"]

    direct_read = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings/{binding_id}"
    )
    assert direct_read.status_code == 200
    assert direct_read.json()["id"] == binding_id
    assert direct_read.json()["signal_id"] == atmospheric.id

    resolved = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings/atmospheric_pressure/effective",
        params={"at": "2026-09-06T01:30:00Z"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["signal_id"] == atmospheric.id


def test_circuit_api_rejects_gauge_signal_for_atmospheric_role(tmp_path: Path) -> None:
    api, _, _, instrumentation = _client(tmp_path)
    circuit_id = _create_circuit(api)
    gauge = _accepted_pressure_signal(
        instrumentation,
        key="GAUGE",
        kind="pressure_transmitter",
        reference="gauge",
        unit="bar",
    )

    rejected = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings",
        json={
            "role": "atmospheric_pressure",
            "signal_id": gauge.id,
            "valid_from": "2026-09-06T01:00:00Z",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "refrigeration_circuit_binding_incompatible"


def test_circuit_api_explicit_binding_end_makes_future_resolution_unavailable(tmp_path: Path) -> None:
    api, _, _, instrumentation = _client(tmp_path)
    circuit_id = _create_circuit(api)
    suction = _accepted_pressure_signal(
        instrumentation,
        key="END",
        kind="pressure_transmitter",
        reference="gauge",
        unit="bar",
    )
    assert api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings",
        json={
            "role": "suction_pressure",
            "signal_id": suction.id,
            "valid_from": "2026-09-06T01:00:00Z",
        },
    ).status_code == 201

    ended = api.post(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings/suction_pressure/end",
        json={"valid_to": "2026-09-06T02:00:00Z"},
    )
    assert ended.status_code == 200
    assert ended.json()["ended_by"] == "development-system"

    unavailable = api.get(
        f"/api/v1/refrigeration/circuits/{circuit_id}/bindings/suction_pressure/effective",
        params={"at": "2026-09-06T03:00:00Z"},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "refrigeration_circuit_resolution_unavailable"
