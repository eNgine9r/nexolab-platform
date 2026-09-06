from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.instrumentation.repository as instrumentation_repository_module
from app.db import Database
from app.instrumentation.api import create_instrumentation_router
from app.instrumentation.repository import (
    AcquisitionSourceResolutionError,
    AcquisitionSourceUnitMismatchError,
    AnalogScalingSourceMismatchError,
    AnalogScalingUnitMismatchError,
    InstrumentNotFoundError,
    InstrumentationRepository,
    PressureSignalUnsupportedError,
)
from app.instrumentation.schemas import (
    AcquisitionSourceAppendRequest,
    AnalogScalingProfileAppendRequest,
    InstrumentCreate,
    PressureObservationRequest,
    SignalCreate,
)
from app.model_registry import register_models
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def _pressure_repository(
    tmp_path: Path,
    *,
    pressure_reference: str = "gauge",
) -> tuple[Database, InstrumentationRepository, str, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / f'pressure-{pressure_reference}.db'}")
    database.create_schema()
    SecurityRepository(database).provision_organization(
        organization_id=ORGANIZATION_ID,
        slug=f"pressure-{pressure_reference}-lab",
        name="Pressure laboratory",
    )
    repository = InstrumentationRepository(database)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key=f"PRESSURE-{pressure_reference.upper()}-001",
            display_name=f"{pressure_reference.title()} pressure transmitter",
            instrument_kind="pressure_transmitter",
            pressure_reference=pressure_reference,
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"PRESSURE-{pressure_reference.upper()}-001.PRIMARY",
            display_name="Pressure",
            physical_quantity="pressure",
            engineering_unit="bar",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return database, repository, instrument.id, signal.id


def _source(at: datetime, **changes: object) -> AcquisitionSourceAppendRequest:
    values: dict[str, object] = {
        "node_id": "edge-lab-01",
        "equipment_id": "pressure-rack-01",
        "channel_id": "analog-input-4",
        "metric": "pressure.process",
        "unit": "bar",
        "evidence_status": "hardware_unverified",
        "evidence_reference": "urn:nexolab:evidence:rfx04-pressure-source",
        "valid_from": at,
    }
    values.update(changes)
    return AcquisitionSourceAppendRequest.model_validate(values)


def _profile(
    at: datetime,
    *,
    acquisition_source_id: str | None = None,
) -> AnalogScalingProfileAppendRequest:
    return AnalogScalingProfileAppendRequest(
        raw_unit="mA",
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("0"),
        engineering_max=Decimal("16"),
        engineering_unit="bar",
        acquisition_source_id=acquisition_source_id,
        evidence_status="hardware_unverified",
        evidence_reference="urn:nexolab:evidence:rfx04-pressure-profile",
        effective_from=at,
    )


def _bind_source_and_profile(
    repository: InstrumentationRepository,
    instrument_id: str,
    signal_id: str,
    at: datetime,
):
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
        _profile(at, acquisition_source_id=source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return source, profile


def test_gauge_pressure_observation_delegates_to_rfx02_and_never_persists_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, repository, instrument_id, signal_id = _pressure_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    source, profile = _bind_source_and_profile(
        repository, instrument_id, signal_id, at
    )
    delegated = False
    rfx02_scaler = instrumentation_repository_module.scale_linear_two_point

    def recorded_scale(raw_value: Decimal, **kwargs: Decimal) -> Decimal:
        nonlocal delegated
        delegated = True
        return rfx02_scaler(raw_value, **kwargs)

    monkeypatch.setattr(
        instrumentation_repository_module, "scale_linear_two_point", recorded_scale
    )
    resolved_source, resolved_profile, value, pressure_reference = (
        repository.evaluate_pressure_observation(
            instrument_id,
            signal_id,
            Decimal("12"),
            at,
            organization_id=ORGANIZATION_ID,
        )
    )

    assert delegated is True
    assert resolved_source.id == source.id
    assert resolved_profile.id == profile.id
    assert value == Decimal("8.000000000000000000")
    assert pressure_reference == "gauge"
    assert resolved_source.evidence_status == "hardware_unverified"
    assert resolved_profile.evidence_status == "hardware_unverified"
    assert database.count_samples() == 0
    assert database.count_latest_samples() == 0


def test_absolute_pressure_observation_preserves_reference_without_atmospheric_adjustment(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _pressure_repository(
        tmp_path, pressure_reference="absolute"
    )
    at = datetime(2026, 9, 6, tzinfo=UTC)
    _bind_source_and_profile(repository, instrument_id, signal_id, at)

    _, _, value, pressure_reference = repository.evaluate_pressure_observation(
        instrument_id,
        signal_id,
        Decimal("12"),
        at,
        organization_id=ORGANIZATION_ID,
    )

    assert value == Decimal("8.000000000000000000")
    assert pressure_reference == "absolute"


def test_pressure_observation_rejects_wrong_identity_and_cross_organization(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _pressure_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    _bind_source_and_profile(repository, instrument_id, signal_id, at)

    with pytest.raises(InstrumentNotFoundError):
        repository.evaluate_pressure_observation(
            instrument_id,
            signal_id,
            Decimal("12"),
            at,
            organization_id=OTHER_ORGANIZATION_ID,
        )

    temperature = repository.create_signal(
        instrument_id,
        SignalCreate(
            business_key="PRESSURE-GAUGE-001.TEMP",
            display_name="Temperature compatibility signal",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    with pytest.raises(PressureSignalUnsupportedError) as failure:
        repository.evaluate_pressure_observation(
            instrument_id,
            temperature.id,
            Decimal("12"),
            at,
            organization_id=ORGANIZATION_ID,
        )
    assert failure.value.code == "pressure_signal_unsupported"

    wrong_instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="PRESSURE-WRONG-KIND-001",
            display_name="Wrong-kind pressure source",
            instrument_kind="temperature_probe",
            pressure_reference="gauge",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    wrong_signal = repository.create_signal(
        wrong_instrument.id,
        SignalCreate(
            business_key="PRESSURE-WRONG-KIND-001.PRIMARY",
            display_name="Pressure",
            physical_quantity="pressure",
            engineering_unit="bar",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    with pytest.raises(PressureSignalUnsupportedError):
        repository.evaluate_pressure_observation(
            wrong_instrument.id,
            wrong_signal.id,
            Decimal("12"),
            at,
            organization_id=ORGANIZATION_ID,
        )


def test_pressure_source_and_profile_units_must_match_signal_exactly(tmp_path: Path) -> None:
    _, repository, instrument_id, signal_id = _pressure_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(AcquisitionSourceUnitMismatchError):
        repository.append_acquisition_source(
            instrument_id,
            signal_id,
            _source(at, unit="kPa"),
            actor_id="test-suite",
            organization_id=ORGANIZATION_ID,
        )

    source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    mismatched = _profile(at, acquisition_source_id=source.id).model_copy(
        update={"engineering_unit": "kPa"}
    )
    with pytest.raises(AnalogScalingUnitMismatchError):
        repository.append_analog_scaling_profile(
            instrument_id,
            signal_id,
            mismatched,
            actor_id="test-suite",
            organization_id=ORGANIZATION_ID,
        )


def test_pressure_observation_fails_closed_after_source_rebind_until_profile_replaced(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _pressure_repository(tmp_path)
    start = datetime(2026, 9, 6, tzinfo=UTC)
    first_source, _ = _bind_source_and_profile(
        repository, instrument_id, signal_id, start
    )
    boundary = start + timedelta(hours=1)
    second_source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(boundary, channel_id="analog-input-5"),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    assert second_source.id != first_source.id

    with pytest.raises(AnalogScalingSourceMismatchError) as failure:
        repository.evaluate_pressure_observation(
            instrument_id,
            signal_id,
            Decimal("12"),
            boundary,
            organization_id=ORGANIZATION_ID,
        )
    assert failure.value.code == "analog_scaling_source_mismatch"

    replacement = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(boundary, acquisition_source_id=second_source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    source, profile, value, pressure_reference = repository.evaluate_pressure_observation(
        instrument_id,
        signal_id,
        Decimal("12"),
        boundary,
        organization_id=ORGANIZATION_ID,
    )
    assert source.id == second_source.id
    assert profile.id == replacement.id
    assert value == Decimal("8.000000000000000000")
    assert pressure_reference == "gauge"


def test_pressure_api_preserves_reference_source_profile_and_fail_closed_states(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _pressure_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    app = FastAPI()
    app.include_router(
        create_instrumentation_router(
            repository, default_organization_id=ORGANIZATION_ID
        )
    )
    api = TestClient(app)
    endpoint = (
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/"
        f"{signal_id}/pressure-observation-evaluate"
    )

    request = PressureObservationRequest(raw_value=Decimal("12"), at=at)
    missing_source = api.post(endpoint, json=request.model_dump(mode="json"))
    assert missing_source.status_code == 409
    assert missing_source.json()["detail"]["code"] == (
        "acquisition_source_resolution_unavailable"
    )

    source = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    missing_profile = api.post(endpoint, json=request.model_dump(mode="json"))
    assert missing_profile.status_code == 409
    assert missing_profile.json()["detail"]["code"] == (
        "analog_scaling_resolution_unavailable"
    )
    profile = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(at, acquisition_source_id=source.id),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )

    evaluated = api.post(endpoint, json=request.model_dump(mode="json"))
    assert evaluated.status_code == 200
    assert evaluated.json()["signal_id"] == signal_id
    assert evaluated.json()["physical_quantity"] == "pressure"
    assert evaluated.json()["pressure_reference"] == "gauge"
    assert evaluated.json()["raw_value"] == "12"
    assert evaluated.json()["value"] == "8.000000000000000000"
    assert evaluated.json()["unit"] == "bar"
    assert evaluated.json()["source"]["evidence_reference"] == (
        "urn:nexolab:evidence:rfx04-pressure-source"
    )
    assert evaluated.json()["source"]["id"] == source.id
    assert evaluated.json()["profile_id"] == profile.id
    assert evaluated.json()["profile_revision"] == profile.revision
    assert evaluated.json()["profile_evidence_status"] == "hardware_unverified"
    assert evaluated.json()["profile_evidence_reference"] == (
        "urn:nexolab:evidence:rfx04-pressure-profile"
    )
    assert evaluated.json()["evidence_status"] == "hardware_unverified"

    outside = api.post(
        endpoint,
        json={"raw_value": "20.1", "at": at.isoformat()},
    )
    assert outside.status_code == 422
    assert outside.json()["detail"]["code"] == "analog_over_range"

    temperature = repository.create_signal(
        instrument_id,
        SignalCreate(
            business_key="PRESSURE-GAUGE-001.API-TEMP",
            display_name="Temperature compatibility signal",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    wrong_identity = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/"
        f"{temperature.id}/pressure-observation-evaluate",
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert wrong_identity.status_code == 422
    assert wrong_identity.json()["detail"]["code"] == "pressure_signal_unsupported"
