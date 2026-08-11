from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.model_registry import register_models
from app.security.api import create_security_router
from app.security.authentication import JwtAuthenticator
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.local_api import create_local_auth_router
from app.security.local_repository import LOCAL_AUTH_PROVIDER, LocalAuthRepository
from app.security.local_service import LocalAuthService
from app.security.passwords import hash_password
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
ISSUER = "urn:nexolab:test-local-user-admin"
AUDIENCE = "nexolab-test-api"
ADMIN_PASSWORD = "Admin-Correct-Horse-47"
ENGINEER_PASSWORD = "Engineer-Correct-Horse-47"
REPLACEMENT_PASSWORD = "Engineer-Replacement-72"


@dataclass(frozen=True)
class Fixture:
    client: TestClient
    database: Database

    def close(self) -> None:
        self.database.dispose()


def build_fixture(tmp_path: Path) -> Fixture:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'local-user-admin-integration.db'}")
    database.create_schema()
    security_repository = SecurityRepository(database)
    local_repository = LocalAuthRepository(database)
    local_repository.bootstrap_account(
        username="admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        email="admin@nexolab.local",
        display_name="Administrator",
        organization_id=ORGANIZATION_ID,
        organization_slug="nexolab-lab",
        organization_name="NEXOLAB Laboratory",
        roles={Role.ADMINISTRATOR},
    )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    service = LocalAuthService(
        local_repository,
        security_repository,
        private_key=private_pem,
        algorithm="RS256",
        issuer=ISSUER,
        audience=AUDIENCE,
        access_token_seconds=300,
        refresh_token_seconds=3600,
        max_failed_attempts=3,
        lockout_seconds=300,
    )
    dependencies = SecurityDependencies(
        security_repository,
        mode="local",
        authenticator=JwtAuthenticator(
            public_key=public_pem,
            algorithm="RS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider=LOCAL_AUTH_PROVIDER,
        ),
        default_organization_id=ORGANIZATION_ID,
        local_session_validator=service.validate_access_claims,
    )
    app = FastAPI()
    app.include_router(create_local_auth_router(service))
    app.include_router(create_security_router(security_repository, dependencies))
    return Fixture(TestClient(app), database)


def login(client: TestClient, username: str, password: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/local/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(access_token: object) -> dict[str, str]:
    assert isinstance(access_token, str)
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


def test_local_admin_can_create_and_revoke_explicit_engineer_access(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    try:
        admin_tokens = login(fixture.client, "admin", ADMIN_PASSWORD)
        admin_headers = auth_headers(admin_tokens["access_token"])

        created_response = fixture.client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": "engineer.one",
                "password": ENGINEER_PASSWORD,
                "display_name": "Engineer One",
                "role": "engineer",
                "permissions": ["dashboard.read", "telemetry.read"],
                "reason": "integration test",
            },
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        assert created["role"] == "engineer"
        assert created["effective_permissions"] == [
            "dashboard.read",
            "telemetry.read",
        ]
        assert ENGINEER_PASSWORD not in created_response.text
        assert "scrypt$" not in created_response.text

        engineer_tokens = login(fixture.client, "engineer.one", ENGINEER_PASSWORD)
        engineer_headers = auth_headers(engineer_tokens["access_token"])
        session_response = fixture.client.get(
            "/api/v1/auth/session",
            headers=engineer_headers,
        )
        assert session_response.status_code == 200, session_response.text
        membership = session_response.json()["memberships"][0]
        assert membership["roles"] == ["engineer"]
        assert membership["permissions"] == [
            "dashboard.read",
            "telemetry.read",
        ]

        denied_response = fixture.client.get(
            "/api/v1/admin/users",
            headers=engineer_headers,
        )
        assert denied_response.status_code == 403
        assert denied_response.json()["detail"]["code"] == "permission_denied"

        changed_response = fixture.client.put(
            f"/api/v1/admin/users/{created['id']}/permissions",
            headers=admin_headers,
            json={
                "permissions": ["dashboard.read", "nodes.read"],
                "reason": "integration permission change",
            },
        )
        assert changed_response.status_code == 200, changed_response.text
        assert changed_response.json()["effective_permissions"] == [
            "dashboard.read",
            "nodes.read",
        ]

        revoked_old_access = fixture.client.get(
            "/api/v1/auth/session",
            headers=engineer_headers,
        )
        assert revoked_old_access.status_code == 401
        assert revoked_old_access.json()["detail"]["code"] == "local_session_invalid"

        engineer_tokens = login(fixture.client, "engineer.one", ENGINEER_PASSWORD)
        refreshed_session = fixture.client.get(
            "/api/v1/auth/session",
            headers=auth_headers(engineer_tokens["access_token"]),
        )
        assert refreshed_session.status_code == 200
        assert refreshed_session.json()["memberships"][0]["permissions"] == [
            "dashboard.read",
            "nodes.read",
        ]

        deactivated_response = fixture.client.patch(
            f"/api/v1/admin/users/{created['id']}",
            headers=admin_headers,
            json={
                "is_active": False,
                "reason": "integration deactivation",
            },
        )
        assert deactivated_response.status_code == 200, deactivated_response.text
        assert deactivated_response.json()["is_active"] is False

        revoked_after_deactivation = fixture.client.get(
            "/api/v1/auth/session",
            headers=auth_headers(engineer_tokens["access_token"]),
        )
        assert revoked_after_deactivation.status_code == 401

        denied_login = fixture.client.post(
            "/api/v1/auth/local/login",
            json={"username": "engineer.one", "password": ENGINEER_PASSWORD},
        )
        assert denied_login.status_code == 401
        assert denied_login.json()["detail"]["code"] == "invalid_local_credentials"

        reactivated_response = fixture.client.patch(
            f"/api/v1/admin/users/{created['id']}",
            headers=admin_headers,
            json={
                "is_active": True,
                "reason": "integration reactivation",
            },
        )
        assert reactivated_response.status_code == 200
        assert reactivated_response.json()["is_active"] is True
        assert login(fixture.client, "engineer.one", ENGINEER_PASSWORD)["access_token"]

        active_before_reset = login(fixture.client, "engineer.one", ENGINEER_PASSWORD)
        reset_response = fixture.client.post(
            f"/api/v1/admin/users/{created['id']}/reset-password",
            headers=admin_headers,
            json={
                "password": REPLACEMENT_PASSWORD,
                "reason": "integration password reset",
            },
        )
        assert reset_response.status_code == 204, reset_response.text
        assert reset_response.content == b""

        revoked_after_reset = fixture.client.get(
            "/api/v1/auth/session",
            headers=auth_headers(active_before_reset["access_token"]),
        )
        assert revoked_after_reset.status_code == 401
        old_password_login = fixture.client.post(
            "/api/v1/auth/local/login",
            json={"username": "engineer.one", "password": ENGINEER_PASSWORD},
        )
        assert old_password_login.status_code == 401
        assert login(fixture.client, "engineer.one", REPLACEMENT_PASSWORD)["access_token"]
    finally:
        fixture.close()
