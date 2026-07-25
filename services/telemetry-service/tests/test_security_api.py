from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.security.api import create_security_router
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


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


def build_client(
    tmp_path: Path,
    *,
    subject: str,
    roles: set[Role],
) -> tuple[TestClient, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / f'{subject}.db'}")
    database.create_schema()
    repository = SecurityRepository(database)
    repository.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository.provision_organization(
        organization_id=OTHER_ORGANIZATION_ID,
        slug="other-lab",
        name="Other Laboratory",
    )
    repository.provision_membership(
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
        repository,
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
    app = FastAPI()
    app.include_router(create_security_router(repository, dependencies))
    return TestClient(app), repository


def authorization(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(subject)}"}


def test_missing_token_returns_401(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="auditor", roles={Role.AUDITOR})

    response = api.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "missing_bearer_token"


def test_session_returns_database_memberships_and_permissions(tmp_path: Path) -> None:
    api, _ = build_client(
        tmp_path,
        subject="operator",
        roles={Role.OPERATOR},
    )

    response = api.get(
        "/api/v1/auth/session",
        headers=authorization("operator"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["identity"]["subject"] == "operator"
    assert payload["memberships"][0]["organization_id"] == ORGANIZATION_ID
    assert payload["memberships"][0]["roles"] == ["operator"]
    assert "layout.draft.edit" in payload["memberships"][0]["permissions"]
    assert "audit.read" not in payload["memberships"][0]["permissions"]


def test_viewer_cannot_read_audit(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="viewer", roles={Role.VIEWER})

    response = api.get(
        "/api/v1/audit/events",
        headers={
            **authorization("viewer"),
            "X-Organization-ID": ORGANIZATION_ID,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_cross_organization_access_is_denied(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="admin", roles={Role.ADMINISTRATOR})

    response = api.get(
        "/api/v1/audit/events",
        headers={
            **authorization("admin"),
            "X-Organization-ID": OTHER_ORGANIZATION_ID,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "organization_membership_not_found"


def test_auditor_reads_only_selected_organization_events(tmp_path: Path) -> None:
    api, repository = build_client(
        tmp_path,
        subject="auditor",
        roles={Role.AUDITOR},
    )
    security_session = repository.resolve_session(
        VerifiedIdentityClaims(provider="test-oidc", subject="auditor")
    )
    repository.append_audit_event(
        AuditEventInput(
            organization_id=ORGANIZATION_ID,
            actor_identity_id=security_session.identity_id,
            actor_subject="auditor",
            actor_roles=frozenset({Role.AUDITOR}),
            action="layout.published",
            entity_type="equipment_layout",
            entity_id="showcase-1",
            after_snapshot={"revision": 1},
        )
    )

    response = api.get(
        "/api/v1/audit/events?entity_type=equipment_layout",
        headers={
            **authorization("auditor"),
            "X-Organization-ID": ORGANIZATION_ID,
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["action"] == "layout.published"
