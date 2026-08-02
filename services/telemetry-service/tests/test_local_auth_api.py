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
ISSUER = "urn:nexolab:test-local"
AUDIENCE = "nexolab-test-api"
PASSWORD = "Correct-Horse-Battery-47"


@dataclass(frozen=True)
class LocalAuthFixture:
    client: TestClient
    database: Database

    def close(self) -> None:
        self.database.dispose()


def build_fixture(
    tmp_path: Path,
    *,
    max_failed_attempts: int = 3,
    lockout_seconds: int = 300,
) -> LocalAuthFixture:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'local-auth.db'}")
    database.create_schema()
    security_repository = SecurityRepository(database)
    local_repository = LocalAuthRepository(database)
    for username, role in (
        ("admin", Role.ADMINISTRATOR),
        ("operator", Role.OPERATOR),
        ("viewer", Role.VIEWER),
    ):
        local_repository.bootstrap_account(
            username=username,
            password_hash=hash_password(PASSWORD),
            email=f"{username}@nexolab.local",
            display_name=username.title(),
            organization_id=ORGANIZATION_ID,
            organization_slug="nexolab-lab",
            organization_name="NEXOLAB Laboratory",
            roles={role},
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
        max_failed_attempts=max_failed_attempts,
        lockout_seconds=lockout_seconds,
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
    return LocalAuthFixture(TestClient(app), database)


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/local/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def authorization(access_token: object) -> dict[str, str]:
    assert isinstance(access_token, str)
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


def test_local_login_returns_revocable_access_and_refresh_tokens(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    try:
        tokens = login(fixture.client, "admin")

        response = fixture.client.get(
            "/api/v1/auth/session",
            headers=authorization(tokens["access_token"]),
        )
        assert response.status_code == 200
        assert response.json()["identity"]["provider"] == LOCAL_AUTH_PROVIDER
        assert response.json()["memberships"][0]["roles"] == ["administrator"]

        audit_response = fixture.client.get(
            "/api/v1/audit/events",
            headers=authorization(tokens["access_token"]),
        )
        assert audit_response.status_code == 200
        login_events = [
            item
            for item in audit_response.json()["items"]
            if item["action"] == "security.local_login.succeeded"
        ]
        assert len(login_events) == 1
        assert login_events[0]["actor_subject"] == response.json()["identity"]["subject"]
    finally:
        fixture.close()


def test_refresh_rotates_token_and_logout_revokes_access_session(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    try:
        initial = login(fixture.client, "operator")
        refresh_response = fixture.client.post(
            "/api/v1/auth/local/refresh",
            json={"refresh_token": initial["refresh_token"]},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["refresh_token"] != initial["refresh_token"]

        replay_response = fixture.client.post(
            "/api/v1/auth/local/refresh",
            json={"refresh_token": initial["refresh_token"]},
        )
        assert replay_response.status_code == 401
        assert replay_response.json()["detail"]["code"] == "invalid_local_refresh_token"

        logout_response = fixture.client.post(
            "/api/v1/auth/local/logout",
            json={"refresh_token": refreshed["refresh_token"]},
        )
        assert logout_response.status_code == 204

        revoked_response = fixture.client.get(
            "/api/v1/auth/session",
            headers=authorization(refreshed["access_token"]),
        )
        assert revoked_response.status_code == 401
        assert revoked_response.json()["detail"]["code"] == "local_session_invalid"
    finally:
        fixture.close()


def test_local_roles_remain_server_authoritative(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    try:
        viewer = login(fixture.client, "viewer")
        response = fixture.client.get(
            "/api/v1/audit/events",
            headers=authorization(viewer["access_token"]),
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "permission_denied"
    finally:
        fixture.close()


def test_repeated_bad_passwords_trigger_bounded_lockout(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path, max_failed_attempts=3, lockout_seconds=60)
    try:
        responses = []
        for _ in range(3):
            responses.append(
                fixture.client.post(
                    "/api/v1/auth/local/login",
                    json={"username": "operator", "password": "Wrong-Password-Value-99"},
                )
            )

        assert [response.status_code for response in responses] == [401, 401, 429]
        assert responses[-1].headers["retry-after"] == "60"
        correct_password_response = fixture.client.post(
            "/api/v1/auth/local/login",
            json={"username": "operator", "password": PASSWORD},
        )
        assert correct_password_response.status_code == 429
        retry_after = int(correct_password_response.headers["retry-after"])
        assert 1 <= retry_after <= 60
    finally:
        fixture.close()


def test_unknown_account_uses_generic_invalid_credentials_response(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    try:
        response = fixture.client.post(
            "/api/v1/auth/local/login",
            json={"username": "unknown", "password": "Wrong-Password-Value-99"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == {
            "code": "invalid_local_credentials",
            "message": "Неправильний логін або пароль.",
        }
    finally:
        fixture.close()
