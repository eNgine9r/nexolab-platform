"""add central node registry and provisioning credentials

Revision ID: 20260726_0014
Revises: 20260726_0013
Create Date: 2026-07-26 22:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0014"
down_revision = "20260726_0013"
branch_labels = None
depends_on = None

NODE_STATES = "'pending', 'active', 'suspended', 'revoked'"
CLOCK_STATUSES = "'unknown', 'ok', 'warning', 'critical'"


def upgrade() -> None:
    op.create_table(
        "central_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("state_reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "clock_warning_ms",
            sa.Integer(),
            server_default=sa.text("30000"),
            nullable=False,
        ),
        sa.Column(
            "clock_critical_ms",
            sa.Integer(),
            server_default=sa.text("120000"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_clock_offset_ms", sa.Integer(), nullable=True),
        sa.Column(
            "clock_status",
            sa.String(length=16),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("clock_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"state IN ({NODE_STATES})",
            name="ck_central_nodes_state",
        ),
        sa.CheckConstraint(
            f"clock_status IN ({CLOCK_STATUSES})",
            name="ck_central_nodes_clock_status",
        ),
        sa.CheckConstraint(
            "clock_warning_ms > 0 AND clock_critical_ms > clock_warning_ms",
            name="ck_central_nodes_clock_thresholds",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_nodes_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "node_id",
            name="uq_central_nodes_organization_node",
        ),
    )
    op.create_index(
        "ix_central_nodes_organization_state",
        "central_nodes",
        ["organization_id", "state", "node_id"],
    )

    op.create_table(
        "central_node_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("secret_salt", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("secret_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("issued_by", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=255), nullable=True),
        sa.Column("revocation_reason", sa.String(length=1024), nullable=True),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_central_node_credentials_generation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_credentials_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_credentials_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_central_node_credentials_organization_idempotency",
        ),
        sa.UniqueConstraint(
            "node_record_id",
            "generation",
            name="uq_central_node_credentials_node_generation",
        ),
    )
    op.create_index(
        "ix_central_node_credentials_active_lookup",
        "central_node_credentials",
        ["organization_id", "node_record_id", "revoked_at"],
    )

    op.create_table(
        "central_node_ingress_cursors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_event_id", sa.String(length=36), nullable=False),
        sa.Column("last_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 1",
            name="ck_central_node_ingress_cursors_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_ingress_cursors_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_ingress_cursors_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "node_record_id",
            "stream",
            name="uq_central_node_ingress_cursors_node_stream",
        ),
    )
    op.create_index(
        "ix_central_node_ingress_cursors_organization_node",
        "central_node_ingress_cursors",
        ["organization_id", "node_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_central_node_ingress_cursors_organization_node",
        table_name="central_node_ingress_cursors",
    )
    op.drop_table("central_node_ingress_cursors")
    op.drop_index(
        "ix_central_node_credentials_active_lookup",
        table_name="central_node_credentials",
    )
    op.drop_table("central_node_credentials")
    op.drop_index(
        "ix_central_nodes_organization_state",
        table_name="central_nodes",
    )
    op.drop_table("central_nodes")
