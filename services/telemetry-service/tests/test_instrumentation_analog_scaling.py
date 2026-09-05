from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from app.instrumentation.scaling import (
    AnalogScalingUnavailableError,
    canonical_decimal,
    scale_linear_two_point,
)


def test_linear_4_20ma_scaling_is_decimal_exact() -> None:
    profile = dict(
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("0"),
        engineering_max=Decimal("30"),
    )

    assert scale_linear_two_point(Decimal("4"), **profile) == Decimal("0")
    assert scale_linear_two_point(Decimal("12"), **profile) == Decimal("15")
    assert scale_linear_two_point(Decimal("20"), **profile) == Decimal("30")


def test_linear_scaling_pins_decimal_context_and_quantizes_to_storage_scale() -> None:
    expected = Decimal("6172839450617283945.061728394506172839")
    profile = dict(
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("0"),
        engineering_max=Decimal("12345678901234567890.123456789012345678"),
    )

    with localcontext() as context:
        context.prec = 6
        constrained_context_result = scale_linear_two_point(Decimal("12"), **profile)

    with localcontext() as context:
        context.prec = 50
        expanded_context_result = scale_linear_two_point(Decimal("12"), **profile)

    assert constrained_context_result == expected
    assert expanded_context_result == expected
    assert constrained_context_result.as_tuple().exponent == -18


def test_linear_scaling_rounds_non_terminating_results_half_even_to_18_places() -> None:
    assert scale_linear_two_point(
        Decimal("1"),
        raw_min=Decimal("0"),
        raw_max=Decimal("3"),
        engineering_min=Decimal("0"),
        engineering_max=Decimal("1"),
    ) == Decimal("0.333333333333333333")


def test_linear_scaling_supports_negative_engineering_ranges() -> None:
    assert scale_linear_two_point(
        Decimal("12"),
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("-40"),
        engineering_max=Decimal("60"),
    ) == Decimal("10")


@pytest.mark.parametrize(
    ("raw", "code"),
    [(Decimal("3.999"), "analog_under_range"), (Decimal("20.001"), "analog_over_range")],
)
def test_linear_scaling_fails_closed_outside_accepted_domain(raw: Decimal, code: str) -> None:
    with pytest.raises(AnalogScalingUnavailableError) as failure:
        scale_linear_two_point(
            raw,
            raw_min=Decimal("4"),
            raw_max=Decimal("20"),
            engineering_min=Decimal("0"),
            engineering_max=Decimal("100"),
        )
    assert failure.value.code == code


def test_linear_scaling_rejects_zero_width_or_reversed_domain() -> None:
    for lower, upper in [("4", "4"), ("20", "4")]:
        with pytest.raises(AnalogScalingUnavailableError) as failure:
            scale_linear_two_point(
                "12",
                raw_min=lower,
                raw_max=upper,
                engineering_min="0",
                engineering_max="100",
            )
        assert failure.value.code == "analog_raw_domain_invalid"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_decimal_authority_rejects_non_finite_values(value: str) -> None:
    with pytest.raises(AnalogScalingUnavailableError) as failure:
        canonical_decimal(value)
    assert failure.value.code == "analog_raw_value_invalid"

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db import Database
from app.instrumentation.repository import (
    AnalogScalingResolutionError,
    AnalogScalingUnitMismatchError,
    InstrumentationRepository,
)
from app.instrumentation.schemas import (
    AnalogScalingProfileAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.model_registry import register_models
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def _repository_with_signal(
    tmp_path: Path, *, engineering_unit: str = "bar"
) -> tuple[InstrumentationRepository, str, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'analog-scaling.db'}")
    database.create_schema()
    SecurityRepository(database).provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository = InstrumentationRepository(database)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="PRESS-001",
            display_name="Pressure transmitter",
            instrument_kind="pressure_transmitter",
            pressure_reference="gauge",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="PRESS-001.PRIMARY",
            display_name="Pressure",
            physical_quantity="pressure",
            engineering_unit=engineering_unit,
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return repository, instrument.id, signal.id


def _profile(
    effective_from: datetime,
    *,
    engineering_unit: str = "bar",
    engineering_min: str = "0",
    engineering_max: str = "30",
) -> AnalogScalingProfileAppendRequest:
    return AnalogScalingProfileAppendRequest(
        raw_unit="mA",
        raw_min=Decimal("4"),
        raw_max=Decimal("20"),
        engineering_min=Decimal(engineering_min),
        engineering_max=Decimal(engineering_max),
        engineering_unit=engineering_unit,
        evidence_status="hardware_unverified",
        effective_from=effective_from,
    )


def test_repository_profile_history_resolves_half_open_revisions_and_scales(
    tmp_path: Path,
) -> None:
    repository, instrument_id, signal_id = _repository_with_signal(tmp_path)
    start = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
    first = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(start),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    second_start = start + timedelta(days=1)
    second = repository.append_analog_scaling_profile(
        instrument_id,
        signal_id,
        _profile(second_start, engineering_max="40"),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )

    history = repository.list_analog_scaling_history(
        instrument_id, signal_id, organization_id=ORGANIZATION_ID
    )
    assert [row.revision for row in history] == [1, 2]
    assert history[0].effective_to is not None
    assert history[0].effective_to.replace(tzinfo=UTC) == second_start
    assert history[1].effective_to is None
    assert repository.resolve_analog_scaling_profile(
        instrument_id,
        signal_id,
        second_start - timedelta(microseconds=1),
        organization_id=ORGANIZATION_ID,
    ).id == first.id
    assert repository.resolve_analog_scaling_profile(
        instrument_id,
        signal_id,
        second_start,
        organization_id=ORGANIZATION_ID,
    ).id == second.id

    profile, value = repository.evaluate_analog_scaling(
        instrument_id,
        signal_id,
        Decimal("12"),
        second_start,
        organization_id=ORGANIZATION_ID,
    )
    assert profile.revision == 2
    assert value == Decimal("20")


def test_repository_profile_unit_mismatch_fails_closed(tmp_path: Path) -> None:
    repository, instrument_id, signal_id = _repository_with_signal(tmp_path)
    with pytest.raises(AnalogScalingUnitMismatchError):
        repository.append_analog_scaling_profile(
            instrument_id,
            signal_id,
            _profile(datetime(2026, 9, 6, tzinfo=UTC), engineering_unit="kPa"),
            actor_id="test-suite",
            organization_id=ORGANIZATION_ID,
        )


def test_repository_resolution_fails_closed_without_profile(tmp_path: Path) -> None:
    repository, instrument_id, signal_id = _repository_with_signal(tmp_path)
    with pytest.raises(AnalogScalingResolutionError, match="exactly one"):
        repository.resolve_analog_scaling_profile(
            instrument_id,
            signal_id,
            datetime(2026, 9, 6, tzinfo=UTC),
            organization_id=ORGANIZATION_ID,
        )

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instrumentation.api import create_instrumentation_router


def _client_with_signal(tmp_path: Path) -> tuple[TestClient, SecurityRepository, str, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'analog-scaling-api.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository = InstrumentationRepository(database)
    app = FastAPI()
    app.include_router(
        create_instrumentation_router(
            repository,
            security_repository=security,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    api = TestClient(app)
    instrument = api.post(
        "/api/v1/instrumentation/instruments",
        json={
            "inventory_key": "PRESS-API-001",
            "display_name": "Pressure transmitter",
            "instrument_kind": "pressure_transmitter",
            "pressure_reference": "gauge",
        },
    )
    assert instrument.status_code == 201
    instrument_id = instrument.json()["id"]
    signal = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals",
        json={
            "business_key": "PRESS-API-001.PRIMARY",
            "display_name": "Pressure",
            "physical_quantity": "pressure",
            "engineering_unit": "bar",
        },
    )
    assert signal.status_code == 201
    return api, security, instrument_id, signal.json()["id"]


def test_api_exposes_audited_profile_history_resolution_and_evaluation(tmp_path: Path) -> None:
    api, security, instrument_id, signal_id = _client_with_signal(tmp_path)
    start = "2026-09-06T00:00:00Z"
    route = (
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/"
        f"{signal_id}/analog-scaling-history"
    )
    created = api.post(
        route,
        headers={"X-Audit-Reason": "Register software-only 4-20 mA scaling candidate"},
        json={
            "raw_unit": "mA",
            "raw_min": "4",
            "raw_max": "20",
            "engineering_min": "0",
            "engineering_max": "30",
            "engineering_unit": "bar",
            "evidence_status": "hardware_unverified",
            "effective_from": start,
        },
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["schema_version"] == "analog-scaling/v1"
    assert profile["evidence_status"] == "hardware_unverified"
    assert profile["engineering_unit"] == "bar"
    assert api.get(route).json()["items"] == [profile]

    resolved = api.get(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}/analog-scaling-profile",
        params={"at": start},
    )
    assert resolved.status_code == 200
    assert resolved.json()["id"] == profile["id"]

    evaluated = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}/analog-scaling-evaluate",
        json={"raw_value": "12", "at": start},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert Decimal(str(evaluated.json()["engineering_value"])) == Decimal("15")
    assert evaluated.json()["engineering_unit"] == "bar"

    under = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}/analog-scaling-evaluate",
        json={"raw_value": "3.9", "at": start},
    )
    assert under.status_code == 422
    assert under.json()["detail"]["code"] == "analog_under_range"

    audit = security.list_audit_events(organization_id=ORGANIZATION_ID, limit=20)
    assert any(
        event.action == "instrument_signal.analog_scaling_appended"
        and event.entity_id == signal_id
        for event in audit
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_min", "4.1234567890123456789"),
        ("raw_max", "200000000000000000000"),
        ("engineering_min", "-100000000000000000000"),
        ("engineering_max", "30.1234567890123456789"),
    ],
)
def test_api_rejects_analog_profile_values_outside_numeric_38_18(
    tmp_path: Path, field: str, value: str
) -> None:
    api, _, instrument_id, signal_id = _client_with_signal(tmp_path)
    route = (
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/"
        f"{signal_id}/analog-scaling-history"
    )
    payload = {
        "raw_unit": "mA",
        "raw_min": "4",
        "raw_max": "20",
        "engineering_min": "0",
        "engineering_max": "30",
        "engineering_unit": "bar",
        "evidence_status": "hardware_unverified",
        "effective_from": "2026-09-06T00:00:00Z",
    }
    payload[field] = value

    rejected = api.post(route, json=payload)

    assert rejected.status_code == 422
    assert api.get(route).json() == {"items": []}


def test_profile_schema_accepts_numeric_38_18_boundary() -> None:
    profile = AnalogScalingProfileAppendRequest(
        raw_unit="mA",
        raw_min=Decimal("4.123456789012345678"),
        raw_max=Decimal("20"),
        engineering_min=Decimal("-99999999999999999999.123456789012345678"),
        engineering_max=Decimal("99999999999999999999.123456789012345678"),
        engineering_unit="bar",
        evidence_status="hardware_unverified",
        effective_from=datetime(2026, 9, 6, tzinfo=UTC),
    )

    assert profile.raw_min == Decimal("4.123456789012345678")
    assert profile.engineering_max == Decimal(
        "99999999999999999999.123456789012345678"
    )


def test_api_rejects_unit_mismatch_and_unproven_hardware_verified_profile(tmp_path: Path) -> None:
    api, _, instrument_id, signal_id = _client_with_signal(tmp_path)
    route = (
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/"
        f"{signal_id}/analog-scaling-history"
    )
    payload = {
        "raw_unit": "mA",
        "raw_min": "4",
        "raw_max": "20",
        "engineering_min": "0",
        "engineering_max": "3000",
        "engineering_unit": "kPa",
        "evidence_status": "hardware_unverified",
        "effective_from": "2026-09-06T00:00:00Z",
    }
    mismatch = api.post(route, json=payload)
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "analog_scaling_unit_mismatch"

    payload["engineering_unit"] = "bar"
    payload["evidence_status"] = "hardware_verified"
    unproven = api.post(route, json=payload)
    assert unproven.status_code == 422
    assert "complete acquisition provenance" in unproven.text
