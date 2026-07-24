"""add laboratory test sessions

Revision ID: 20260724_0004
Revises: 20260723_0003
Create Date: 2026-07-24 11:15:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260724_0004"
down_revision = "20260723_0003"
branch_labels = None
depends_on = None

SESSION_STATE_CHECK = (
    "state IN ('draft', 'ready', 'running', 'paused', "
    "'completed', 'cancelled', 'archived')"
)
SESSION_STAGE_TYPE_CHECK = (
    "stage_type IN ('preparation', 'preconditioning', 'stabilization', "
    "'main_test', 'defrost', 'recovery', 'completion', 'report')"
)


def upgrade() -> None:
    op.create_table(
        "test_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_number", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("customer", sa.String(length=256), nullable=True),
        sa.Column("test_object", sa.String(length=256), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column("standard", sa.String(length=256), nullable=True),
        sa.Column("method", sa.String(length=256), nullable=True),
        sa.Column("operator_id", sa.String(length=128), nullable=True),
        sa.Column(
            "responsible_engineer_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "metadata_payload",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("current_stage_id", sa.String(length=36), nullable=True),
        sa.Column(
            "active_config_snapshot_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column("active_limit_version", sa.Integer(), nullable=True),
        sa.Column(
            "lock_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            SESSION_STATE_CHECK,
            name="ck_test_sessions_state",
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_test_sessions_lock_version_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_number",
            name="uq_test_sessions_session_number",
        ),
    )
    op.create_index(
        "ix_test_sessions_state_created",
        "test_sessions",
        ["state", "created_at"],
    )
    op.create_index(
        "ix_test_sessions_node_state",
        "test_sessions",
        ["node_id", "state"],
    )

    op.create_table(
        "session_channel_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column(
            "binding_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "released_at IS NULL OR "
            "(activated_at IS NOT NULL AND released_at >= activated_at)",
            name="ck_session_channel_binding_release_order",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_channel_bindings_session_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            name="uq_session_channel_binding_identity",
        ),
    )
    op.create_index(
        "ix_session_channel_bindings_session",
        "session_channel_bindings",
        ["session_id"],
    )
    op.create_index(
        "uq_active_session_channel_lease",
        "session_channel_bindings",
        ["node_id", "equipment_id", "channel_id", "metric"],
        unique=True,
        postgresql_where=sa.text(
            "activated_at IS NOT NULL AND released_at IS NULL"
        ),
    )

    op.create_table(
        "session_config_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_session_config_snapshot_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_config_snapshots_session_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "version",
            name="uq_session_config_snapshot_version",
        ),
    )
    op.create_index(
        "ix_session_config_snapshots_session",
        "session_config_snapshots",
        ["session_id", "version"],
    )

    op.create_table(
        "session_limits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=True),
        sa.Column("config_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_limit_id", sa.String(length=36), nullable=True),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lower_limit", sa.Float(), nullable=True),
        sa.Column("upper_limit", sa.Float(), nullable=True),
        sa.Column("hysteresis", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "payload",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_session_limits_version_positive",
        ),
        sa.CheckConstraint(
            "lower_limit IS NULL OR upper_limit IS NULL "
            "OR lower_limit <= upper_limit",
            name="ck_session_limits_order",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["session_channel_bindings.id"],
            name="fk_session_limits_binding_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"],
            ["session_config_snapshots.id"],
            name="fk_session_limits_config_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_limits_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_limit_id"],
            ["session_limits.id"],
            name="fk_session_limits_supersedes_limit_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_limits_session_version",
        "session_limits",
        ["session_id", "version"],
    )
    op.create_index(
        "uq_session_binding_limit_version",
        "session_limits",
        ["session_id", "binding_id", "metric", "version"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NOT NULL"),
    )
    op.create_index(
        "uq_session_metric_limit_version",
        "session_limits",
        ["session_id", "metric", "version"],
        unique=True,
        postgresql_where=sa.text("binding_id IS NULL"),
    )

    op.create_table(
        "session_stages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("stage_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("planned_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_index >= 0",
            name="ck_session_stage_sequence_nonnegative",
        ),
        sa.CheckConstraint(
            SESSION_STAGE_TYPE_CHECK,
            name="ck_session_stage_type",
        ),
        sa.CheckConstraint(
            "exited_at IS NULL OR "
            "(entered_at IS NOT NULL AND exited_at >= entered_at)",
            name="ck_session_stage_exit_order",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_stages_session_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "sequence_index",
            name="uq_session_stage_sequence",
        ),
    )
    op.create_index(
        "ix_session_stages_session_sequence",
        "session_stages",
        ["session_id", "sequence_index"],
    )
    op.create_foreign_key(
        "fk_test_sessions_current_stage_id",
        "test_sessions",
        "session_stages",
        ["current_stage_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_test_sessions_active_config_snapshot_id",
        "test_sessions",
        "session_config_snapshots",
        ["active_config_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_state", sa.String(length=32), nullable=True),
        sa.Column("next_state", sa.String(length=32), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_source", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_events_session_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_session_event_idempotency_key",
        ),
    )
    op.create_index(
        "ix_session_events_session_occurred",
        "session_events",
        ["session_id", "occurred_at"],
    )
    op.create_index(
        "ix_session_events_type_occurred",
        "session_events",
        ["event_type", "occurred_at"],
    )

    op.create_table(
        "session_stage_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("session_event_id", sa.String(length=36), nullable=False),
        sa.Column("from_stage_id", sa.String(length=36), nullable=True),
        sa.Column("to_stage_id", sa.String(length=36), nullable=False),
        sa.Column("from_sequence_index", sa.Integer(), nullable=True),
        sa.Column("to_sequence_index", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_sequence_index IS NULL OR from_sequence_index >= 0",
            name="ck_stage_transition_from_sequence_nonnegative",
        ),
        sa.CheckConstraint(
            "to_sequence_index >= 0",
            name="ck_stage_transition_to_sequence_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["from_stage_id"],
            ["session_stages.id"],
            name="fk_session_stage_transitions_from_stage_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_event_id"],
            ["session_events.id"],
            name="fk_session_stage_transitions_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_stage_transitions_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_stage_id"],
            ["session_stages.id"],
            name="fk_session_stage_transitions_to_stage_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_event_id",
            name="uq_session_stage_transition_event_id",
        ),
    )
    op.create_index(
        "ix_session_stage_transitions_session_occurred",
        "session_stage_transitions",
        ["session_id", "occurred_at"],
    )

    op.create_table(
        "session_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("stage_id", sa.String(length=36), nullable=True),
        sa.Column("author_id", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_session_notes_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["session_stages.id"],
            name="fk_session_notes_stage_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_notes_session_created",
        "session_notes",
        ["session_id", "created_at"],
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("session_event_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_source", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_event_id"],
            ["session_events.id"],
            name="fk_audit_log_session_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_audit_log_session_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_log_session_occurred",
        "audit_log",
        ["session_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_log_entity_occurred",
        "audit_log",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index(
        "uq_audit_log_session_event",
        "audit_log",
        ["session_event_id"],
        unique=True,
        postgresql_where=sa.text("session_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_audit_log_session_event", table_name="audit_log")
    op.drop_index("ix_audit_log_entity_occurred", table_name="audit_log")
    op.drop_index("ix_audit_log_session_occurred", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_session_notes_session_created", table_name="session_notes")
    op.drop_table("session_notes")

    op.drop_index(
        "ix_session_stage_transitions_session_occurred",
        table_name="session_stage_transitions",
    )
    op.drop_table("session_stage_transitions")

    op.drop_index("ix_session_events_type_occurred", table_name="session_events")
    op.drop_index(
        "ix_session_events_session_occurred",
        table_name="session_events",
    )
    op.drop_table("session_events")

    op.drop_constraint(
        "fk_test_sessions_active_config_snapshot_id",
        "test_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_test_sessions_current_stage_id",
        "test_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_session_stages_session_sequence",
        table_name="session_stages",
    )
    op.drop_table("session_stages")

    op.drop_index(
        "uq_session_metric_limit_version",
        table_name="session_limits",
    )
    op.drop_index(
        "uq_session_binding_limit_version",
        table_name="session_limits",
    )
    op.drop_index(
        "ix_session_limits_session_version",
        table_name="session_limits",
    )
    op.drop_table("session_limits")

    op.drop_index(
        "ix_session_config_snapshots_session",
        table_name="session_config_snapshots",
    )
    op.drop_table("session_config_snapshots")

    op.drop_index(
        "uq_active_session_channel_lease",
        table_name="session_channel_bindings",
    )
    op.drop_index(
        "ix_session_channel_bindings_session",
        table_name="session_channel_bindings",
    )
    op.drop_table("session_channel_bindings")

    op.drop_index("ix_test_sessions_node_state", table_name="test_sessions")
    op.drop_index("ix_test_sessions_state_created", table_name="test_sessions")
    op.drop_table("test_sessions")
