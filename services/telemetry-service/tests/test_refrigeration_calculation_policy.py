from __future__ import annotations

from pathlib import Path
import pytest
from pydantic import ValidationError

from app.db import Database
from app.model_registry import register_models
from app.refrigeration.calculation_policy import (
    CalculationPolicyConflictError,
    CalculationPolicyCreateRequest,
    CalculationPolicyNotFoundError,
    CalculationPolicyRepository,
)
from app.security.repository import SecurityRepository


ORG = "33333333-3333-3333-3333-333333333333"
OTHER_ORG = "44444444-4444-4444-4444-444444444444"


def _repository(tmp_path: Path) -> CalculationPolicyRepository:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'calculation-policy.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORG, slug="policy-a", name="Policy A"
    )
    security.provision_organization(
        organization_id=OTHER_ORG, slug="policy-b", name="Policy B"
    )
    return CalculationPolicyRepository(database)


def _payload(version: str = "lab-rfx08-v1") -> CalculationPolicyCreateRequest:
    return CalculationPolicyCreateRequest(
        version=version,
        maximum_age_ms=60_000,
        maximum_future_clock_skew_ms=2_000,
        maximum_cross_input_skew_ms=5_000,
        accepted_calibration_states=["valid", "due"],
        require_calibration_at_observation=True,
        calibration_required_roles=[
            "suction_pressure",
            "condensing_pressure",
            "suction_line_temperature",
            "liquid_line_temperature",
            "atmospheric_pressure",
        ],
    )


def test_policy_is_version_addressable_and_maps_exactly_to_kernel(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    row = repository.create(_payload(), actor_id="test-suite", organization_id=ORG)
    assert repository.get(row.version, organization_id=ORG).id == row.id
    assert [item.version for item in repository.list(organization_id=ORG)] == [
        row.version
    ]
    kernel = repository.as_kernel_policy(row.version, organization_id=ORG)
    assert kernel.version == row.version
    assert kernel.maximum_age.total_seconds() == 60
    assert kernel.maximum_future_clock_skew.total_seconds() == 2
    assert kernel.maximum_cross_input_skew.total_seconds() == 5
    assert kernel.accepted_calibration_states == frozenset({"valid", "due"})
    assert kernel.require_calibration_at_observation is True
    assert "atmospheric_pressure" in kernel.calibration_required_roles


def test_policy_version_is_unique_per_organization_and_cross_org_isolated(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.create(_payload(), actor_id="test-suite", organization_id=ORG)
    with pytest.raises(CalculationPolicyConflictError):
        repository.create(_payload(), actor_id="test-suite", organization_id=ORG)
    other = repository.create(
        _payload(), actor_id="test-suite", organization_id=OTHER_ORG
    )
    assert repository.get(other.version, organization_id=OTHER_ORG).id == other.id
    with pytest.raises(CalculationPolicyNotFoundError):
        repository.get("missing-v1", organization_id=ORG)


@pytest.mark.parametrize(
    "patch",
    [
        {"maximum_age_ms": -1},
        {"maximum_future_clock_skew_ms": -1},
        {"maximum_cross_input_skew_ms": -1},
        {"accepted_calibration_states": []},
        {"accepted_calibration_states": ["expired"]},
        {"accepted_calibration_states": ["valid", "valid"]},
        {"calibration_required_roles": ["relative_humidity"]},
        {"calibration_vocabulary_version": "calibration-state/v2"},
        {"schema_version": "refrigeration-calculation-policy/v2"},
    ],
)
def test_policy_validation_fails_closed(patch: dict[str, object]) -> None:
    payload = _payload().model_dump()
    payload.update(patch)
    with pytest.raises(ValidationError):
        CalculationPolicyCreateRequest.model_validate(payload)
