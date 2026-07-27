from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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


BROKER_COMMAND_TYPES = ("upsert_credential", "disable_client", "enable_client")
BROKER_COMMAND_STATES = ("pending", "retrying", "applied", "failed")
_COMMAND_TYPES_SQL = ", ".join(f"'{value}'" for value in BROKER_COMMAND_TYPES)
_COMMAND_STATES_SQL = ", ".join(f"'{value}'" for value in BROKER_COMMAND_STATES)


class CentralNodeBrokerCommand(Base):
    __tablename__ = "central_node_broker_commands"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "command_key",
            name="uq_central_node_broker_commands_organization_key",
        ),
        CheckConstraint(
            f"command_type IN ({_COMMAND_TYPES_SQL})",
            name="ck_central_node_broker_commands_type",
        ),
        CheckConstraint(
            f"state IN ({_COMMAND_STATES_SQL})",
            name="ck_central_node_broker_commands_state",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_central_node_broker_commands_attempts",
        ),
        CheckConstraint(
            "(command_type = 'upsert_credential' AND credential_id IS NOT NULL "
            "AND secret_ciphertext IS NOT NULL AND secret_nonce IS NOT NULL "
            "AND encryption_key_id IS NOT NULL AND credential_generation IS NOT NULL) "
            "OR (command_type <> 'upsert_credential' AND credential_id IS NULL "
            "AND secret_ciphertext IS NULL AND secret_nonce IS NULL "
            "AND encryption_key_id IS NULL AND credential_generation IS NULL)",
            name="ck_central_node_broker_commands_secret_shape",
        ),
        Index(
            "ix_central_node_broker_commands_dispatch",
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
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    command_key: Mapped[str] = mapped_column(String(160), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desired_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=8,
        server_default=text("8"),
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
