"""add durable alert rules and lifecycle

Revision ID: 20260725_0009
Revises: 20260725_0008
Create Date: 2026-07-25 19:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260725_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("condition", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("trigger_threshold", sa.Float(), nullable=True),
        sa.Column("clear_threshold", sa.Float(), nullable=True),
        sa.Column("target_quality", sa.String(length=32), nullable=True),
        sa.Column("minimum_duration_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "condition IN ('high', 'low', 'quality')",
            name="ck_alert_rules_condition_known",
        ),
        sa.CheckConstraint(
            "severity IN ('information', 'warning', 'alarm', 'critical', 'system')",
            name="ck_alert_rules_severity_known",
        ),
        sa.CheckConstraint(
            "minimum_duration_seconds >= 0",
            name="ck_alert_rules_duration_non_negative",
        ),
        sa.CheckConstraint(
            "cooldown_seconds >= 0",
            name="ck_alert_rules_cooldown_non_negative",
        ),
        sa.CheckConstraint(
            "(condition = 'quality' AND target_quality IS NOT NULL "
            "AND trigger_threshold IS NULL AND clear_threshold IS NULL) "
            "OR (condition IN ('high', 'low') AND target_quality IS NULL "
            "AND trigger_threshold IS NOT NULL AND clear_threshold IS NOT NULL)",
            name="ck_alert_rules_condition_parameters",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alert_rules_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            name="uq_alert_rules_organization_name",
        ),
    )
    op.create_index(
        "ix_alert_rules_series_enabled",
        "alert_rules",
        ["node_id", "equipment_id", "channel_id", "metric", "enabled"],
    )
    op.create_index(
        "ix_alert_rules_organization",
        "alert_rules",
        ["organization_id", "enabled"],
    )

    op.create_table(
        "alert_rule_runtime",
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_event_id", sa.String(length=36), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.String(length=36), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alert_rule_runtime_rule",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rule_id"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_event_id", sa.String(length=36), nullable=False),
        sa.Column("last_event_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True),
        sa.Column("peak_value", sa.Float(), nullable=True),
        sa.Column("current_quality", sa.String(length=32), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("acknowledgement_reason", sa.String(length=1024), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(length=255), nullable=True),
        sa.Column("close_reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('active', 'acknowledged', 'resolved', 'closed')",
            name="ck_alerts_state_known",
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= triggered_at",
            name="ck_alerts_resolution_order",
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR (resolved_at IS NOT NULL AND closed_at >= resolved_at)",
            name="ck_alerts_close_order",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alerts_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alerts_rule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alerts_organization_state_triggered",
        "alerts",
        ["organization_id", "state", "triggered_at"],
    )
    op.create_index(
        "ix_alerts_rule_triggered",
        "alerts",
        ["rule_id", "triggered_at"],
    )
    op.create_index(
        "uq_alerts_rule_open",
        "alerts",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('active', 'acknowledged')"),
        sqlite_where=sa.text("state IN ('active', 'acknowledged')"),
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("telemetry_event_id", sa.String(length=36), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alert_events_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name="fk_alert_events_alert",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alert_events_rule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alert_id",
            "event_type",
            "telemetry_event_id",
            name="uq_alert_events_alert_type_telemetry",
        ),
    )
    op.create_index(
        "ix_alert_events_alert_occurred",
        "alert_events",
        ["alert_id", "occurred_at"],
    )
    op.create_index(
        "ix_alert_events_organization_occurred",
        "alert_events",
        ["organization_id", "occurred_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_alert_event_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'alert events are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_alert_events_immutable
            BEFORE UPDATE OR DELETE ON alert_events
            FOR EACH ROW EXECUTE FUNCTION reject_alert_event_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_alert_events_immutable ON alert_events")
        op.execute("DROP FUNCTION IF EXISTS reject_alert_event_mutation()")

    op.drop_index("ix_alert_events_organization_occurred", table_name="alert_events")
    op.drop_index("ix_alert_events_alert_occurred", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_index("uq_alerts_rule_open", table_name="alerts")
    op.drop_index("ix_alerts_rule_triggered", table_name="alerts")
    op.drop_index("ix_alerts_organization_state_triggered", table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("alert_rule_runtime")
    op.drop_index("ix_alert_rules_organization", table_name="alert_rules")
    op.drop_index("ix_alert_rules_series_enabled", table_name="alert_rules")
    op.drop_table("alert_rules")
