from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import AuthenticatedPrincipal, Role
from app.security.models import (
    SecurityAuditEvent,
    SecurityIdentity,
    SecurityMembershipRole,
    SecurityOrganization,
    SecurityOrganizationMembership,
)


class SecurityRepositoryError(RuntimeError):
    code = "security_repository_error"


class IdentityNotProvisionedError(SecurityRepositoryError):
    code = "identity_not_provisioned"


class OrganizationMembershipNotFoundError(SecurityRepositoryError):
    code = "organization_membership_not_found"


@dataclass(frozen=True, slots=True)
class MembershipSummary:
    organization_id: str
    organization_slug: str
    organization_name: str
    roles: frozenset[Role]


@dataclass(frozen=True, slots=True)
class SecuritySession:
    identity_id: str
    provider: str
    subject: str
    email: str | None
    display_name: str | None
    memberships: tuple[MembershipSummary, ...]


@dataclass(frozen=True, slots=True)
class AuditEventInput:
    organization_id: str
    actor_identity_id: str | None
    actor_subject: str
    actor_roles: frozenset[Role]
    action: str
    entity_type: str
    entity_id: str
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    reason: str | None = None
    request_id: str | None = None
    source_ip: str | None = None
    user_agent: str | None = None


class SecurityRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def provision_organization(
        self,
        *,
        organization_id: str,
        slug: str,
        name: str,
    ) -> SecurityOrganization:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                organization = session.get(SecurityOrganization, organization_id)
                if organization is None:
                    organization = SecurityOrganization(
                        id=organization_id,
                        slug=slug,
                        name=name,
                        is_active=True,
                    )
                    session.add(organization)
                else:
                    organization.slug = slug
                    organization.name = name
                    organization.is_active = True
            session.expunge(organization)
            return organization

    def provision_membership(
        self,
        *,
        organization_id: str,
        claims: VerifiedIdentityClaims,
        roles: Iterable[Role],
        assigned_by: str | None = None,
    ) -> SecuritySession:
        resolved_roles = frozenset(roles)
        if not resolved_roles:
            raise ValueError("at least one role is required")

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                organization = session.get(SecurityOrganization, organization_id)
                if organization is None or not organization.is_active:
                    raise OrganizationMembershipNotFoundError(
                        f"organization {organization_id!r} is not active"
                    )
                identity = session.scalar(
                    select(SecurityIdentity).where(
                        SecurityIdentity.provider == claims.provider,
                        SecurityIdentity.subject == claims.subject,
                    )
                )
                now = datetime.now(UTC)
                if identity is None:
                    identity = SecurityIdentity(
                        id=str(uuid4()),
                        provider=claims.provider,
                        subject=claims.subject,
                        email=claims.email,
                        display_name=claims.display_name,
                        is_active=True,
                        created_at=now,
                        last_authenticated_at=now,
                    )
                    session.add(identity)
                    session.flush()
                else:
                    identity.email = claims.email
                    identity.display_name = claims.display_name
                    identity.is_active = True
                    identity.last_authenticated_at = now

                membership = session.scalar(
                    select(SecurityOrganizationMembership).where(
                        SecurityOrganizationMembership.organization_id
                        == organization_id,
                        SecurityOrganizationMembership.identity_id == identity.id,
                    )
                )
                if membership is None:
                    membership = SecurityOrganizationMembership(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        identity_id=identity.id,
                        is_active=True,
                        created_at=now,
                    )
                    session.add(membership)
                    session.flush()
                else:
                    membership.is_active = True

                existing_roles = session.scalars(
                    select(SecurityMembershipRole).where(
                        SecurityMembershipRole.membership_id == membership.id
                    )
                ).all()
                for assignment in existing_roles:
                    session.delete(assignment)
                session.flush()
                session.add_all(
                    SecurityMembershipRole(
                        membership_id=membership.id,
                        role=role.value,
                        assigned_by=assigned_by,
                        assigned_at=now,
                    )
                    for role in sorted(resolved_roles, key=lambda item: item.value)
                )

        return self.resolve_session(claims)

    def resolve_session(self, claims: VerifiedIdentityClaims) -> SecuritySession:
        with Session(self._engine) as session:
            identity = self._active_identity(session, claims)
            memberships = self._membership_summaries(session, identity.id)
            return SecuritySession(
                identity_id=identity.id,
                provider=identity.provider,
                subject=identity.subject,
                email=claims.email if claims.email is not None else identity.email,
                display_name=(
                    claims.display_name
                    if claims.display_name is not None
                    else identity.display_name
                ),
                memberships=memberships,
            )

    def resolve_principal(
        self,
        claims: VerifiedIdentityClaims,
        *,
        organization_id: str,
    ) -> tuple[str, AuthenticatedPrincipal]:
        security_session = self.resolve_session(claims)
        membership = next(
            (
                item
                for item in security_session.memberships
                if item.organization_id == organization_id
            ),
            None,
        )
        if membership is None:
            raise OrganizationMembershipNotFoundError(
                f"identity is not a member of organization {organization_id!r}"
            )
        return (
            security_session.identity_id,
            AuthenticatedPrincipal(
                subject=security_session.subject,
                organization_id=organization_id,
                roles=membership.roles,
                email=security_session.email,
                display_name=security_session.display_name,
                provider=security_session.provider,
            ),
        )

    def append_audit_event(
        self,
        event: AuditEventInput,
        *,
        session: Session | None = None,
    ) -> SecurityAuditEvent:
        row = SecurityAuditEvent(
            id=str(uuid4()),
            organization_id=event.organization_id,
            actor_identity_id=event.actor_identity_id,
            actor_subject=event.actor_subject,
            actor_roles=sorted(role.value for role in event.actor_roles),
            action=_required_text(event.action, "action", 128),
            entity_type=_required_text(event.entity_type, "entity_type", 128),
            entity_id=_required_text(event.entity_id, "entity_id", 255),
            before_snapshot=event.before_snapshot,
            after_snapshot=event.after_snapshot,
            reason=_optional_text(event.reason, 1024),
            request_id=_optional_text(event.request_id, 128),
            source_ip=_optional_text(event.source_ip, 64),
            user_agent=_optional_text(event.user_agent, 512),
            occurred_at=datetime.now(UTC),
        )
        if session is not None:
            session.add(row)
            session.flush()
            return row

        with Session(self._engine, expire_on_commit=False) as owned_session:
            with owned_session.begin():
                owned_session.add(row)
            owned_session.expunge(row)
            return row

    def list_audit_events(
        self,
        *,
        organization_id: str,
        limit: int,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[SecurityAuditEvent]:
        statement = (
            select(SecurityAuditEvent)
            .where(SecurityAuditEvent.organization_id == organization_id)
            .order_by(
                SecurityAuditEvent.occurred_at.desc(),
                SecurityAuditEvent.id.desc(),
            )
            .limit(limit)
        )
        if entity_type is not None:
            statement = statement.where(SecurityAuditEvent.entity_type == entity_type)
        if entity_id is not None:
            statement = statement.where(SecurityAuditEvent.entity_id == entity_id)

        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            for row in rows:
                session.expunge(row)
            return rows

    def _active_identity(
        self,
        session: Session,
        claims: VerifiedIdentityClaims,
    ) -> SecurityIdentity:
        identity = session.scalar(
            select(SecurityIdentity).where(
                SecurityIdentity.provider == claims.provider,
                SecurityIdentity.subject == claims.subject,
                SecurityIdentity.is_active.is_(True),
            )
        )
        if identity is None:
            raise IdentityNotProvisionedError("authenticated identity is not provisioned")
        return identity

    def _membership_summaries(
        self,
        session: Session,
        identity_id: str,
    ) -> tuple[MembershipSummary, ...]:
        rows = session.execute(
            select(
                SecurityOrganizationMembership.id,
                SecurityOrganization.id,
                SecurityOrganization.slug,
                SecurityOrganization.name,
            )
            .join(
                SecurityOrganization,
                SecurityOrganization.id
                == SecurityOrganizationMembership.organization_id,
            )
            .where(
                SecurityOrganizationMembership.identity_id == identity_id,
                SecurityOrganizationMembership.is_active.is_(True),
                SecurityOrganization.is_active.is_(True),
            )
            .order_by(SecurityOrganization.slug)
        ).all()
        result: list[MembershipSummary] = []
        for membership_id, organization_id, slug, name in rows:
            assigned_roles = session.scalars(
                select(SecurityMembershipRole.role).where(
                    SecurityMembershipRole.membership_id == membership_id
                )
            ).all()
            roles = frozenset(Role(role) for role in assigned_roles)
            if not roles:
                continue
            result.append(
                MembershipSummary(
                    organization_id=organization_id,
                    organization_slug=slug,
                    organization_name=name,
                    roles=roles,
                )
            )
        return tuple(result)


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _optional_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized
