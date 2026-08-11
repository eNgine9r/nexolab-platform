from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.security.authorization import (
    GRANTABLE_PERMISSIONS,
    PRODUCT_ROLES,
    AuthenticatedPrincipal,
    Permission,
    Role,
    effective_permissions_from_grants,
)
from app.security.local_models import SecurityLocalAccount, SecurityLocalSession
from app.security.local_repository import LOCAL_AUTH_PROVIDER, normalize_optional, normalize_username
from app.security.models import (
    SecurityIdentity,
    SecurityMembershipPermission,
    SecurityMembershipRole,
    SecurityOrganization,
    SecurityOrganizationMembership,
)
from app.security.passwords import hash_password
from app.security.repository import AuditEventInput, SecurityRepository


class LocalUserAdminError(RuntimeError):
    code = "local_user_admin_error"


class LocalUserNotFoundError(LocalUserAdminError):
    code = "local_user_not_found"


class LocalUserConflictError(LocalUserAdminError):
    code = "local_user_conflict"


class LocalUserValidationError(LocalUserAdminError):
    code = "local_user_validation_error"


class LastAdministratorError(LocalUserConflictError):
    code = "last_active_administrator"


@dataclass(frozen=True, slots=True)
class LocalUserRecord:
    account_id: str
    identity_id: str
    membership_id: str
    username: str
    email: str | None
    display_name: str | None
    is_active: bool
    roles: tuple[str, ...]
    granted_permissions: frozenset[Permission]
    effective_permissions: frozenset[Permission]
    created_at: datetime
    password_changed_at: datetime
    last_authenticated_at: datetime
    locked_until: datetime | None

    @property
    def product_role(self) -> Role | None:
        if len(self.roles) != 1:
            return None
        try:
            role = Role(self.roles[0])
        except ValueError:
            return None
        return role if role in PRODUCT_ROLES else None

    @property
    def migration_required(self) -> bool:
        return self.product_role is None


class LocalUserAdminService:
    def __init__(
        self,
        database: Database,
        security_repository: SecurityRepository,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository

    def list_users(self, *, organization_id: str) -> tuple[LocalUserRecord, ...]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(
                    SecurityLocalAccount,
                    SecurityIdentity,
                    SecurityOrganizationMembership,
                )
                .join(
                    SecurityIdentity,
                    SecurityIdentity.id == SecurityLocalAccount.identity_id,
                )
                .join(
                    SecurityOrganizationMembership,
                    SecurityOrganizationMembership.identity_id == SecurityIdentity.id,
                )
                .where(
                    SecurityOrganizationMembership.organization_id == organization_id
                )
                .order_by(SecurityLocalAccount.username)
            ).all()
            return tuple(
                self._record(session, account, identity, membership)
                for account, identity, membership in rows
            )

    def get_user(
        self,
        *,
        organization_id: str,
        account_id: str,
    ) -> LocalUserRecord:
        with Session(self._engine) as session:
            account, identity, membership = self._target(
                session,
                organization_id=organization_id,
                account_id=account_id,
                for_update=False,
            )
            return self._record(session, account, identity, membership)

    def create_user(
        self,
        *,
        organization_id: str,
        username: str,
        password: str,
        role: str,
        permissions: Iterable[Permission],
        email: str | None,
        display_name: str | None,
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> LocalUserRecord:
        normalized_username = normalize_username(username)
        resolved_role = self._product_role(role)
        resolved_permissions = self._validated_permissions(
            permissions,
            role=resolved_role,
        )
        password_hash = hash_password(password)
        now = datetime.now(UTC)
        account_id = str(uuid4())
        identity_id = str(uuid4())
        membership_id = str(uuid4())

        try:
            with Session(self._engine) as session:
                with session.begin():
                    organization = session.get(SecurityOrganization, organization_id)
                    if organization is None or not organization.is_active:
                        raise LocalUserNotFoundError(
                            f"organization {organization_id!r} is not active"
                        )
                    existing = session.scalar(
                        select(SecurityLocalAccount.id).where(
                            SecurityLocalAccount.username == normalized_username
                        )
                    )
                    if existing is not None:
                        raise LocalUserConflictError(
                            f"local username {normalized_username!r} already exists"
                        )

                    identity = SecurityIdentity(
                        id=identity_id,
                        provider=LOCAL_AUTH_PROVIDER,
                        subject=account_id,
                        email=normalize_optional(email),
                        display_name=normalize_optional(display_name),
                        is_active=True,
                        created_at=now,
                        last_authenticated_at=now,
                    )
                    account = SecurityLocalAccount(
                        id=account_id,
                        identity_id=identity_id,
                        username=normalized_username,
                        password_hash=password_hash,
                        is_active=True,
                        failed_login_count=0,
                        locked_until=None,
                        password_changed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    membership = SecurityOrganizationMembership(
                        id=membership_id,
                        organization_id=organization_id,
                        identity_id=identity_id,
                        is_active=True,
                        created_at=now,
                    )
                    # These mapped objects do not have ORM relationships linking their
                    # dependency graph. Flush the identity first so PostgreSQL never sees
                    # account/membership foreign keys before their parent identity row.
                    session.add(identity)
                    session.flush()
                    session.add_all((account, membership))
                    session.flush()
                    session.add(
                        SecurityMembershipRole(
                            membership_id=membership_id,
                            role=resolved_role.value,
                            assigned_by=actor.subject,
                            assigned_at=now,
                        )
                    )
                    if resolved_role != Role.ADMINISTRATOR:
                        session.add_all(
                            SecurityMembershipPermission(
                                membership_id=membership_id,
                                permission=permission.value,
                                assigned_by=actor.subject,
                                assigned_at=now,
                            )
                            for permission in sorted(
                                resolved_permissions,
                                key=lambda item: item.value,
                            )
                        )
                    self._audit(
                        session,
                        organization_id=organization_id,
                        actor_identity_id=actor_identity_id,
                        actor=actor,
                        action="security.local_user.created",
                        entity_id=account_id,
                        after_snapshot={
                            "username": normalized_username,
                            "identity_id": identity_id,
                            "role": resolved_role.value,
                            "permissions": sorted(
                                permission.value
                                for permission in (
                                    frozenset(Permission)
                                    if resolved_role == Role.ADMINISTRATOR
                                    else resolved_permissions
                                )
                            ),
                            "is_active": True,
                        },
                        reason=reason,
                        request_id=request_id,
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )
        except IntegrityError as error:
            if self._is_username_conflict(error):
                raise LocalUserConflictError(
                    f"local username {normalized_username!r} already exists"
                ) from error
            raise

        return self.get_user(
            organization_id=organization_id,
            account_id=account_id,
        )

    def update_user(
        self,
        *,
        organization_id: str,
        account_id: str,
        role: str | None,
        is_active: bool | None,
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> LocalUserRecord:
        resolved_role = self._product_role(role) if role is not None else None
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            with session.begin():
                account, identity, membership = self._target(
                    session,
                    organization_id=organization_id,
                    account_id=account_id,
                    for_update=True,
                )
                current_roles = self._role_values(session, membership.id)
                current_active = bool(
                    account.is_active and identity.is_active and membership.is_active
                )
                removes_admin = (
                    Role.ADMINISTRATOR.value in current_roles
                    and (
                        (resolved_role is not None and resolved_role != Role.ADMINISTRATOR)
                        or is_active is False
                    )
                )
                if removes_admin and current_active:
                    self._assert_not_last_active_administrator(
                        session,
                        organization_id=organization_id,
                        account_id=account.id,
                    )

                role_changed = (
                    resolved_role is not None
                    and current_roles != (resolved_role.value,)
                )
                active_changed = (
                    is_active is not None and is_active != current_active
                )

                if role_changed:
                    session.execute(
                        delete(SecurityMembershipRole).where(
                            SecurityMembershipRole.membership_id == membership.id
                        )
                    )
                    session.add(
                        SecurityMembershipRole(
                            membership_id=membership.id,
                            role=resolved_role.value,
                            assigned_by=actor.subject,
                            assigned_at=now,
                        )
                    )
                    if resolved_role == Role.ADMINISTRATOR:
                        session.execute(
                            delete(SecurityMembershipPermission).where(
                                SecurityMembershipPermission.membership_id
                                == membership.id
                            )
                        )
                    self._audit(
                        session,
                        organization_id=organization_id,
                        actor_identity_id=actor_identity_id,
                        actor=actor,
                        action="security.local_user.role_changed",
                        entity_id=account.id,
                        before_snapshot={"roles": list(current_roles)},
                        after_snapshot={"roles": [resolved_role.value]},
                        reason=reason,
                        request_id=request_id,
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )

                if active_changed:
                    assert is_active is not None
                    account.is_active = is_active
                    identity.is_active = is_active
                    membership.is_active = is_active
                    account.updated_at = now
                    self._audit(
                        session,
                        organization_id=organization_id,
                        actor_identity_id=actor_identity_id,
                        actor=actor,
                        action=(
                            "security.local_user.activated"
                            if is_active
                            else "security.local_user.deactivated"
                        ),
                        entity_id=account.id,
                        before_snapshot={"is_active": current_active},
                        after_snapshot={"is_active": is_active},
                        reason=reason,
                        request_id=request_id,
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )

                if role_changed or active_changed:
                    self._revoke_sessions(session, account.id, now)

        return self.get_user(
            organization_id=organization_id,
            account_id=account_id,
        )

    def set_permissions(
        self,
        *,
        organization_id: str,
        account_id: str,
        permissions: Iterable[Permission],
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> LocalUserRecord:
        if actor_identity_id is not None:
            with Session(self._engine) as lookup_session:
                target_identity = lookup_session.scalar(
                    select(SecurityLocalAccount.identity_id).where(
                        SecurityLocalAccount.id == account_id
                    )
                )
            if target_identity == actor_identity_id:
                raise LocalUserConflictError(
                    "administrators cannot grant permissions to their own account"
                )

        now = datetime.now(UTC)
        with Session(self._engine) as session:
            with session.begin():
                account, _, membership = self._target(
                    session,
                    organization_id=organization_id,
                    account_id=account_id,
                    for_update=True,
                )
                roles = self._role_values(session, membership.id)
                if len(roles) != 1:
                    raise LocalUserConflictError(
                        "legacy or multi-role membership must be migrated before editing permissions"
                    )
                role = self._product_role(roles[0])
                if role == Role.ADMINISTRATOR:
                    raise LocalUserConflictError(
                        "administrator permissions are implicit and cannot be edited"
                    )
                resolved_permissions = self._validated_permissions(
                    permissions,
                    role=role,
                )
                before = self._permission_values(session, membership.id)
                after = tuple(
                    permission.value
                    for permission in sorted(
                        resolved_permissions,
                        key=lambda item: item.value,
                    )
                )
                if before != after:
                    session.execute(
                        delete(SecurityMembershipPermission).where(
                            SecurityMembershipPermission.membership_id
                            == membership.id
                        )
                    )
                    session.add_all(
                        SecurityMembershipPermission(
                            membership_id=membership.id,
                            permission=permission.value,
                            assigned_by=actor.subject,
                            assigned_at=now,
                        )
                        for permission in sorted(
                            resolved_permissions,
                            key=lambda item: item.value,
                        )
                    )
                    self._revoke_sessions(session, account.id, now)
                    self._audit(
                        session,
                        organization_id=organization_id,
                        actor_identity_id=actor_identity_id,
                        actor=actor,
                        action="security.local_user.permissions_changed",
                        entity_id=account.id,
                        before_snapshot={"permissions": list(before)},
                        after_snapshot={"permissions": list(after)},
                        reason=reason,
                        request_id=request_id,
                        source_ip=source_ip,
                        user_agent=user_agent,
                    )

        return self.get_user(
            organization_id=organization_id,
            account_id=account_id,
        )

    def reset_password(
        self,
        *,
        organization_id: str,
        account_id: str,
        password: str,
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None:
        password_hash = hash_password(password)
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            with session.begin():
                account, _, _ = self._target(
                    session,
                    organization_id=organization_id,
                    account_id=account_id,
                    for_update=True,
                )
                account.password_hash = password_hash
                account.password_changed_at = now
                account.failed_login_count = 0
                account.locked_until = None
                account.updated_at = now
                self._revoke_sessions(session, account.id, now)
                self._audit(
                    session,
                    organization_id=organization_id,
                    actor_identity_id=actor_identity_id,
                    actor=actor,
                    action="security.local_user.password_reset",
                    entity_id=account.id,
                    after_snapshot={
                        "password_changed_at": now.isoformat(),
                        "sessions_revoked": True,
                    },
                    reason=reason,
                    request_id=request_id,
                    source_ip=source_ip,
                    user_agent=user_agent,
                )

    def revoke_sessions(
        self,
        *,
        organization_id: str,
        account_id: str,
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> int:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            with session.begin():
                account, _, _ = self._target(
                    session,
                    organization_id=organization_id,
                    account_id=account_id,
                    for_update=True,
                )
                count = self._revoke_sessions(session, account.id, now)
                self._audit(
                    session,
                    organization_id=organization_id,
                    actor_identity_id=actor_identity_id,
                    actor=actor,
                    action="security.local_user.sessions_revoked",
                    entity_id=account.id,
                    after_snapshot={"revoked_session_count": count},
                    reason=reason,
                    request_id=request_id,
                    source_ip=source_ip,
                    user_agent=user_agent,
                )
                return count

    @staticmethod
    def _is_username_conflict(error: IntegrityError) -> bool:
        original = error.orig
        diagnostic = getattr(original, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        if constraint_name == "uq_security_local_accounts_username":
            return True
        return (
            "UNIQUE constraint failed: security_local_accounts.username"
            in str(original)
        )

    @staticmethod
    def _product_role(value: str) -> Role:
        try:
            role = Role(value)
        except ValueError as error:
            raise LocalUserValidationError(
                f"unsupported product role {value!r}"
            ) from error
        if role not in PRODUCT_ROLES:
            raise LocalUserValidationError(
                f"legacy role {value!r} cannot be assigned"
            )
        return role

    @staticmethod
    def _validated_permissions(
        permissions: Iterable[Permission],
        *,
        role: Role,
    ) -> frozenset[Permission]:
        resolved = frozenset(permissions)
        if role == Role.ADMINISTRATOR:
            if resolved:
                raise LocalUserValidationError(
                    "administrator permissions are implicit and must not be supplied"
                )
            return frozenset()
        forbidden = resolved - GRANTABLE_PERMISSIONS
        if forbidden:
            names = ", ".join(sorted(item.value for item in forbidden))
            raise LocalUserValidationError(
                f"administrator-only permissions cannot be granted: {names}"
            )
        return resolved

    def _target(
        self,
        session: Session,
        *,
        organization_id: str,
        account_id: str,
        for_update: bool,
    ) -> tuple[
        SecurityLocalAccount,
        SecurityIdentity,
        SecurityOrganizationMembership,
    ]:
        statement = (
            select(
                SecurityLocalAccount,
                SecurityIdentity,
                SecurityOrganizationMembership,
            )
            .join(
                SecurityIdentity,
                SecurityIdentity.id == SecurityLocalAccount.identity_id,
            )
            .join(
                SecurityOrganizationMembership,
                SecurityOrganizationMembership.identity_id == SecurityIdentity.id,
            )
            .where(
                SecurityLocalAccount.id == account_id,
                SecurityOrganizationMembership.organization_id == organization_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.execute(statement).one_or_none()
        if row is None:
            raise LocalUserNotFoundError(
                f"local user {account_id!r} was not found in this organization"
            )
        return row

    def _record(
        self,
        session: Session,
        account: SecurityLocalAccount,
        identity: SecurityIdentity,
        membership: SecurityOrganizationMembership,
    ) -> LocalUserRecord:
        roles = self._role_values(session, membership.id)
        granted = frozenset(
            Permission(value)
            for value in self._permission_values(session, membership.id)
        )
        parsed_roles = frozenset(Role(value) for value in roles)
        effective = effective_permissions_from_grants(parsed_roles, granted)
        return LocalUserRecord(
            account_id=account.id,
            identity_id=identity.id,
            membership_id=membership.id,
            username=account.username,
            email=identity.email,
            display_name=identity.display_name,
            is_active=bool(
                account.is_active and identity.is_active and membership.is_active
            ),
            roles=roles,
            granted_permissions=granted,
            effective_permissions=effective,
            created_at=account.created_at,
            password_changed_at=account.password_changed_at,
            last_authenticated_at=identity.last_authenticated_at,
            locked_until=account.locked_until,
        )

    @staticmethod
    def _role_values(session: Session, membership_id: str) -> tuple[str, ...]:
        return tuple(
            session.scalars(
                select(SecurityMembershipRole.role)
                .where(SecurityMembershipRole.membership_id == membership_id)
                .order_by(SecurityMembershipRole.role)
            ).all()
        )

    @staticmethod
    def _permission_values(
        session: Session,
        membership_id: str,
    ) -> tuple[str, ...]:
        return tuple(
            session.scalars(
                select(SecurityMembershipPermission.permission)
                .where(SecurityMembershipPermission.membership_id == membership_id)
                .order_by(SecurityMembershipPermission.permission)
            ).all()
        )

    @staticmethod
    def _revoke_sessions(
        session: Session,
        account_id: str,
        now: datetime,
    ) -> int:
        rows = session.scalars(
            select(SecurityLocalSession).where(
                SecurityLocalSession.account_id == account_id,
                SecurityLocalSession.revoked_at.is_(None),
            )
        ).all()
        for row in rows:
            row.revoked_at = now
        return len(rows)

    @staticmethod
    def _active_admin_count(
        session: Session,
        *,
        organization_id: str,
    ) -> int:
        count = session.scalar(
            select(func.count())
            .select_from(SecurityLocalAccount)
            .join(
                SecurityIdentity,
                SecurityIdentity.id == SecurityLocalAccount.identity_id,
            )
            .join(
                SecurityOrganizationMembership,
                SecurityOrganizationMembership.identity_id == SecurityIdentity.id,
            )
            .join(
                SecurityMembershipRole,
                SecurityMembershipRole.membership_id
                == SecurityOrganizationMembership.id,
            )
            .where(
                SecurityOrganizationMembership.organization_id == organization_id,
                SecurityLocalAccount.is_active.is_(True),
                SecurityIdentity.is_active.is_(True),
                SecurityOrganizationMembership.is_active.is_(True),
                SecurityMembershipRole.role == Role.ADMINISTRATOR.value,
            )
        )
        return int(count or 0)

    def _assert_not_last_active_administrator(
        self,
        session: Session,
        *,
        organization_id: str,
        account_id: str,
    ) -> None:
        if self._active_admin_count(
            session,
            organization_id=organization_id,
        ) <= 1:
            raise LastAdministratorError(
                f"local administrator {account_id!r} is the last active administrator"
            )

    def _audit(
        self,
        session: Session,
        *,
        organization_id: str,
        actor_identity_id: str | None,
        actor: AuthenticatedPrincipal,
        action: str,
        entity_id: str,
        before_snapshot: dict[str, object] | None = None,
        after_snapshot: dict[str, object] | None = None,
        reason: str | None,
        request_id: str | None,
        source_ip: str | None,
        user_agent: str | None,
    ) -> None:
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=organization_id,
                actor_identity_id=actor_identity_id,
                actor_subject=actor.subject,
                actor_roles=actor.roles,
                action=action,
                entity_type="local_user",
                entity_id=entity_id,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                reason=reason,
                request_id=request_id,
                source_ip=source_ip,
                user_agent=user_agent,
            ),
            session=session,
        )
