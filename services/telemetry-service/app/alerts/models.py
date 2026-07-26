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

from app.alerts.domain import AlertCondition, AlertSeverity, AlertState
from app.db import Base


_SEVERITY_SQL = ", ".join(f"'{item.value}'" for item in AlertSeverity)
_STATE_SQL = ", ".join(f"'{item.value}'" for item in AlertState)
_CONDITION_SQL = ", ".join(f"'{item.value}'" for item in AlertCondition)
_OPEN_STATES_SQL = "'active', 'acknowledged', 'resolved'"


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_alert_rules_organization_name",
        ),
        CheckConstraint(
            f"severity IN ({_SEVERITY_SQL})",
            name="ck_alert_rules_severity",
        ),
        CheckConstraint(
            "current_version >= 1",
            name="ck_alert_rules_current_version_positive",
        ),
        Index(
            "ix_alert_rules_organization_enabled",
            "organization_id",
            "enabled",
            "metric",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_alert_rules_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    equipment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_alert_rules_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    current_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertRuleVersion(Base):
    __tablename__ = "alert_rule_versions"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "version",
            name="uq_alert_rule_versions_rule_version",
        ),
        CheckConstraint(
            f"condition IN ({_CONDITION_SQL})",
            name="ck_alert_rule_versions_condition",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_alert_rule_versions_version_positive",
        ),
        CheckConstraint(
            "minimum_duration_seconds >= 0 AND clear_duration_seconds >= 0 "
            "AND debounce_seconds >= 0 AND cooldown_seconds >= 0",
            name="ck_alert_rule_versions_durations_nonnegative",
        ),
        Index("ix_alert_rule_versions_rule", "rule_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rules.id",
            name="fk_alert_rule_versions_rule",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    clear_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    clear_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    debounce_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertInstance(Base):
    __tablename__ = "alert_instances"
    __table_args__ = (
        CheckConstraint(
            f"state IN ({_STATE_SQL})",
            name="ck_alert_instances_state",
        ),
        CheckConstraint(
            f"severity IN ({_SEVERITY_SQL})",
            name="ck_alert_instances_severity",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_alert_instances_lock_version_positive",
        ),
        Index(
            "uq_alert_instances_open_identity",
            "rule_id",
            "resource_key",
            unique=True,
            postgresql_where=text(f"state IN ({_OPEN_STATES_SQL})"),
            sqlite_where=text(f"state IN ({_OPEN_STATES_SQL})"),
        ),
        Index(
            "ix_alert_instances_organization_state_triggered",
            "organization_id",
            "state",
            "triggered_at",
        ),
        Index(
            "ix_alert_instances_resource",
            "organization_id",
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_alert_instances_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rules.id",
            name="fk_alert_instances_rule",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    rule_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rule_versions.id",
            name="fk_alert_instances_rule_version",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    resource_key: Mapped[str] = mapped_column(String(512), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    clear_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_deviation: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    first_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    last_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_alert_instances_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_alert_instances_stage",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    binding_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_channel_bindings.id",
            name="fk_alert_instances_binding",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertTransition(Base):
    __tablename__ = "alert_transitions"
    __table_args__ = (
        UniqueConstraint(
            "alert_id",
            "idempotency_key",
            name="uq_alert_transitions_alert_idempotency",
        ),
        CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({_STATE_SQL})",
            name="ck_alert_transitions_previous_state",
        ),
        CheckConstraint(
            f"next_state IN ({_STATE_SQL})",
            name="ck_alert_transitions_next_state",
        ),
        Index("ix_alert_transitions_alert_occurred", "alert_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_instances.id",
            name="fk_alert_transitions_alert",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_source: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertEvidenceSample(Base):
    __tablename__ = "alert_evidence_samples"
    __table_args__ = (
        UniqueConstraint(
            "alert_id",
            "event_id",
            name="uq_alert_evidence_alert_event",
        ),
        Index("ix_alert_evidence_alert_captured", "alert_id", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_instances.id",
            name="fk_alert_evidence_alert",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AlertEvaluationState(Base):
    __tablename__ = "alert_evaluation_states"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "resource_key",
            name="uq_alert_evaluation_rule_resource",
        ),
        Index(
            "ix_alert_evaluation_organization_updated",
            "organization_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_alert_evaluation_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rules.id",
            name="fk_alert_evaluation_rule",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    resource_key: Mapped[str] = mapped_column(String(512), nullable=False)
    last_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_pending_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    clear_pending_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "alert_instances.id",
            name="fk_alert_evaluation_active_alert",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_deviation: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
