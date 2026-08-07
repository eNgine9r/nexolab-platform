from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.security.authorization import (
    ADMIN_ONLY_PERMISSIONS,
    GRANTABLE_PERMISSIONS,
    PRODUCT_ROLES,
    Permission,
    Role,
)
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.local_admin_service import (
    LastAdministratorError,
    LocalUserAdminService,
    LocalUserConflictError,
    LocalUserNotFoundError,
    LocalUserRecord,
    LocalUserValidationError,
)
from app.security.passwords import PasswordHashError


ProductRoleValue = Literal[
    "administrator",
    "laboratory_manager",
    "engineer",
    "laboratory_technician",
]


class LocalUserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    role: ProductRoleValue
    permissions: set[Permission] = Field(default_factory=set)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=1024)


class LocalUserUpdateRequest(BaseModel):
    role: ProductRoleValue | None = None
    is_active: bool | None = None
    reason: str | None = Field(default=None, max_length=1024)


class LocalUserPermissionsRequest(BaseModel):
    permissions: set[Permission] = Field(default_factory=set)
    reason: str | None = Field(default=None, max_length=1024)


class LocalUserPasswordResetRequest(BaseModel):
    password: str = Field(min_length=12, max_length=256)
    reason: str | None = Field(default=None, max_length=1024)


class LocalUserSessionRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1024)


def create_local_user_admin_router(
    service: LocalUserAdminService,
    dependencies: SecurityDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["local-user-admin"])

    @router.get("/users")
    def list_users(
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        _no_store(response)
        rows = service.list_users(
            organization_id=authorized.principal.organization_id,
        )
        return {
            "items": [_user_payload(row) for row in rows],
            "count": len(rows),
        }

    @router.post("/users", status_code=status.HTTP_201_CREATED)
    def create_user(
        payload: LocalUserCreateRequest,
        request: Request,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        try:
            row = service.create_user(
                organization_id=authorized.principal.organization_id,
                username=payload.username,
                password=payload.password,
                role=payload.role,
                permissions=payload.permissions,
                email=payload.email,
                display_name=payload.display_name,
                actor_identity_id=authorized.identity_id,
                actor=authorized.principal,
                reason=payload.reason,
                **_request_context(request),
            )
        except LocalUserConflictError as error:
            raise _conflict(error.code, str(error)) from error
        except (PasswordHashError, ValueError, LocalUserValidationError) as error:
            raise _unprocessable(
                getattr(error, "code", "invalid_local_user"),
                str(error),
            ) from error
        _no_store(response)
        return _user_payload(row)

    @router.get("/users/{account_id}")
    def get_user(
        account_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        try:
            row = service.get_user(
                organization_id=authorized.principal.organization_id,
                account_id=account_id,
            )
        except LocalUserNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        _no_store(response)
        return _user_payload(row)

    @router.patch("/users/{account_id}")
    def update_user(
        account_id: str,
        payload: LocalUserUpdateRequest,
        request: Request,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        if payload.role is None and payload.is_active is None:
            raise _unprocessable(
                "local_user_update_empty",
                "role or is_active must be supplied",
            )
        try:
            row = service.update_user(
                organization_id=authorized.principal.organization_id,
                account_id=account_id,
                role=payload.role,
                is_active=payload.is_active,
                actor_identity_id=authorized.identity_id,
                actor=authorized.principal,
                reason=payload.reason,
                **_request_context(request),
            )
        except LocalUserNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        except (LastAdministratorError, LocalUserConflictError) as error:
            raise _conflict(error.code, str(error)) from error
        except LocalUserValidationError as error:
            raise _unprocessable(error.code, str(error)) from error
        _no_store(response)
        return _user_payload(row)

    @router.put("/users/{account_id}/permissions")
    def set_permissions(
        account_id: str,
        payload: LocalUserPermissionsRequest,
        request: Request,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        try:
            row = service.set_permissions(
                organization_id=authorized.principal.organization_id,
                account_id=account_id,
                permissions=payload.permissions,
                actor_identity_id=authorized.identity_id,
                actor=authorized.principal,
                reason=payload.reason,
                **_request_context(request),
            )
        except LocalUserNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        except LocalUserConflictError as error:
            raise _conflict(error.code, str(error)) from error
        except LocalUserValidationError as error:
            raise _unprocessable(error.code, str(error)) from error
        _no_store(response)
        return _user_payload(row)

    @router.post(
        "/users/{account_id}/reset-password",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def reset_password(
        account_id: str,
        payload: LocalUserPasswordResetRequest,
        request: Request,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> Response:
        try:
            service.reset_password(
                organization_id=authorized.principal.organization_id,
                account_id=account_id,
                password=payload.password,
                actor_identity_id=authorized.identity_id,
                actor=authorized.principal,
                reason=payload.reason,
                **_request_context(request),
            )
        except LocalUserNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        except (PasswordHashError, ValueError) as error:
            raise _unprocessable("invalid_password", str(error)) from error
        _no_store(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @router.post("/users/{account_id}/revoke-sessions")
    def revoke_sessions(
        account_id: str,
        payload: LocalUserSessionRevokeRequest,
        request: Request,
        response: Response,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, int]:
        try:
            count = service.revoke_sessions(
                organization_id=authorized.principal.organization_id,
                account_id=account_id,
                actor_identity_id=authorized.identity_id,
                actor=authorized.principal,
                reason=payload.reason,
                **_request_context(request),
            )
        except LocalUserNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        _no_store(response)
        return {"revoked_session_count": count}

    @router.get("/roles")
    def roles(
        response: Response,
        _: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        _no_store(response)
        labels = {
            Role.ADMINISTRATOR: "Адміністратор",
            Role.LABORATORY_MANAGER: "Керівник лабораторії",
            Role.ENGINEER: "Інженер",
            Role.LABORATORY_TECHNICIAN: "Технік-лаборант",
        }
        return {
            "items": [
                {
                    "value": role.value,
                    "label": labels[role],
                    "full_access": role == Role.ADMINISTRATOR,
                    "permissions_editable": role != Role.ADMINISTRATOR,
                }
                for role in (
                    Role.ADMINISTRATOR,
                    Role.LABORATORY_MANAGER,
                    Role.ENGINEER,
                    Role.LABORATORY_TECHNICIAN,
                )
                if role in PRODUCT_ROLES
            ]
        }

    @router.get("/permissions")
    def permissions(
        response: Response,
        _: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, object]:
        _no_store(response)
        return {
            "items": [
                {
                    "value": permission.value,
                    "grantable": permission in GRANTABLE_PERMISSIONS,
                    "administrator_only": permission in ADMIN_ONLY_PERMISSIONS,
                }
                for permission in sorted(Permission, key=lambda item: item.value)
            ]
        }

    return router


def _user_payload(row: LocalUserRecord) -> dict[str, object]:
    role = row.product_role
    return {
        "id": row.account_id,
        "identity_id": row.identity_id,
        "username": row.username,
        "email": row.email,
        "display_name": row.display_name,
        "is_active": row.is_active,
        "role": role.value if role is not None else None,
        "legacy_roles": [] if role is not None else list(row.roles),
        "migration_required": row.migration_required,
        "granted_permissions": sorted(
            permission.value for permission in row.granted_permissions
        ),
        "effective_permissions": sorted(
            permission.value for permission in row.effective_permissions
        ),
        "created_at": row.created_at.isoformat(),
        "password_changed_at": row.password_changed_at.isoformat(),
        "last_authenticated_at": row.last_authenticated_at.isoformat(),
        "locked_until": (
            row.locked_until.isoformat() if row.locked_until is not None else None
        ),
    }


def _request_context(request: Request) -> dict[str, str | None]:
    return {
        "request_id": request.headers.get("X-Request-ID"),
        "source_ip": request.client.host if request.client is not None else None,
        "user_agent": request.headers.get("User-Agent"),
    }


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )
