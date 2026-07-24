from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


SESSION_STATES = (
    "draft",
    "ready",
    "running",
    "paused",
    "completed",
    "cancelled",
    "archived",
)
SESSION_STAGE_TYPES = (
    "preparation",
    "preconditioning",
    "stabilization",
    "main_test",
    "defrost",
    "recovery",
    "completion",
    "report",
)

_SESSION_STATE_SQL = ", ".join(f"'{state}'" for state in SESSION_STATES)
_SESSION_STAGE_TYPE_SQL = ", ".join(
    f"'{stage_type}'" for stage_type in SESSION_STAGE_TYPES
)


class TestSession(Base):
    __tablename__ = "test_sessions"
    __table_args__ = (
        CheckConstraint(
            f"state IN ({_SESSION_STATE_SQL})",
            name="ck_test_sessions_state",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_test_sessions_lock_version_positive",
        ),
        Index("ix_test_sessions_state_created", "state", "created_at"),
        Index("ix_test_sessions_node_state", "node_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_number: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    customer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    test_object: Mapped[str] = mapped_column(String(256), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    standard: Mapped[str | None] = mapped_column(String(256), nullable=True)
    method: Mapped[str | None] = mapped_column(String(256), nullable=True)
    operator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    responsible_engineer_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    current_stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_test_sessions_current_stage_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    active_config_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    active_limit_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionChannelBinding(Base):
    __tablename__ = "session_channel_bindings"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            name="uq_session_channel_binding_identity",
        ),
        CheckConstraint(
            "released_at IS NULL OR "
            "(activated_at IS NOT NULL AND released_at >= activated_at)",
            name="ck_session_channel_binding_release_order",
        ),
        Index(
            "uq_active_session_channel_lease",
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            unique=True,
            postgresql_where=text(
                "activated_at IS NOT NULL AND released_at IS NULL"
            ),
            sqlite_where=text(
                "activated_at IS NOT NULL AND released_at IS NULL"
            ),
        ),
        Index("ix_session_channel_bindings_session", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_channel_bindings_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    binding_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionConfigSnapshot(Base):
    __tablename__ = "session_config_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "version",
            name="uq_session_config_snapshot_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_session_config_snapshot_version_positive",
        ),
        Index("ix_session_config_snapshots_session", "session_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_config_snapshots_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionLimit(Base):
    __tablename__ = "session_limits"
    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_session_limits_version_positive",
        ),
        CheckConstraint(
            "lower_limit IS NULL OR upper_limit IS NULL "
            "OR lower_limit <= upper_limit",
            name="ck_session_limits_order",
        ),
        Index(
            "uq_session_binding_limit_version",
            "session_id",
            "binding_id",
            "metric",
            "version",
            unique=True,
            postgresql_where=text("binding_id IS NOT NULL"),
            sqlite_where=text("binding_id IS NOT NULL"),
        ),
        Index(
            "uq_session_metric_limit_version",
            "session_id",
            "metric",
            "version",
            unique=True,
            postgresql_where=text("binding_id IS NULL"),
            sqlite_where=text("binding_id IS NULL"),
        ),
        Index("ix_session_limits_session_version", "session_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_limits_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    binding_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_channel_bindings.id",
            name="fk_session_limits_binding_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    config_snapshot_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_config_snapshots.id",
            name="fk_session_limits_config_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    supersedes_limit_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_limits.id",
            name="fk_session_limits_supersedes_limit_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    lower_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    hysteresis: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionStage(Base):
    __tablename__ = "session_stages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence_index",
            name="uq_session_stage_sequence",
        ),
        CheckConstraint(
            "sequence_index >= 0",
            name="ck_session_stage_sequence_nonnegative",
        ),
        CheckConstraint(
            f"stage_type IN ({_SESSION_STAGE_TYPE_SQL})",
            name="ck_session_stage_type",
        ),
        CheckConstraint(
            "exited_at IS NULL OR "
            "(entered_at IS NOT NULL AND exited_at >= entered_at)",
            name="ck_session_stage_exit_order",
        ),
        Index("ix_session_stages_session_sequence", "session_id", "sequence_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_stages_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_session_event_idempotency_key",
        ),
        Index("ix_session_events_session_occurred", "session_id", "occurred_at"),
        Index("ix_session_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_events_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_source: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionStageTransition(Base):
    __tablename__ = "session_stage_transitions"
    __table_args__ = (
        CheckConstraint(
            "from_sequence_index IS NULL OR from_sequence_index >= 0",
            name="ck_stage_transition_from_sequence_nonnegative",
        ),
        CheckConstraint(
            "to_sequence_index >= 0",
            name="ck_stage_transition_to_sequence_nonnegative",
        ),
        Index(
            "ix_session_stage_transitions_session_occurred",
            "session_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_stage_transitions_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_events.id",
            name="fk_session_stage_transitions_event_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    )
    from_stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_session_stage_transitions_from_stage_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    to_stage_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_session_stage_transitions_to_stage_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    from_sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SessionNote(Base):
    __tablename__ = "session_notes"
    __table_args__ = (
        Index("ix_session_notes_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_session_notes_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_session_notes_stage_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    author_id: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_session_occurred", "session_id", "occurred_at"),
        Index("ix_audit_log_entity_occurred", "entity_type", "entity_id", "occurred_at"),
        Index(
            "uq_audit_log_session_event",
            "session_event_id",
            unique=True,
            postgresql_where=text("session_event_id IS NOT NULL"),
            sqlite_where=text("session_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_audit_log_session_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    session_event_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_events.id",
            name="fk_audit_log_session_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_source: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
