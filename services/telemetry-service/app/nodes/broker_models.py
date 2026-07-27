from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.nodes.broker_control import BrokerControlOperation, BrokerControlState


_OPERATIONS = ", ".join(f"'{item.value}'" for item in BrokerControlOperation)
_STATES = ", ".join(f"'{item.value}'" for item in BrokerControlState)


class CentralNodeBrokerCommand(Base):
    __tablename__ = "central_node_broker_commands"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_central_node_broker_commands_organization_deduplication",
        ),
        CheckConstraint(
            f"operation IN ({_OPERATIONS})",
            name="ck_central_node_broker_commands_operation",
        ),
        CheckConstraint(
            f"state IN ({_STATES})",
            name="ck_central_node_broker_commands_state",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_central_node_broker_commands_attempts",
        ),
        CheckConstraint(
            "(secret_ciphertext IS NULL AND secret_nonce IS NULL "
            "AND secret_key_id IS NULL) OR "
            "(secret_ciphertext IS NOT NULL AND secret_nonce IS NOT NULL "
            "AND secret_key_id IS NOT NULL)",
            name="ck_central_node_broker_commands_secret_envelope",
        ),
        CheckConstraint(
            "(operation IN ('provision', 'rotate') "
            "AND secret_ciphertext IS NOT NULL) OR "
            "(operation IN ('disable', 'delete') "
            "AND secret_ciphertext IS NULL)",
            name="ck_central_node_broker_commands_operation_secret",
        ),
        Index(
            "ix_central_node_broker_commands_ready",
            "state",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_central_node_broker_commands_node_history",
            "organization_id",
            "node_record_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_central_node_broker_commands_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    node_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "central_nodes.id",
            name="fk_central_node_broker_commands_node",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    credential_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "central_node_credentials.id",
            name="fk_central_node_broker_commands_credential",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=BrokerControlState.PENDING.value,
        server_default=BrokerControlState.PENDING.value,
    )
    deduplication_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_nonce: Mapped[str | None] = mapped_column(String(32), nullable=True)
    secret_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
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
