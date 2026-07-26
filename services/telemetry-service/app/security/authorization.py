from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import AbstractSet


class Role(StrEnum):
    ADMINISTRATOR = "administrator"
    LABORATORY_MANAGER = "laboratory_manager"
    ENGINEER = "engineer"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


class Permission(StrEnum):
    READ_DASHBOARD = "dashboard.read"
    READ_TELEMETRY = "telemetry.read"
    READ_ALERTS = "alerts.read"
    READ_AUDIT = "audit.read"
    READ_REPORTS = "reports.read"
    GENERATE_REPORTS = "reports.generate"
    MANAGE_MEMBERSHIPS = "memberships.manage"
    MANAGE_EQUIPMENT = "equipment.manage"
    EDIT_LAYOUT_DRAFT = "layout.draft.edit"
    PUBLISH_LAYOUT = "layout.publish"
    RESTORE_LAYOUT = "layout.restore"
    MANAGE_SESSIONS = "sessions.manage"
    OPERATE_SESSIONS = "sessions.operate"
    MANAGE_ALERT_RULES = "alerts.rules.manage"
    ACKNOWLEDGE_ALERTS = "alerts.acknowledge"
    APPROVE_REPORTS = "reports.approve"


_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMINISTRATOR: frozenset(Permission),
    Role.LABORATORY_MANAGER: frozenset(
        {
            Permission.READ_DASHBOARD,
            Permission.READ_TELEMETRY,
            Permission.READ_ALERTS,
            Permission.READ_AUDIT,
            Permission.READ_REPORTS,
            Permission.GENERATE_REPORTS,
            Permission.MANAGE_EQUIPMENT,
            Permission.EDIT_LAYOUT_DRAFT,
            Permission.PUBLISH_LAYOUT,
            Permission.RESTORE_LAYOUT,
            Permission.MANAGE_SESSIONS,
            Permission.OPERATE_SESSIONS,
            Permission.MANAGE_ALERT_RULES,
            Permission.ACKNOWLEDGE_ALERTS,
            Permission.APPROVE_REPORTS,
        }
    ),
    Role.ENGINEER: frozenset(
        {
            Permission.READ_DASHBOARD,
            Permission.READ_TELEMETRY,
            Permission.READ_ALERTS,
            Permission.READ_REPORTS,
            Permission.GENERATE_REPORTS,
            Permission.MANAGE_EQUIPMENT,
            Permission.EDIT_LAYOUT_DRAFT,
            Permission.PUBLISH_LAYOUT,
            Permission.RESTORE_LAYOUT,
            Permission.MANAGE_SESSIONS,
            Permission.OPERATE_SESSIONS,
            Permission.ACKNOWLEDGE_ALERTS,
        }
    ),
    Role.OPERATOR: frozenset(
        {
            Permission.READ_DASHBOARD,
            Permission.READ_TELEMETRY,
            Permission.READ_ALERTS,
            Permission.READ_REPORTS,
            Permission.EDIT_LAYOUT_DRAFT,
            Permission.OPERATE_SESSIONS,
            Permission.ACKNOWLEDGE_ALERTS,
        }
    ),
    Role.VIEWER: frozenset(
        {
            Permission.READ_DASHBOARD,
            Permission.READ_TELEMETRY,
            Permission.READ_ALERTS,
            Permission.READ_REPORTS,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.READ_DASHBOARD,
            Permission.READ_TELEMETRY,
            Permission.READ_ALERTS,
            Permission.READ_AUDIT,
            Permission.READ_REPORTS,
        }
    ),
}

ROLE_PERMISSIONS = MappingProxyType(_ROLE_PERMISSIONS)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    organization_id: str
    roles: frozenset[Role]
    email: str | None = None
    display_name: str | None = None
    provider: str = "oidc"

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.organization_id.strip():
            raise ValueError("organization_id is required")
        if not self.roles:
            raise ValueError("at least one role is required")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    code: str
    permission: Permission
    organization_id: str


def permissions_for_role(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def effective_permissions(roles: AbstractSet[Role]) -> frozenset[Permission]:
    permissions: set[Permission] = set()
    for role in roles:
        permissions.update(permissions_for_role(role))
    return frozenset(permissions)


def authorize(
    principal: AuthenticatedPrincipal,
    permission: Permission,
    *,
    resource_organization_id: str,
) -> AuthorizationDecision:
    if principal.organization_id != resource_organization_id:
        return AuthorizationDecision(
            allowed=False,
            code="organization_access_denied",
            permission=permission,
            organization_id=resource_organization_id,
        )

    if permission not in effective_permissions(principal.roles):
        return AuthorizationDecision(
            allowed=False,
            code="permission_denied",
            permission=permission,
            organization_id=resource_organization_id,
        )

    return AuthorizationDecision(
        allowed=True,
        code="authorized",
        permission=permission,
        organization_id=resource_organization_id,
    )
