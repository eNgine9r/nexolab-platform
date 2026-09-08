from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceRepository,
)
from app.instrumentation.profile_acceptance_api import create_profile_acceptance_router
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcquisitionSourceAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.model_registry import register_models
from app.refrigeration.calculation_policy import CalculationPolicyRepository
from app.refrigeration.calculation_policy_api import create_calculation_policy_router
from app.refrigeration.derived_api import create_derived_read_router
from app.refrigeration.derived_read import DerivedReadItem
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORG = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
AT = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


def _token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        SECRET,
        algorithm="HS256",
    )


def _headers(subject: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject)}",
        "X-Organization-ID": organization_id,
    }


class _CapturingDerivedService:
    def __init__(self) -> None:
        self.organization_ids: list[str] = []

    def calculate(self, circuit_id, observation_at, *, organization_id, metrics=None):
        self.organization_ids.append(organization_id)
        requested = metrics or ["refrigeration.superheat"]
        return tuple(
            DerivedReadItem(
                metric=metric,
                availability="unavailable",
                reason_codes=("circuit_lifecycle_unresolved",),
                observation_at=observation_at,
                computed_at=observation_at,
                kernel_result=None,
            )
            for metric in requested
        )


def _client(tmp_path: Path):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'rfx08b-security.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    for org, slug in ((ORG, "primary"), (OTHER, "other")):
        security.provision_organization(organization_id=org, slug=slug, name=slug)
    memberships = (
        ("viewer", ORG, {Role.VIEWER}),
        ("engineer", ORG, {Role.ENGINEER}),
        ("technician", ORG, {Role.LABORATORY_TECHNICIAN}),
        ("other-viewer", OTHER, {Role.VIEWER}),
    )
    for subject, org, roles in memberships:
        security.provision_membership(
            organization_id=org,
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
        default_organization_id=ORG,
    )
    instrumentation = InstrumentationRepository(database)
    profiles = AcquisitionProfileAcceptanceRepository(database)
    policies = CalculationPolicyRepository(database)
    derived = _CapturingDerivedService()
    app = FastAPI()
    app.include_router(
        create_calculation_policy_router(
            policies,
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORG,
        )
    )
    app.include_router(
        create_profile_acceptance_router(
            profiles,
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORG,
        )
    )
    app.include_router(
        create_derived_read_router(
            derived,
            security_dependencies=dependencies,
            default_organization_id=ORG,
        )
    )
    return TestClient(app), database, instrumentation, derived


def _policy_payload(version: str) -> dict[str, object]:
    return {
        "version": version,
        "maximum_age_ms": 10000,
        "maximum_future_clock_skew_ms": 0,
        "maximum_cross_input_skew_ms": 1000,
        "accepted_calibration_states": ["valid"],
        "require_calibration_at_observation": False,
        "calibration_required_roles": [],
    }


def test_policy_permissions_and_organization_isolation(tmp_path: Path) -> None:
    api, _, _, _ = _client(tmp_path)
    assert (
        api.get(
            "/api/v1/refrigeration/calculation-policies",
            headers=_headers("viewer", ORG),
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/v1/refrigeration/calculation-policies",
            headers=_headers("viewer", ORG),
            json=_policy_payload("denied"),
        ).status_code
        == 403
    )

    created = api.post(
        "/api/v1/refrigeration/calculation-policies",
        headers=_headers("engineer", ORG),
        json=_policy_payload("org-policy-v1"),
    )
    assert created.status_code == 201, created.text
    other = api.get(
        "/api/v1/refrigeration/calculation-policies",
        headers=_headers("other-viewer", OTHER),
    )
    assert other.status_code == 200
    assert other.json()["items"] == []


def test_profile_acceptance_permissions_and_cross_org_target_fail_closed(
    tmp_path: Path,
) -> None:
    api, _, instrumentation, _ = _client(tmp_path)
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key="SEC-RFX08B-INST",
            display_name="Secure temperature probe",
            instrument_kind="temperature_probe",
        ),
        actor_id="fixture",
        organization_id=ORG,
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key="SEC-RFX08B-SIGNAL",
            display_name="Temperature",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="fixture",
        organization_id=ORG,
    )
    source = instrumentation.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="equipment-01",
            channel_id="modbus-01",
            metric="temperature",
            unit="degC",
            acquisition_profile_id="digital-profile",
            acquisition_profile_version="1",
            valid_from=AT,
        ),
        actor_id="fixture",
        organization_id=ORG,
    )
    path = (
        f"/api/v1/instrumentation/instruments/{instrument.id}/signals/{signal.id}"
        f"/acquisition-sources/{source.id}/profile-acceptance-history"
    )
    assert api.get(path, headers=_headers("viewer", ORG)).status_code == 200
    assert (
        api.post(
            path,
            headers=_headers("viewer", ORG),
            json={"accepted_for_calculation": True, "effective_from": AT.isoformat()},
        ).status_code
        == 403
    )
    created = api.post(
        path,
        headers=_headers("engineer", ORG),
        json={"accepted_for_calculation": True, "effective_from": AT.isoformat()},
    )
    assert created.status_code == 201, created.text
    other = api.get(path, headers=_headers("other-viewer", OTHER))
    assert other.status_code == 404
    assert other.json()["detail"]["code"] == "acquisition_profile_not_found"


def test_derived_endpoint_requires_read_permission_and_uses_authorized_organization(
    tmp_path: Path,
) -> None:
    api, _, _, derived = _client(tmp_path)
    params = {
        "observation_at": AT.isoformat(),
        "metric": "refrigeration.superheat",
    }
    allowed = api.get(
        "/api/v1/refrigeration/circuits/circuit-1/derived",
        headers=_headers("viewer", ORG),
        params=params,
    )
    assert allowed.status_code == 200
    assert derived.organization_ids[-1] == ORG

    denied = api.get(
        "/api/v1/refrigeration/circuits/circuit-1/derived",
        headers=_headers("technician", ORG),
        params=params,
    )
    assert denied.status_code == 403

    other = api.get(
        "/api/v1/refrigeration/circuits/circuit-1/derived",
        headers=_headers("other-viewer", OTHER),
        params=params,
    )
    assert other.status_code == 200
    assert derived.organization_ids[-1] == OTHER
