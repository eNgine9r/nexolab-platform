from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.instrumentation.api import create_instrumentation_router
from app.instrumentation.repository import (
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
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def headers(subject: str, organization_id: str = ORGANIZATION_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": organization_id,
    }


def payload(key: str = "SECURE-INSTRUMENT-001") -> dict[str, object]:
    return {
        "inventory_key": key,
        "display_name": "Захищений зонд",
        "instrument_kind": "temperature_probe",
        "manufacturer": None,
        "model": None,
        "serial_number": None,
        "lifecycle_state": "active",
        "metadata": {},
    }


def build_client(
    tmp_path: Path,
    *,
    subject: str,
    roles: set[Role],
) -> tuple[TestClient, SecurityRepository, InstrumentationRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / f'instrumentation-{subject}.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    for organization_id, slug in (
        (ORGANIZATION_ID, "nexolab-lab"),
        (OTHER_ORGANIZATION_ID, "other-lab"),
    ):
        security.provision_organization(
            organization_id=organization_id,
            slug=slug,
            name=slug,
        )
    security.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles,
    )
    dependencies = SecurityDependencies(
        security,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider="test-oidc",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    repository = InstrumentationRepository(database)
    app = FastAPI()
    app.include_router(
        create_instrumentation_router(
            repository,
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), security, repository


def test_dashboard_read_can_list_but_equipment_manage_is_required_to_mutate(
    tmp_path: Path,
) -> None:
    api, _, _ = build_client(tmp_path, subject="viewer", roles={Role.VIEWER})

    assert (
        api.get(
            "/api/v1/instrumentation/instruments",
            headers=headers("viewer"),
        ).status_code
        == 200
    )
    denied = api.post(
        "/api/v1/instrumentation/instruments",
        headers=headers("viewer"),
        json=payload(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"

    source_denied = api.post(
        "/api/v1/instrumentation/instruments/missing/signals/missing/acquisition-source-history",
        headers=headers("viewer"),
        json={
            "node_id": "edge-01",
            "equipment_id": "humidity-01",
            "channel_id": "ai-1",
            "metric": "humidity.relative",
            "unit": "%RH",
            "valid_from": "2026-09-06T00:00:00Z",
        },
    )
    assert source_denied.status_code == 403
    assert source_denied.json()["detail"]["code"] == "permission_denied"


def test_acquisition_source_mutation_is_organization_scoped_and_audited(
    tmp_path: Path,
) -> None:
    api, security, repository = build_client(
        tmp_path, subject="humidity-engineer", roles={Role.ENGINEER}
    )
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="RH-SECURE-001",
            display_name="Secure humidity transmitter",
            instrument_kind="humidity_transmitter",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="RH-SECURE-001.PRIMARY",
            display_name="Relative humidity",
            physical_quantity="relative_humidity",
            engineering_unit="%RH",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    response = api.post(
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/{signal.id}/acquisition-source-history",
        headers={
            **headers("humidity-engineer"),
            "X-Audit-Reason": "Bind recorded humidity source",
        },
        json={
            "node_id": "edge-01",
            "equipment_id": "humidity-01",
            "channel_id": "ai-1",
            "metric": "humidity.relative",
            "unit": "%RH",
            "valid_from": "2026-09-06T00:00:00Z",
        },
    )
    assert response.status_code == 201
    assert response.json()["evidence_status"] == "hardware_unverified"
    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="instrument_signal_acquisition_source",
        entity_id=signal.id,
        limit=10,
    )
    assert [event.action for event in events] == [
        "instrument_signal.acquisition_source_appended"
    ]
    assert events[0].actor_subject == "humidity-engineer"
    assert events[0].reason == "Bind recorded humidity source"

    hidden = api.get(
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/{signal.id}/acquisition-source-history",
        headers=headers("humidity-engineer", OTHER_ORGANIZATION_ID),
    )
    assert hidden.status_code == 403


def test_registry_mutations_use_verified_actor_and_local_audit_conventions(
    tmp_path: Path,
) -> None:
    api, security, _ = build_client(
        tmp_path,
        subject="engineer",
        roles={Role.ENGINEER},
    )
    created = api.post(
        "/api/v1/instrumentation/instruments",
        headers={
            **headers("engineer"),
            "X-Audit-Reason": "Register metrology inventory",
        },
        json=payload(),
    )
    assert created.status_code == 201
    instrument_id = created.json()["id"]

    acceptance = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history",
        headers={
            **headers("engineer"),
            "X-Audit-Reason": "Release for future calculation use",
        },
        json={
            "accepted_for_calculation": True,
            "effective_from": "2026-08-28T08:00:00Z",
        },
    )
    assert acceptance.status_code == 201

    instrument_events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="instrument",
        entity_id=instrument_id,
        limit=10,
    )
    assert [event.action for event in instrument_events] == ["instrument.created"]
    assert instrument_events[0].actor_subject == "engineer"
    assert instrument_events[0].reason == "Register metrology inventory"

    acceptance_events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="instrument_acceptance",
        entity_id=instrument_id,
        limit=10,
    )
    assert [event.action for event in acceptance_events] == [
        "instrument.acceptance_appended"
    ]
    assert acceptance_events[0].actor_subject == "engineer"
    assert acceptance_events[0].reason == "Release for future calculation use"


def test_cross_organization_registry_ids_do_not_leak_or_link(tmp_path: Path) -> None:
    api, _, repository = build_client(
        tmp_path,
        subject="admin",
        roles={Role.ADMINISTRATOR},
    )
    other = repository.create_instrument(
        InstrumentCreate.model_validate(payload("OTHER-INSTRUMENT-001")),
        actor_id="other-system",
        organization_id=OTHER_ORGANIZATION_ID,
    )

    hidden = api.get(
        f"/api/v1/instrumentation/instruments/{other.id}",
        headers=headers("admin"),
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "instrument_not_found"

    forbidden_scope = api.get(
        f"/api/v1/instrumentation/instruments/{other.id}",
        headers=headers("admin", OTHER_ORGANIZATION_ID),
    )
    assert forbidden_scope.status_code == 403
    assert forbidden_scope.json()["detail"]["code"] == (
        "organization_membership_not_found"
    )

    try:
        repository.create_signal(
            other.id,
            SignalCreate(
                business_key="CROSS-ORG-SIGNAL",
                display_name="Cross organization signal",
                physical_quantity="temperature",
                engineering_unit="degC",
            ),
            actor_id="admin",
            organization_id=ORGANIZATION_ID,
        )
    except InstrumentNotFoundError:
        pass
    else:
        raise AssertionError("cross-organization Instrument -> Signal link was accepted")


def test_analog_scaling_read_uses_dashboard_permission_and_mutation_requires_manage(
    tmp_path: Path,
) -> None:
    api, _, repository = build_client(tmp_path, subject="viewer", roles={Role.VIEWER})
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="SECURE-ANALOG-001",
            display_name="Secure analog instrument",
            instrument_kind="humidity_transmitter",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="SECURE-ANALOG-001.RH",
            display_name="Relative humidity",
            physical_quantity="relative_humidity",
            engineering_unit="percent",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    route = (
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/"
        f"{signal.id}/analog-scaling-history"
    )

    readable = api.get(route, headers=headers("viewer"))
    assert readable.status_code == 200
    assert readable.json() == {"items": []}

    denied = api.post(
        route,
        headers=headers("viewer"),
        json={
            "raw_unit": "mA",
            "raw_min": "4",
            "raw_max": "20",
            "engineering_min": "0",
            "engineering_max": "100",
            "engineering_unit": "percent",
            "evidence_status": "hardware_unverified",
            "effective_from": "2026-09-06T00:00:00Z",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def test_analog_scaling_cross_organization_signal_is_not_visible(tmp_path: Path) -> None:
    api, _, repository = build_client(
        tmp_path, subject="admin-analog", roles={Role.ADMINISTRATOR}
    )
    other = repository.create_instrument(
        InstrumentCreate(
            inventory_key="OTHER-ANALOG-001",
            display_name="Other analog instrument",
            instrument_kind="temperature_transmitter",
        ),
        actor_id="other-system",
        organization_id=OTHER_ORGANIZATION_ID,
    )
    other_signal = repository.create_signal(
        other.id,
        SignalCreate(
            business_key="OTHER-ANALOG-001.TEMP",
            display_name="Other temperature",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="other-system",
        organization_id=OTHER_ORGANIZATION_ID,
    )
    hidden = api.get(
        f"/api/v1/instrumentation/instruments/{other.id}/signals/"
        f"{other_signal.id}/analog-scaling-history",
        headers=headers("admin-analog"),
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "instrument_not_found"


def test_dashboard_read_can_evaluate_pressure_but_cross_org_stays_closed(
    tmp_path: Path,
) -> None:
    api, _, repository = build_client(
        tmp_path, subject="pressure-viewer", roles={Role.VIEWER}
    )
    at = datetime(2026, 9, 6, tzinfo=UTC)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="PRESSURE-SECURE-001",
            display_name="Secure pressure transmitter",
            instrument_kind="pressure_transmitter",
            pressure_reference="gauge",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="PRESSURE-SECURE-001.PRIMARY",
            display_name="Pressure",
            physical_quantity="pressure",
            engineering_unit="bar",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    source = repository.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="pressure-01",
            channel_id="ai-1",
            metric="pressure.process",
            unit="bar",
            valid_from=at,
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    repository.append_analog_scaling_profile(
        instrument.id,
        signal.id,
        AnalogScalingProfileAppendRequest(
            raw_unit="mA",
            raw_min=Decimal("4"),
            raw_max=Decimal("20"),
            engineering_min=Decimal("0"),
            engineering_max=Decimal("16"),
            engineering_unit="bar",
            acquisition_source_id=source.id,
            effective_from=at,
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    endpoint = (
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/{signal.id}/"
        "pressure-observation-evaluate"
    )

    allowed = api.post(
        endpoint,
        headers=headers("pressure-viewer"),
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert allowed.status_code == 200
    assert allowed.json()["pressure_reference"] == "gauge"
    assert allowed.json()["value"] == "8.000000000000000000"

    denied = api.post(
        endpoint,
        headers=headers("pressure-viewer", OTHER_ORGANIZATION_ID),
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "organization_membership_not_found"


def test_dashboard_read_can_evaluate_atmospheric_pressure_but_cross_org_stays_closed(
    tmp_path: Path,
) -> None:
    api, _, repository = build_client(
        tmp_path, subject="atmosphere-viewer", roles={Role.VIEWER}
    )
    at = datetime(2026, 9, 6, tzinfo=UTC)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="ATMOSPHERE-SECURE-001",
            display_name="Secure barometric pressure sensor",
            instrument_kind="barometric_pressure_sensor",
            pressure_reference="absolute",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key="ATMOSPHERE-SECURE-001.PRIMARY",
            display_name="Atmospheric pressure measurement",
            physical_quantity="pressure",
            engineering_unit="kPa",
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    source = repository.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="environment-reference-01",
            channel_id="ai-2",
            metric="pressure.environmental",
            unit="kPa",
            valid_from=at,
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    repository.append_analog_scaling_profile(
        instrument.id,
        signal.id,
        AnalogScalingProfileAppendRequest(
            raw_unit="mA",
            raw_min=Decimal("4"),
            raw_max=Decimal("20"),
            engineering_min=Decimal("80"),
            engineering_max=Decimal("120"),
            engineering_unit="kPa",
            acquisition_source_id=source.id,
            effective_from=at,
        ),
        actor_id="fixture",
        organization_id=ORGANIZATION_ID,
    )
    endpoint = (
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/{signal.id}/"
        "atmospheric-pressure-observation-evaluate"
    )

    allowed = api.post(
        endpoint,
        headers=headers("atmosphere-viewer"),
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert allowed.status_code == 200
    assert allowed.json()["pressure_reference"] == "absolute"
    assert allowed.json()["physical_quantity"] == "pressure"

    denied = api.post(
        endpoint,
        headers=headers("atmosphere-viewer", OTHER_ORGANIZATION_ID),
        json={"raw_value": "12", "at": at.isoformat()},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "organization_membership_not_found"
