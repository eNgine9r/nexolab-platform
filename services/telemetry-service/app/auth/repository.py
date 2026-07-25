from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.domain import (
    AuthError,
    MembershipRequiredError,
    Principal,
    Role,
    permissions_for_role,
)
from app.auth.models import (
    AuthIdentity,
    Organization,
    OrganizationMembership,
    PlatformAuditEvent,
    ResourceOrganizationBinding,
)
from app.db import Database


class ResourceOrganizationError(AuthError):
    def __init__(self) -> None:
        super().__init__(
            "resource_not_found",
            "resource was not found in the active organization",
            status_code=404,
        )


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[PlatformAuditEvent]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


class AuthRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def resolve_principal(
        self,
        claimed: Principal,
        *,
        auto_provision_memberships: bool,
    ) -> Principal:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                organization = db_session.get(Organization, claimed.organization_id)
                if organization is None:
                    if not auto_provision_memberships:
                        raise MembershipRequiredError()
                    organization = Organization(
                        id=claimed.organization_id,
                        slug=claimed.organization_id,
                        name=claimed.organization_id,
                        is_active=True,
                        created_at=now,
                    )
                    db_session.add(organization)
                    db_session.flush()
                if not organization.is_active:
                    raise MembershipRequiredError("organization is inactive")

                identity = db_session.scalar(
                    select(AuthIdentity).where(AuthIdentity.subject == claimed.subject)
                )
                if identity is None:
                    if not auto_provision_memberships:
                        raise MembershipRequiredError()
                    identity = AuthIdentity(
                        id=str(uuid4()),
                        subject=claimed.subject,
                        email=claimed.email,
                        display_name=claimed.display_name,
                        is_active=True,
                        created_at=now,
                        last_seen_at=now,
                    )
                    db_session.add(identity)
                    db_session.flush()
                if not identity.is_active:
                    raise MembershipRequiredError("identity is inactive")

                identity.email = claimed.email
                identity.display_name = claimed.display_name
                identity.last_seen_at = now

                membership = db_session.scalar(
                    select(OrganizationMembership).where(
                        OrganizationMembership.organization_id == organization.id,
                        OrganizationMembership.identity_id == identity.id,
                    )
                )
                if membership is None:
                    if not auto_provision_memberships:
                        raise MembershipRequiredError()
                    membership = OrganizationMembership(
                        id=str(uuid4()),
                        organization_id=organization.id,
                        identity_id=identity.id,
                        role=claimed.role.value,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                    db_session.add(membership)
                    db_session.flush()
                if not membership.is_active:
                    raise MembershipRequiredError()

                try:
                    effective_role = Role(membership.role)
                except ValueError as error:
                    raise MembershipRequiredError("membership role is invalid") from error

            return Principal(
                subject=identity.subject,
                organization_id=organization.id,
                role=effective_role,
                permissions=permissions_for_role(effective_role),
                email=identity.email,
                display_name=identity.display_name,
                identity_id=identity.id,
                token_id=claimed.token_id,
                provider=claimed.provider,
            )

    def ensure_resource_access(
        self,
        principal: Principal,
        *,
        resource_type: str,
        resource_id: str,
        create_if_missing: bool,
    ) -> None:
        with Session(self._engine) as db_session:
            with db_session.begin():
                binding = db_session.scalar(
                    select(ResourceOrganizationBinding).where(
                        ResourceOrganizationBinding.resource_type == resource_type,
                        ResourceOrganizationBinding.resource_id == resource_id,
                    )
                )
                if binding is None:
                    if not create_if_missing:
                        raise ResourceOrganizationError()
                    binding = ResourceOrganizationBinding(
                        id=str(uuid4()),
                        organization_id=principal.organization_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        created_by_identity_id=principal.identity_id,
                    )
                    db_session.add(binding)
                    return
                if binding.organization_id != principal.organization_id:
                    raise ResourceOrganizationError()

    def record_audit(
        self,
        *,
        principal: Principal | None,
        action: str,
        outcome: str,
        resource_type: str,
        resource_id: str,
        request_id: str,
        metadata_payload: dict[str, Any] | None = None,
    ) -> PlatformAuditEvent:
        event = PlatformAuditEvent(
            id=str(uuid4()),
            organization_id=principal.organization_id if principal else None,
            actor_identity_id=principal.identity_id if principal else None,
            actor_subject=principal.subject if principal else None,
            actor_role=principal.role.value if principal else None,
            action=action[:128],
            outcome=outcome[:32],
            resource_type=resource_type[:64],
            resource_id=resource_id[:256],
            request_id=request_id[:128],
            metadata_payload=dict(metadata_payload or {}),
            occurred_at=datetime.now(UTC),
        )
        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                db_session.add(event)
            db_session.expunge(event)
        return event

    def list_audit(
        self,
        *,
        organization_id: str,
        action: str | None,
        outcome: str | None,
        resource_type: str | None,
        resource_id: str | None,
        limit: int,
        offset: int,
    ) -> AuditPage:
        filters = [PlatformAuditEvent.organization_id == organization_id]
        if action is not None:
            filters.append(PlatformAuditEvent.action == action)
        if outcome is not None:
            filters.append(PlatformAuditEvent.outcome == outcome)
        if resource_type is not None:
            filters.append(PlatformAuditEvent.resource_type == resource_type)
        if resource_id is not None:
            filters.append(PlatformAuditEvent.resource_id == resource_id)

        with Session(self._engine) as db_session:
            count = int(
                db_session.scalar(
                    select(func.count()).select_from(PlatformAuditEvent).where(*filters)
                )
                or 0
            )
            items = list(
                db_session.scalars(
                    select(PlatformAuditEvent)
                    .where(*filters)
                    .order_by(PlatformAuditEvent.occurred_at.desc(), PlatformAuditEvent.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            for item in items:
                db_session.expunge(item)
        return AuditPage(items=items, count=count, limit=limit, offset=offset)
