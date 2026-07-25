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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.alerts.domain import AlertCondition, AlertState
from app.db import Base


_CONDITIONS = ", ".join(f"'{item.value}'" for item in AlertCondition)
_STATES = ", ".join(f"'{item.value}'" for item in AlertState)
_SEVERITIES = "'information', 'warning', 'alarm', 'critical', 'system'"


class AlertRuleModel(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(
            f"condition IN ({_CONDITIONS})",
            name="ck_alert_rules_condition_known",
        ),
        CheckConstraint(
            f"severity IN ({_SEVERITIES})",
            name="ck_alert_rules_severity_known",
        ),
        CheckConstraint(
            "minimum_duration_seconds >= 0",
            name="ck_alert_rules_duration_non_negative",
        ),
        CheckConstraint(
            "cooldown_seconds >= 0",
            name="ck_alert_rules_cooldown_non_negative",
        ),
        CheckConstraint(
            "(condition = 'quality' AND target_quality IS NOT NULL "
            "AND trigger_threshold IS NULL AND clear_threshold IS NULL) "
            "OR (condition IN ('high', 'low') AND target_quality IS NULL "
            "AND trigger_threshold IS NOT NULL AND clear_threshold IS NOT NULL)",
            name="ck_alert_rules_condition_parameters",
        ),
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_alert_rules_organization_name",
        ),
        Index(
            "ix_alert_rules_series_enabled",
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            "enabled",
        ),
        Index("ix_alert_rules_organization", "organization_id", "enabled"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    clear_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    minimum_duration_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AlertRuleRuntimeModel(Base):
    __tablename__ = "alert_rule_runtime"

    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rules.id",
            name="fk_alert_rule_runtime_rule",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    pending_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pending_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"state IN ({_STATES})", name="ck_alerts_state_known"),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= triggered_at",
            name="ck_alerts_resolution_order",
        ),
        CheckConstraint(
            "closed_at IS NULL OR (resolved_at IS NOT NULL AND closed_at >= resolved_at)",
            name="ck_alerts_close_order",
        ),
        Index(
            "ix_alerts_organization_state_triggered",
            "organization_id",
            "state",
            "triggered_at",
        ),
        Index("ix_alerts_rule_triggered", "rule_id", "triggered_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_alerts_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("alert_rules.id", name="fk_alerts_rule", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    last_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trigger_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acknowledgement_reason: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AlertEventModel(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint(
            "alert_id",
            "event_type",
            "telemetry_event_id",
            name="uq_alert_events_alert_type_telemetry",
        ),
        Index("ix_alert_events_alert_occurred", "alert_id", "occurred_at"),
        Index(
            "ix_alert_events_organization_occurred",
            "organization_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_alert_events_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    alert_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("alerts.id", name="fk_alert_events_alert", ondelete="RESTRICT"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "alert_rules.id",
            name="fk_alert_events_rule",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    telemetry_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
