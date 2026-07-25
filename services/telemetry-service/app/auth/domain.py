from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Permission(StrEnum):
    TELEMETRY_READ = "telemetry.read"
    SESSION_READ = "sessions.read"
    SESSION_WRITE = "sessions.write"
    LAYOUT_READ = "layouts.read"
    LAYOUT_WRITE = "layouts.write"
    LAYOUT_PUBLISH = "layouts.publish"
    AUDIT_READ = "audit.read"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(
        {
            Permission.TELEMETRY_READ,
            Permission.SESSION_READ,
            Permission.LAYOUT_READ,
        }
    ),
    Role.OPERATOR: frozenset(
        {
            Permission.TELEMETRY_READ,
            Permission.SESSION_READ,
            Permission.SESSION_WRITE,
            Permission.LAYOUT_READ,
            Permission.LAYOUT_WRITE,
        }
    ),
    Role.ADMIN: frozenset(Permission),
}


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    organization_id: str
    role: Role
    permissions: frozenset[Permission]
    email: str | None = None
    display_name: str | None = None
    identity_id: str | None = None
    token_id: str | None = None
    provider: str = "jwt"

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


class AuthError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AuthenticationRequiredError(AuthError):
    def __init__(self, message: str = "authentication is required") -> None:
        super().__init__("authentication_required", message, status_code=401)


class InvalidTokenError(AuthError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=401)


class MembershipRequiredError(AuthError):
    def __init__(self, message: str = "active organization membership is required") -> None:
        super().__init__("organization_membership_required", message, status_code=403)


class PermissionDeniedError(AuthError):
    def __init__(self, permission: Permission) -> None:
        super().__init__(
            "permission_denied",
            f"permission {permission.value!r} is required",
            status_code=403,
        )
        self.permission = permission


def permissions_for_role(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def permission_for_http_request(method: str, path: str) -> Permission | None:
    normalized_method = method.upper()

    if path.startswith("/api/v1/telemetry") or path.startswith("/metrics"):
        return Permission.TELEMETRY_READ

    if path.startswith("/api/v1/sessions"):
        return (
            Permission.SESSION_READ
            if normalized_method in {"GET", "HEAD", "OPTIONS"}
            else Permission.SESSION_WRITE
        )

    if path.startswith("/api/v1/equipment"):
        if normalized_method in {"GET", "HEAD", "OPTIONS"}:
            return Permission.LAYOUT_READ
        if path.endswith("/layout/publish") or "/layout/history/" in path and path.endswith("/restore"):
            return Permission.LAYOUT_PUBLISH
        return Permission.LAYOUT_WRITE

    if path.startswith("/api/v1/audit"):
        return Permission.AUDIT_READ

    return None
