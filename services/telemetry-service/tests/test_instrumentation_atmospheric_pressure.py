from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.instrumentation.repository as instrumentation_repository_module
from app.db import Database
from app.instrumentation.api import create_instrumentation_router
from app.instrumentation.repository import (
    AcquisitionSourceResolutionError,
    AnalogScalingSourceMismatchError,
    AtmosphericPressureSignalUnsupportedError,
    InstrumentNotFoundError,
    InstrumentationRepository,
    PressureSignalUnsupportedError,
)
from app.instrumentation.schemas import (
    AcquisitionSourceAppendRequest,
    AnalogScalingProfileAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.model_registry import register_models
from app.security.repository import SecurityRepository

ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def _repository(
    tmp_path: Path, *, pressure_reference: str = "absolute", instrument_kind: str = "barometric_pressure_sensor"
) -> tuple[Database, InstrumentationRepository, str, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / f'atmosphere-{pressure_reference}-{instrument_kind}.db'}")
    database.create_schema()
    SecurityRepository(database).provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="atmosphere-lab",
        name="Atmospheric pressure laboratory",
    )
    repository = InstrumentationRepository(database)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key=f"ATM-{pressure_reference}-{instrument_kind}",
            display_name="Atmospheric pressure sensor",
            instrument_kind=instrument_kind,
            pressure_reference=pressure_reference,
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"{instrument.inventory_key}.PRIMARY",
            display_name="Atmospheric pressure measurement",
            physical_quantity="pressure",
            engineering_unit="kPa",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return database, repository, instrument.id, signal.id


def _source(at: datetime, **changes: object) -> AcquisitionSourceAppendRequest:
    values: dict[str, object] = {
        "node_id": "edge-lab-01",
        "equipment_id": "environment-reference-01",
        "channel_id": "analog-input-6",
        "metric": "pressure.environmental",
        "unit": "kPa",
        "evidence_status": "hardware_unverified",
        "evidence_reference": "urn:nexolab:evidence:rfx05-atmospheric-source",
        "valid_from": at,
    }
    values.update(changes)
    return AcquisitionSourceAppendRequest.model_validate(values)


def _profile(at: datetime, source_id: str) -> AnalogScalingProfileAppendRequest:
    return AnalogScalingProfileAppendRequest(
        raw_unit="mA",
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("80"),
        engineering_max=Decimal("120"),
        engineering_unit="kPa",
        acquisition_source_id=source_id,
        evidence_status="hardware_unverified",
        evidence_reference="urn:nexolab:evidence:rfx05-atmospheric-profile",
        effective_from=at,
    )


def _bind(repository: InstrumentationRepository, instrument_id: str, signal_id: str, at: datetime):
    source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    profile = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(at, source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return source, profile


def test_atmospheric_observation_delegates_to_rfx02_and_never_persists_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, repository, instrument_id, signal_id = _repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    source, profile = _bind(repository, instrument_id, signal_id, at)
    delegated = False
    scaler = instrumentation_repository_module.scale_linear_two_point

    def recorded_scale(raw_value: Decimal, **kwargs: Decimal) -> Decimal:
        nonlocal delegated
        delegated = True
        return scaler(raw_value, **kwargs)

    monkeypatch.setattr(instrumentation_repository_module, "scale_linear_two_point", recorded_scale)
    resolved_source, resolved_profile, value = repository.evaluate_atmospheric_pressure_observation(
        instrument_id, signal_id, Decimal("12"), at, organization_id=ORGANIZATION_ID
    )

    assert delegated is True
    assert resolved_source.id == source.id
    assert resolved_profile.id == profile.id
    assert value == Decimal("100.000000000000000000")
    assert database.count_samples() == 0
    assert database.count_latest_samples() == 0


def test_atmospheric_observation_requires_barometric_absolute_pressure_identity(tmp_path: Path) -> None:
    at = datetime(2026, 9, 6, tzinfo=UTC)
    _, gauge_repo, gauge_instrument, gauge_signal = _repository(tmp_path, pressure_reference="gauge")
    _bind(gauge_repo, gauge_instrument, gauge_signal, at)
    with pytest.raises(AtmosphericPressureSignalUnsupportedError):
        gauge_repo.evaluate_atmospheric_pressure_observation(
            gauge_instrument, gauge_signal, Decimal("12"), at, organization_id=ORGANIZATION_ID
        )

    _, transmitter_repo, transmitter, transmitter_signal = _repository(
        tmp_path, instrument_kind="pressure_transmitter"
    )
    _bind(transmitter_repo, transmitter, transmitter_signal, at)
    with pytest.raises(AtmosphericPressureSignalUnsupportedError):
        transmitter_repo.evaluate_atmospheric_pressure_observation(
            transmitter, transmitter_signal, Decimal("12"), at, organization_id=ORGANIZATION_ID
        )

    _, barometric_repo, barometric, barometric_signal = _repository(tmp_path)
    _bind(barometric_repo, barometric, barometric_signal, at)
    with pytest.raises(PressureSignalUnsupportedError):
        barometric_repo.evaluate_pressure_observation(
            barometric, barometric_signal, Decimal("12"), at, organization_id=ORGANIZATION_ID
        )

    temperature = barometric_repo.create_signal(
        barometric,
        SignalCreate(
            business_key="ATM.TEMP",
            display_name="Temperature compatibility signal",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    with pytest.raises(AtmosphericPressureSignalUnsupportedError):
        barometric_repo.evaluate_atmospheric_pressure_observation(
            barometric, temperature.id, Decimal("12"), at, organization_id=ORGANIZATION_ID
        )


def test_atmospheric_pressure_remains_process_neutral_signal_identity() -> None:
    with pytest.raises(ValidationError):
        SignalCreate(
            business_key="ATM.INVALID",
            display_name="Invalid process role signal",
            physical_quantity="atmospheric_pressure",
            engineering_unit="kPa",
        )


def test_atmospheric_observation_fails_closed_on_missing_and_stale_source_profile(tmp_path: Path) -> None:
    _, repository, instrument_id, signal_id = _repository(tmp_path)
    start = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(AcquisitionSourceResolutionError):
        repository.evaluate_atmospheric_pressure_observation(
            instrument_id, signal_id, Decimal("12"), start, organization_id=ORGANIZATION_ID
        )

    first_source, _ = _bind(repository, instrument_id, signal_id, start)
    boundary = start + timedelta(hours=1)
    second_source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(boundary, channel_id="analog-input-7"),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    assert second_source.id != first_source.id
    with pytest.raises(AnalogScalingSourceMismatchError):
        repository.evaluate_atmospheric_pressure_observation(
            instrument_id, signal_id, Decimal("12"), boundary, organization_id=ORGANIZATION_ID
        )

    repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(boundary, second_source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    _, _, value = repository.evaluate_atmospheric_pressure_observation(
        instrument_id, signal_id, Decimal("12"), boundary, organization_id=ORGANIZATION_ID
    )
    assert value == Decimal("100.000000000000000000")


def test_atmospheric_api_returns_absolute_provenance_and_fails_closed(tmp_path: Path) -> None:
    _, repository, instrument_id, signal_id = _repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    app = FastAPI()
    app.include_router(create_instrumentation_router(repository, default_organization_id=ORGANIZATION_ID))
    api = TestClient(app)
    endpoint = (
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}/"
        "atmospheric-pressure-observation-evaluate"
    )

    missing = api.post(endpoint, json={"raw_value": "12", "at": at.isoformat()})
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "acquisition_source_resolution_unavailable"

    source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    missing_profile = api.post(endpoint, json={"raw_value": "12", "at": at.isoformat()})
    assert missing_profile.status_code == 409
    assert missing_profile.json()["detail"]["code"] == "analog_scaling_resolution_unavailable"

    profile = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(at, source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    response = api.post(endpoint, json={"raw_value": "12", "at": at.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert body["physical_quantity"] == "pressure"
    assert body["pressure_reference"] == "absolute"
    assert body["value"] == "100.000000000000000000"
    assert body["unit"] == "kPa"
    assert body["source"]["id"] == source.id
    assert body["source"]["evidence_reference"] == "urn:nexolab:evidence:rfx05-atmospheric-source"
    assert body["profile_id"] == profile.id
    assert body["profile_evidence_reference"] == "urn:nexolab:evidence:rfx05-atmospheric-profile"
    assert body["evidence_status"] == "hardware_unverified"

    over = api.post(endpoint, json={"raw_value": "21", "at": at.isoformat()})
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "analog_over_range"


def test_atmospheric_observation_is_organization_scoped(tmp_path: Path) -> None:
    _, repository, instrument_id, signal_id = _repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    _bind(repository, instrument_id, signal_id, at)
    with pytest.raises(InstrumentNotFoundError):
        repository.evaluate_atmospheric_pressure_observation(
            instrument_id, signal_id, Decimal("12"), at, organization_id=OTHER_ORGANIZATION_ID
        )
