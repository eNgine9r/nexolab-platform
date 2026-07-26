from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.nodes.domain import ClockStatus, NodeState


_NODE_STATES = ", ".join(f"'{item.value}'" for item in NodeState)
_CLOCK_STATUSES = ", ".join(f"'{item.value}'" for item in ClockStatus)


class CentralNode(Base):
    __tablename__ = "central_nodes"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "node_id",
            name="uq_central_nodes_organization_node",
        ),
        CheckConstraint(
            f"state IN ({_NODE_STATES})",
            name="ck_central_nodes_state",
        ),
        CheckConstraint(
            f"clock_status IN ({_CLOCK_STATUSES})",
            name="ck_central_nodes_clock_status",
        ),
        CheckConstraint(
            "clock_warning_ms > 0 AND clock_critical_ms > clock_warning_ms",
            name="ck_central_nodes_clock_thresholds",
        ),
        Index(
            "ix_central_nodes_organization_state",
            "organization_id",
            "state",
            "node_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_central_nodes_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=NodeState.PENDING.value,
        server_default=NodeState.PENDING.value,
    )
    state_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    clock_warning_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30_000,
        server_default=text("30000"),
    )
    clock_critical_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120_000,
        server_default=text("120000"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_clock_offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clock_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ClockStatus.UNKNOWN.value,
        server_default=ClockStatus.UNKNOWN.value,
    )
    clock_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CentralNodeCredential(Base):
    __tablename__ = "central_node_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_central_node_credentials_organization_idempotency",
        ),
        UniqueConstraint(
            "node_record_id",
            "generation",
            name="uq_central_node_credentials_node_generation",
        ),
        CheckConstraint(
            "generation >= 1",
            name="ck_central_node_credentials_generation",
        ),
        Index(
            "ix_central_node_credentials_active_lookup",
            "organization_id",
            "node_record_id",
            "revoked_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_central_node_credentials_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    node_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "central_nodes.id",
            name="fk_central_node_credentials_node",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_by: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
