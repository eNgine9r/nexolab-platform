from __future__ import annotations

from pathlib import Path
from typing import Annotated, Callable

from fastapi import APIRouter, FastAPI, Header, HTTPException, status
from fastapi.testclient import TestClient

from app.db import Database
from app.model_registry import register_models
from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    effective_permissions,
)
from app.security.dependencies import AuthorizedRequest
from app.security.local_admin_api import create_local_user_admin_router
from app.security.local_admin_service import LocalUserAdminService
from app.security.local_repository import LOCAL_AUTH_PROVIDER, LocalAuthRepository
from app.security.passwords import hash_password
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


class TestAdminDependencies:
    def __init__(self, admin_identity_id: str) -> None:
        self._admin_identity_id = admin_identity_id

    def authorized_request(
        self,
        permission: Permission,
    ) -> Callable[..., AuthorizedRequest]:
        def dependency(
            role_value: Annotated[
                str,
                Header(alias="X-Test-Role"),
            ] = Role.ADMINISTRATOR.value,
        ) -> AuthorizedRequest:
            role = Role(role_value)
            if permission not in effective_permissions({role}):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "permission_denied"},
                )
            return AuthorizedRequest(
                identity_id=self._admin_identity_id,
                principal=AuthenticatedPrincipal(
                    subject="admin-subject",
                    organization_id=ORGANIZATION_ID,
                    roles=frozenset({role}),
                    provider=LOCAL_AUTH_PROVIDER,
                ),
            )

        return dependency


def build_client(tmp_path: Path) -> tuple[TestClient, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'local-user-admin-api.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    local = LocalAuthRepository(database)
    admin = local.bootstrap_account(
        username="admin",
        password_hash=hash_password("Admin-password-123"),
        email=None,
        display_name="Administrator",
        organization_id=ORGANIZATION_ID,
        organization_slug="nexolab",
        organization_name="NEXOLAB",
        roles={Role.ADMINISTRATOR},
    )
    service = LocalUserAdminService(database, security)
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(
        create_local_user_admin_router(
            service,
            TestAdminDependencies(admin.identity_id),  # type: ignore[arg-type]
        )
    )
    app.include_router(api)
    return TestClient(app), database


def headers(role: Role = Role.ADMINISTRATOR) -> dict[str, str]:
    return {"X-Test-Role": role.value}


def test_admin_api_uses_canonical_path_and_never_returns_password(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)

    created = client.post(
        "/api/v1/admin/users",
        headers=headers(),
        json={
            "username": "technician.one",
            "password": "Technician-password-123",
            "display_name": "Technician One",
            "role": "laboratory_technician",
            "permissions": ["dashboard.read", "telemetry.read"],
        },
    )

    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["role"] == "laboratory_technician"
    assert payload["effective_permissions"] == ["dashboard.read", "telemetry.read"]
    assert "password" not in repr(payload).casefold()
    assert created.headers["cache-control"] == "no-store"

    listing = client.get("/api/v1/admin/users", headers=headers())
    assert listing.status_code == 200
    assert listing.json()["count"] == 2
    database.dispose()


def test_non_administrator_is_denied_server_side(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)

    response = client.get(
        "/api/v1/admin/users",
        headers=headers(Role.ENGINEER),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"
    database.dispose()


def test_roles_expose_exactly_four_product_roles(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)

    response = client.get("/api/v1/admin/roles", headers=headers())

    assert response.status_code == 200
    assert [item["value"] for item in response.json()["items"]] == [
        "administrator",
        "laboratory_manager",
        "engineer",
        "laboratory_technician",
    ]
    database.dispose()
