from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.instrumentation.api import create_instrumentation_router
from app.instrumentation.repository import (
    AcquisitionSourceResolutionError,
    AcquisitionSourceUnitMismatchError,
    HumiditySignalUnsupportedError,
    InstrumentNotFoundError,
    InstrumentationRepository,
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


def _humidity_repository(
    tmp_path: Path,
) -> tuple[Database, InstrumentationRepository, str, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'humidity.db'}")
    database.create_schema()
    SecurityRepository(database).provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="humidity-lab",
        name="Humidity laboratory",
    )
    repository = InstrumentationRepository(database)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="RH-001",
            display_name="Humidity transmitter",
            instrument_kind="humidity_transmitter",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="RH-001.PRIMARY",
            display_name="Relative humidity",
            physical_quantity="relative_humidity",
            engineering_unit="%RH",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return database, repository, instrument.id, signal.id


def _source(at: datetime, **changes: object) -> AcquisitionSourceAppendRequest:
    values: dict[str, object] = {
        "node_id": "edge-lab-01",
        "equipment_id": "humidity-rack-01",
        "channel_id": "analog-input-2",
        "metric": "humidity.relative",
        "unit": "%RH",
        "evidence_status": "hardware_unverified",
        "valid_from": at,
    }
    values.update(changes)
    return AcquisitionSourceAppendRequest.model_validate(values)


def _profile(at: datetime) -> AnalogScalingProfileAppendRequest:
    return AnalogScalingProfileAppendRequest(
        raw_unit="mA",
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("10"),
        engineering_max=Decimal("90"),
        engineering_unit="%RH",
        evidence_status="hardware_unverified",
        effective_from=at,
    )


def test_source_history_is_explicit_append_oriented_and_half_open(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _humidity_repository(tmp_path)
    start = datetime(2026, 9, 6, tzinfo=UTC)
    source_payload = _source(start, node_id=" edge  lab-01 ")
    assert source_payload.node_id == "edge  lab-01"
    first = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        source_payload,
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    boundary = start + timedelta(days=1)
    second = repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(boundary, channel_id="analog-input-3", metric="humidity.rh"),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )

    history = repository.list_acquisition_source_history(
        instrument_id, signal_id, organization_id=ORGANIZATION_ID
    )
    assert [row.revision for row in history] == [1, 2]
    assert (
        history[0].node_id,
        history[0].equipment_id,
        history[0].channel_id,
        history[0].metric,
        history[0].unit,
    ) == (
        "edge  lab-01",
        "humidity-rack-01",
        "analog-input-2",
        "humidity.relative",
        "%RH",
    )
    assert (
        repository.resolve_acquisition_source(
            instrument_id,
            signal_id,
            boundary - timedelta(microseconds=1),
            organization_id=ORGANIZATION_ID,
        ).id
        == first.id
    )
    assert (
        repository.resolve_acquisition_source(
            instrument_id, signal_id, boundary, organization_id=ORGANIZATION_ID
        ).id
        == second.id
    )


def test_source_binding_fails_closed_for_missing_state_unit_and_organization(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _humidity_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(AcquisitionSourceResolutionError):
        repository.resolve_acquisition_source(
            instrument_id, signal_id, at, organization_id=ORGANIZATION_ID
        )
    with pytest.raises(AcquisitionSourceUnitMismatchError):
        repository.append_acquisition_source(
            instrument_id,
            signal_id,
            _source(at, unit="degC"),
            actor_id="test-suite",
            organization_id=ORGANIZATION_ID,
        )
    with pytest.raises(InstrumentNotFoundError):
        repository.evaluate_humidity_observation(
            instrument_id,
            signal_id,
            Decimal("12"),
            at,
            organization_id="22222222-2222-2222-2222-222222222222",
        )


def test_humidity_evaluation_delegates_to_rfx02_and_never_persists_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, repository, instrument_id, signal_id = _humidity_repository(tmp_path)
    at = datetime(2026, 9, 6, tzinfo=UTC)
    repository.append_acquisition_source(
        instrument_id,
        signal_id,
        _source(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    delegated = False
    rfx02_evaluator = repository.evaluate_analog_scaling

    def recorded_delegate(*args: object, **kwargs: object):
        nonlocal delegated
        delegated = True
        return rfx02_evaluator(*args, **kwargs)

    monkeypatch.setattr(repository, "evaluate_analog_scaling", recorded_delegate)
    source, profile, value = repository.evaluate_humidity_observation(
        instrument_id,
        signal_id,
        Decimal("12"),
        at,
        organization_id=ORGANIZATION_ID,
    )

    assert delegated is True
    assert value == Decimal("50.000000000000000000")
    assert source.evidence_status == profile.evidence_status == "hardware_unverified"
    assert database.count_samples() == 0
    assert database.count_latest_samples() == 0


def test_humidity_evaluation_rejects_non_humidity_signal(tmp_path: Path) -> None:
    _, repository, instrument_id, _ = _humidity_repository(tmp_path)
    signal = repository.create_signal(
        instrument_id,
        SignalCreate(
            business_key="RH-001.TEMP",
            display_name="Temperature compatibility signal",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    with pytest.raises(HumiditySignalUnsupportedError) as failure:
        repository.evaluate_humidity_observation(
            instrument_id,
            signal.id,
            Decimal("12"),
            datetime(2026, 9, 6, tzinfo=UTC),
            organization_id=ORGANIZATION_ID,
        )
    assert failure.value.code == "humidity_signal_unsupported"


def test_humidity_api_preserves_source_profile_and_unverified_evidence(
    tmp_path: Path,
) -> None:
    _, repository, instrument_id, signal_id = _humidity_repository(tmp_path)
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
        f"{signal_id}/humidity-observation-evaluate"
    )

    missing_source = api.post(
        endpoint, json={"raw_value": "12", "at": at.isoformat()}
    )
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
    missing_profile = api.post(
        endpoint, json={"raw_value": "12", "at": at.isoformat()}
    )
    assert missing_profile.status_code == 409
    assert missing_profile.json()["detail"]["code"] == (
        "analog_scaling_resolution_unavailable"
    )
    profile = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(at),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )

    resolved = api.get(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}/acquisition-source",
        params={"at": at.isoformat()},
    )
    assert resolved.status_code == 200
    assert resolved.json()["id"] == source.id

    evaluated = api.post(
        endpoint,
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert evaluated.status_code == 200
    assert evaluated.json() == {
        "signal_id": signal_id,
        "physical_quantity": "relative_humidity",
        "raw_value": "12",
        "value": "50.000000000000000000",
        "unit": "%RH",
        "source": resolved.json(),
        "profile_id": profile.id,
        "profile_revision": 1,
        "profile_evidence_status": "hardware_unverified",
        "evidence_status": "hardware_unverified",
    }

    outside = api.post(
        endpoint,
        json={"raw_value": "20.1", "at": at.isoformat()},
    )
    assert outside.status_code == 422
    assert outside.json()["detail"]["code"] == "analog_over_range"
