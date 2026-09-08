from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.db import Database
from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceRepository,
    AcquisitionProfileAcceptanceResolutionError,
    AcquisitionProfileIdentityUnavailableError,
    AcquisitionProfileNotFoundError,
    ProfileAcceptanceAppendRequest,
)
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcquisitionSourceAppendRequest,
    AnalogScalingProfileAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.model_registry import register_models
from app.security.repository import SecurityRepository


ORG = "11111111-1111-1111-1111-111111111111"
OTHER_ORG = "22222222-2222-2222-2222-222222222222"
T0 = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def _scope(tmp_path: Path, *, with_profile_identity: bool = True):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'profile-acceptance.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG, slug="lab", name="Lab")
    security.provision_organization(
        organization_id=OTHER_ORG, slug="other", name="Other"
    )
    instrumentation = InstrumentationRepository(database)
    acceptance = AcquisitionProfileAcceptanceRepository(database)
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key=f"INST-{uuid4().hex}",
            display_name="Temperature transmitter",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"temp-{uuid4().hex}",
            display_name="Suction line temperature",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    source = instrumentation.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="cabinet-01",
            channel_id="temp-01",
            metric="temperature",
            unit="degC",
            evidence_status="software_verified",
            acquisition_profile_id=("modbus-temp" if with_profile_identity else None),
            acquisition_profile_version=("1" if with_profile_identity else None),
            valid_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    return database, instrumentation, acceptance, instrument, signal, source


def _analog_profile(instrumentation, instrument, signal, source):
    return instrumentation.append_analog_scaling_profile(
        instrument.id,
        signal.id,
        AnalogScalingProfileAppendRequest(
            raw_unit="mA",
            raw_min=Decimal("4"),
            raw_max=Decimal("20"),
            engineering_min=Decimal("-50"),
            engineering_max=Decimal("50"),
            engineering_unit="degC",
            acquisition_device_family="test-analog",
            acquisition_profile_id=source.acquisition_profile_id,
            acquisition_profile_version=source.acquisition_profile_version,
            acquisition_channel_reference="ai-01",
            acquisition_source_id=source.id,
            evidence_status="software_verified",
            effective_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def test_digital_profile_acceptance_half_open_and_same_timestamp_handover(
    tmp_path: Path,
) -> None:
    _, _, repository, instrument, signal, source = _scope(tmp_path)
    first = repository.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            accepted_for_calculation=True,
            state_label="accepted",
            effective_from=T0,
        ),
        actor_id="operator-a",
        organization_id=ORG,
    )
    second_at = T0 + timedelta(hours=1)
    second = repository.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            accepted_for_calculation=False,
            state_label="label-does-not-override-boolean",
            effective_from=second_at,
        ),
        actor_id="operator-b",
        organization_id=ORG,
    )
    assert (
        repository.resolve(
            instrument.id,
            signal.id,
            source.id,
            second_at - timedelta(microseconds=1),
            organization_id=ORG,
        ).id
        == first.id
    )
    resolved = repository.resolve(
        instrument.id,
        signal.id,
        source.id,
        second_at,
        organization_id=ORG,
    )
    assert resolved.id == second.id
    assert resolved.accepted_for_calculation is False
    history = repository.list_history(
        instrument.id, signal.id, source.id, organization_id=ORG
    )
    assert _utc(history[0].effective_to) == second_at
    assert history[1].effective_to is None
    assert history[0].profile_target_key == f"source:{source.id}"


def test_analog_acceptance_targets_exact_source_and_scaling_profile(
    tmp_path: Path,
) -> None:
    _, instrumentation, repository, instrument, signal, source = _scope(tmp_path)
    profile = _analog_profile(instrumentation, instrument, signal, source)
    row = repository.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            scaling_profile_id=profile.id,
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="operator",
        organization_id=ORG,
    )
    assert row.scaling_profile_id == profile.id
    assert row.acquisition_profile_id == "modbus-temp"
    assert row.acquisition_profile_version == "1"
    assert row.profile_target_key == f"source:{source.id}/scaling:{profile.id}"
    assert (
        repository.resolve(
            instrument.id,
            signal.id,
            source.id,
            T0,
            scaling_profile_id=profile.id,
            organization_id=ORG,
        ).id
        == row.id
    )


def test_profile_acceptance_rejects_missing_explicit_source_profile_identity(
    tmp_path: Path,
) -> None:
    _, _, repository, instrument, signal, source = _scope(
        tmp_path, with_profile_identity=False
    )
    with pytest.raises(AcquisitionProfileIdentityUnavailableError):
        repository.append(
            instrument.id,
            signal.id,
            source.id,
            ProfileAcceptanceAppendRequest(
                accepted_for_calculation=True,
                effective_from=T0,
            ),
            actor_id="operator",
            organization_id=ORG,
        )


def test_profile_acceptance_is_organization_scoped(tmp_path: Path) -> None:
    _, _, repository, instrument, signal, source = _scope(tmp_path)
    with pytest.raises(AcquisitionProfileNotFoundError):
        repository.list_history(
            instrument.id,
            signal.id,
            source.id,
            organization_id=OTHER_ORG,
        )


def test_profile_acceptance_resolution_rejects_naive_timestamp(tmp_path: Path) -> None:
    _, _, repository, instrument, signal, source = _scope(tmp_path)
    repository.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="operator",
        organization_id=ORG,
    )
    with pytest.raises(AcquisitionProfileAcceptanceResolutionError, match="timezone"):
        repository.resolve(
            instrument.id,
            signal.id,
            source.id,
            datetime(2026, 9, 7, 10, 0),
            organization_id=ORG,
        )
