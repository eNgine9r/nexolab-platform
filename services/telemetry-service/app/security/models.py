from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.security.authorization import Permission, Role


_ROLE_VALUES = ", ".join(f"'{role.value}'" for role in Role)
_PERMISSION_VALUES = ", ".join(f"'{permission.value}'" for permission in Permission)


class SecurityOrganization(Base):
    __tablename__ = "security_organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityIdentity(Base):
    __tablename__ = "security_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "subject",
            name="uq_security_identity_provider_subject",
        ),
        Index("ix_security_identities_email", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityOrganizationMembership(Base):
    __tablename__ = "security_organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "identity_id",
            name="uq_security_membership_organization_identity",
        ),
        Index("ix_security_memberships_identity", "identity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_security_membership_organization",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    identity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_identities.id",
            name="fk_security_membership_identity",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityMembershipRole(Base):
    __tablename__ = "security_membership_roles"
    __table_args__ = (
        CheckConstraint(
            f"role IN ({_ROLE_VALUES})",
            name="ck_security_membership_role_known",
        ),
        Index("ix_security_membership_roles_role", "role"),
    )

    membership_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organization_memberships.id",
            name="fk_security_membership_role_membership",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    assigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityMembershipPermission(Base):
    __tablename__ = "security_membership_permissions"
    __table_args__ = (
        CheckConstraint(
            f"permission IN ({_PERMISSION_VALUES})",
            name="ck_security_membership_permission_known",
        ),
        Index("ix_security_membership_permissions_permission", "permission"),
    )

    membership_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organization_memberships.id",
            name="fk_security_membership_permission_membership",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    permission: Mapped[str] = mapped_column(String(128), primary_key=True)
    assigned_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityAuditEvent(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (
        Index(
            "ix_security_audit_organization_occurred",
            "organization_id",
            "occurred_at",
        ),
        Index(
            "ix_security_audit_entity",
            "organization_id",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_security_audit_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    actor_identity_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "security_identities.id",
            name="fk_security_audit_identity",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
