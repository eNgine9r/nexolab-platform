"""add organization-scoped production alerts

Revision ID: 20260726_0010
Revises: 20260726_0009
Create Date: 2026-07-26 14:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0010"
down_revision = "20260726_0009"
branch_labels = None
depends_on = None


ALERT_SEVERITIES = "'information', 'warning', 'alarm', 'critical', 'system'"
ALERT_STATES = "'active', 'acknowledged', 'resolved', 'closed'"
ALERT_CONDITIONS = "'threshold_high', 'threshold_low'"
OPEN_ALERT_STATES = "'active', 'acknowledged', 'resolved'"


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=True),
        sa.Column("equipment_id", sa.String(length=128), nullable=True),
        sa.Column("channel_id", sa.String(length=128), nullable=True),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"severity IN ({ALERT_SEVERITIES})",
            name="ck_alert_rules_severity",
        ),
        sa.CheckConstraint(
            "current_version >= 1",
            name="ck_alert_rules_current_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alert_rules_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_alert_rules_session",
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
        "ix_alert_rules_organization_enabled",
        "alert_rules",
        ["organization_id", "enabled", "metric"],
    )

    op.create_table(
        "alert_rule_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=32), nullable=False),
        sa.Column("trigger_threshold", sa.Float(), nullable=False),
        sa.Column("clear_threshold", sa.Float(), nullable=False),
        sa.Column("minimum_duration_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("clear_duration_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("debounce_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("configuration", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"condition IN ({ALERT_CONDITIONS})",
            name="ck_alert_rule_versions_condition",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_alert_rule_versions_version_positive",
        ),
        sa.CheckConstraint(
            "minimum_duration_seconds >= 0 AND clear_duration_seconds >= 0 "
            "AND debounce_seconds >= 0 AND cooldown_seconds >= 0",
            name="ck_alert_rule_versions_durations_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alert_rule_versions_rule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id",
            "version",
            name="uq_alert_rule_versions_rule_version",
        ),
    )
    op.create_index(
        "ix_alert_rule_versions_rule",
        "alert_rule_versions",
        ["rule_id", "version"],
    )

    op.create_table(
        "alert_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("rule_version_id", sa.String(length=36), nullable=False),
        sa.Column("resource_key", sa.String(length=512), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("trigger_value", sa.Float(), nullable=True),
        sa.Column("trigger_threshold", sa.Float(), nullable=True),
        sa.Column("clear_threshold", sa.Float(), nullable=True),
        sa.Column("maximum_deviation", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("first_event_id", sa.String(length=36), nullable=False),
        sa.Column("last_event_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("stage_id", sa.String(length=36), nullable=True),
        sa.Column("binding_id", sa.String(length=36), nullable=True),
        sa.Column("context", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"state IN ({ALERT_STATES})",
            name="ck_alert_instances_state",
        ),
        sa.CheckConstraint(
            f"severity IN ({ALERT_SEVERITIES})",
            name="ck_alert_instances_severity",
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_alert_instances_lock_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alert_instances_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alert_instances_rule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["alert_rule_versions.id"],
            name="fk_alert_instances_rule_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_alert_instances_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["session_stages.id"],
            name="fk_alert_instances_stage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["session_channel_bindings.id"],
            name="fk_alert_instances_binding",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_alert_instances_open_identity",
        "alert_instances",
        ["rule_id", "resource_key"],
        unique=True,
        postgresql_where=sa.text(f"state IN ({OPEN_ALERT_STATES})"),
        sqlite_where=sa.text(f"state IN ({OPEN_ALERT_STATES})"),
    )
    op.create_index(
        "ix_alert_instances_organization_state_triggered",
        "alert_instances",
        ["organization_id", "state", "triggered_at"],
    )
    op.create_index(
        "ix_alert_instances_resource",
        "alert_instances",
        ["organization_id", "node_id", "equipment_id", "channel_id", "metric"],
    )

    op.create_table(
        "alert_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_state", sa.String(length=32), nullable=True),
        sa.Column("next_state", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_source", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"previous_state IS NULL OR previous_state IN ({ALERT_STATES})",
            name="ck_alert_transitions_previous_state",
        ),
        sa.CheckConstraint(
            f"next_state IN ({ALERT_STATES})",
            name="ck_alert_transitions_next_state",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alert_instances.id"],
            name="fk_alert_transitions_alert",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alert_id",
            "idempotency_key",
            name="uq_alert_transitions_alert_idempotency",
        ),
    )
    op.create_index(
        "ix_alert_transitions_alert_occurred",
        "alert_transitions",
        ["alert_id", "occurred_at"],
    )

    op.create_table(
        "alert_evidence_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("deviation", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alert_instances.id"],
            name="fk_alert_evidence_alert",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alert_id",
            "event_id",
            name="uq_alert_evidence_alert_event",
        ),
    )
    op.create_index(
        "ix_alert_evidence_alert_captured",
        "alert_evidence_samples",
        ["alert_id", "captured_at"],
    )

    op.create_table(
        "alert_evaluation_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("resource_key", sa.String(length=512), nullable=False),
        sa.Column("last_event_id", sa.String(length=36), nullable=True),
        sa.Column("last_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clear_pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_alert_id", sa.String(length=36), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("maximum_deviation", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_alert_evaluation_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["alert_rules.id"],
            name="fk_alert_evaluation_rule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["active_alert_id"],
            ["alert_instances.id"],
            name="fk_alert_evaluation_active_alert",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id",
            "resource_key",
            name="uq_alert_evaluation_rule_resource",
        ),
    )
    op.create_index(
        "ix_alert_evaluation_organization_updated",
        "alert_evaluation_states",
        ["organization_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alert_evaluation_organization_updated",
        table_name="alert_evaluation_states",
    )
    op.drop_table("alert_evaluation_states")
    op.drop_index(
        "ix_alert_evidence_alert_captured",
        table_name="alert_evidence_samples",
    )
    op.drop_table("alert_evidence_samples")
    op.drop_index(
        "ix_alert_transitions_alert_occurred",
        table_name="alert_transitions",
    )
    op.drop_table("alert_transitions")
    op.drop_index("ix_alert_instances_resource", table_name="alert_instances")
    op.drop_index(
        "ix_alert_instances_organization_state_triggered",
        table_name="alert_instances",
    )
    op.drop_index(
        "uq_alert_instances_open_identity",
        table_name="alert_instances",
    )
    op.drop_table("alert_instances")
    op.drop_index(
        "ix_alert_rule_versions_rule",
        table_name="alert_rule_versions",
    )
    op.drop_table("alert_rule_versions")
    op.drop_index(
        "ix_alert_rules_organization_enabled",
        table_name="alert_rules",
    )
    op.drop_table("alert_rules")
