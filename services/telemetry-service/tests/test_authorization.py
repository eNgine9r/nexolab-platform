from __future__ import annotations

import pytest

from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    authorize,
    effective_permissions,
    permissions_for_role,
)


def principal(*roles: Role, organization_id: str = "org-lab-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="user-1",
        organization_id=organization_id,
        roles=frozenset(roles),
        email="operator@nexolab.example",
    )


def test_administrator_has_every_permission() -> None:
    assert permissions_for_role(Role.ADMINISTRATOR) == frozenset(Permission)


def test_viewer_is_read_only() -> None:
    permissions = permissions_for_role(Role.VIEWER)

    assert Permission.READ_DASHBOARD in permissions
    assert Permission.READ_TELEMETRY in permissions
    assert Permission.READ_REPORTS in permissions
    assert Permission.EDIT_LAYOUT_DRAFT not in permissions
    assert Permission.PUBLISH_LAYOUT not in permissions
    assert Permission.MANAGE_MEMBERSHIPS not in permissions


def test_auditor_can_read_audit_without_mutation_permissions() -> None:
    permissions = permissions_for_role(Role.AUDITOR)

    assert Permission.READ_AUDIT in permissions
    assert Permission.MANAGE_SESSIONS not in permissions
    assert Permission.ACKNOWLEDGE_ALERTS not in permissions


def test_operator_can_edit_draft_but_cannot_publish_or_restore() -> None:
    permissions = permissions_for_role(Role.OPERATOR)

    assert Permission.EDIT_LAYOUT_DRAFT in permissions
    assert Permission.PUBLISH_LAYOUT not in permissions
    assert Permission.RESTORE_LAYOUT not in permissions


def test_multiple_roles_union_permissions() -> None:
    permissions = effective_permissions({Role.OPERATOR, Role.AUDITOR})

    assert Permission.EDIT_LAYOUT_DRAFT in permissions
    assert Permission.READ_AUDIT in permissions
    assert Permission.PUBLISH_LAYOUT not in permissions


def test_authorization_denies_cross_organization_access_before_role_check() -> None:
    decision = authorize(
        principal(Role.ADMINISTRATOR),
        Permission.READ_DASHBOARD,
        resource_organization_id="org-lab-2",
    )

    assert decision.allowed is False
    assert decision.code == "organization_access_denied"


def test_authorization_denies_missing_permission() -> None:
    decision = authorize(
        principal(Role.VIEWER),
        Permission.PUBLISH_LAYOUT,
        resource_organization_id="org-lab-1",
    )

    assert decision.allowed is False
    assert decision.code == "permission_denied"


def test_authorization_allows_matching_scope_and_permission() -> None:
    decision = authorize(
        principal(Role.ENGINEER),
        Permission.PUBLISH_LAYOUT,
        resource_organization_id="org-lab-1",
    )

    assert decision.allowed is True
    assert decision.code == "authorized"


@pytest.mark.parametrize("field", ["subject", "organization_id"])
def test_principal_rejects_blank_identity_fields(field: str) -> None:
    values = {
        "subject": "user-1",
        "organization_id": "org-lab-1",
        "roles": frozenset({Role.VIEWER}),
    }
    values[field] = "   "

    with pytest.raises(ValueError):
        AuthenticatedPrincipal(**values)


def test_principal_requires_at_least_one_role() -> None:
    with pytest.raises(ValueError):
        AuthenticatedPrincipal(
            subject="user-1",
            organization_id="org-lab-1",
            roles=frozenset(),
        )
