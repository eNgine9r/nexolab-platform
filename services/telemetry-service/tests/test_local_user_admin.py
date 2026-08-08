from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db import Database
from app.model_registry import register_models
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import (
    AuthenticatedPrincipal,
    Permission,
    Role,
    authorize,
)
from app.security.local_admin_service import (
    LastAdministratorError,
    LocalUserAdminService,
    LocalUserValidationError,
)
from app.security.local_repository import (
    LOCAL_AUTH_PROVIDER,
    LocalAuthRepository,
    LocalSessionInvalidError,
)
from app.security.passwords import hash_password
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def build_runtime(
    tmp_path: Path,
) -> tuple[
    Database,
    SecurityRepository,
    LocalAuthRepository,
    LocalUserAdminService,
    AuthenticatedPrincipal,
    str,
]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'local-user-admin.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    local = LocalAuthRepository(database)
    admin_account = local.bootstrap_account(
        username="admin",
        password_hash=hash_password("Admin-password-123"),
        email=None,
        display_name="Administrator",
        organization_id=ORGANIZATION_ID,
        organization_slug="nexolab",
        organization_name="NEXOLAB",
        roles={Role.ADMINISTRATOR},
    )
    actor = AuthenticatedPrincipal(
        subject=admin_account.subject,
        organization_id=ORGANIZATION_ID,
        roles=frozenset({Role.ADMINISTRATOR}),
        provider=LOCAL_AUTH_PROVIDER,
        granted_permissions=frozenset(),
    )
    return (
        database,
        security,
        local,
        LocalUserAdminService(database, security),
        actor,
        admin_account.identity_id,
    )


def create_engineer(
    service: LocalUserAdminService,
    *,
    actor: AuthenticatedPrincipal,
    actor_identity_id: str,
):
    return service.create_user(
        organization_id=ORGANIZATION_ID,
        username="engineer.one",
        password="Engineer-password-123",
        role=Role.ENGINEER.value,
        permissions={Permission.READ_DASHBOARD},
        email="engineer@example.test",
        display_name="Engineer One",
        actor_identity_id=actor_identity_id,
        actor=actor,
        reason="test setup",
        request_id="request-1",
        source_ip="127.0.0.1",
        user_agent="pytest",
    )


def test_local_user_explicit_permissions_are_server_authoritative(
    tmp_path: Path,
) -> None:
    database, security, _, service, actor, actor_identity_id = build_runtime(
        tmp_path
    )
    user = create_engineer(
        service,
        actor=actor,
        actor_identity_id=actor_identity_id,
    )

    assert user.product_role == Role.ENGINEER
    assert user.granted_permissions == frozenset({Permission.READ_DASHBOARD})
    assert Permission.READ_DASHBOARD in user.effective_permissions
    assert Permission.READ_NODES not in user.effective_permissions

    _, principal = security.resolve_principal(
        VerifiedIdentityClaims(
            provider=LOCAL_AUTH_PROVIDER,
            subject=user.account_id,
        ),
        organization_id=ORGANIZATION_ID,
    )
    assert authorize(
        principal,
        Permission.READ_DASHBOARD,
        resource_organization_id=ORGANIZATION_ID,
    ).allowed
    assert not authorize(
        principal,
        Permission.READ_NODES,
        resource_organization_id=ORGANIZATION_ID,
    ).allowed
    database.dispose()


def test_permission_change_revokes_active_local_session(tmp_path: Path) -> None:
    database, _, local, service, actor, actor_identity_id = build_runtime(tmp_path)
    user = create_engineer(
        service,
        actor=actor,
        actor_identity_id=actor_identity_id,
    )
    now = datetime.now(UTC)
    session_id = local.create_session(
        account_id=user.account_id,
        refresh_token_hash="a" * 64,
        expires_at=now + timedelta(hours=1),
        source_ip="127.0.0.1",
        user_agent="pytest",
        now=now,
    )

    service.set_permissions(
        organization_id=ORGANIZATION_ID,
        account_id=user.account_id,
        permissions={Permission.READ_DASHBOARD, Permission.READ_TELEMETRY},
        actor_identity_id=actor_identity_id,
        actor=actor,
        reason="grant telemetry",
        request_id="request-2",
        source_ip="127.0.0.1",
        user_agent="pytest",
    )

    with pytest.raises(LocalSessionInvalidError):
        local.validate_access_session(
            session_id=session_id,
            subject=user.account_id,
            now=now + timedelta(seconds=1),
        )
    database.dispose()


def test_non_admin_cannot_receive_administrator_only_permissions(
    tmp_path: Path,
) -> None:
    database, _, _, service, actor, actor_identity_id = build_runtime(tmp_path)

    with pytest.raises(LocalUserValidationError):
        service.create_user(
            organization_id=ORGANIZATION_ID,
            username="manager.one",
            password="Manager-password-123",
            role=Role.LABORATORY_MANAGER.value,
            permissions={Permission.MANAGE_MEMBERSHIPS},
            email=None,
            display_name=None,
            actor_identity_id=actor_identity_id,
            actor=actor,
            reason=None,
            request_id=None,
            source_ip=None,
            user_agent=None,
        )
    database.dispose()


def test_last_active_local_administrator_cannot_be_deactivated(
    tmp_path: Path,
) -> None:
    database, _, local, service, actor, actor_identity_id = build_runtime(tmp_path)
    admin = local.get_account("admin")

    with pytest.raises(LastAdministratorError):
        service.update_user(
            organization_id=ORGANIZATION_ID,
            account_id=admin.id,
            role=None,
            is_active=False,
            actor_identity_id=actor_identity_id,
            actor=actor,
            reason="unsafe test",
            request_id=None,
            source_ip=None,
            user_agent=None,
        )
    database.dispose()


def test_password_reset_audit_never_contains_password_or_hash(
    tmp_path: Path,
) -> None:
    database, security, _, service, actor, actor_identity_id = build_runtime(tmp_path)
    user = create_engineer(
        service,
        actor=actor,
        actor_identity_id=actor_identity_id,
    )
    secret = "Replacement-password-456"

    service.reset_password(
        organization_id=ORGANIZATION_ID,
        account_id=user.account_id,
        password=secret,
        actor_identity_id=actor_identity_id,
        actor=actor,
        reason="credential rotation",
        request_id="request-3",
        source_ip="127.0.0.1",
        user_agent="pytest",
    )

    events = security.list_audit_events(
        organization_id=ORGANIZATION_ID,
        limit=20,
    )
    reset = next(
        event
        for event in events
        if event.action == "security.local_user.password_reset"
    )
    serialized = repr((reset.before_snapshot, reset.after_snapshot))
    assert secret not in serialized
    assert "scrypt$" not in serialized
    database.dispose()
