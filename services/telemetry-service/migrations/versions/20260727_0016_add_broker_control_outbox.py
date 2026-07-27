"""add encrypted broker control outbox

Revision ID: 20260727_0016
Revises: 20260727_0015
Create Date: 2026-07-27 13:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260727_0016"
down_revision = "20260727_0015"
branch_labels = None
depends_on = None


OPERATIONS = "'provision', 'rotate', 'enable', 'disable', 'delete'"
STATES = "'pending', 'processing', 'retrying', 'applied', 'failed'"


def upgrade() -> None:
    op.create_table(
        "central_node_broker_commands",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("credential_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("deduplication_key", sa.String(length=128), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_nonce", sa.String(length=32), nullable=True),
        sa.Column("secret_key_id", sa.String(length=64), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
            f"operation IN ({OPERATIONS})",
            name="ck_central_node_broker_commands_operation",
        ),
        sa.CheckConstraint(
            f"state IN ({STATES})",
            name="ck_central_node_broker_commands_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_central_node_broker_commands_attempts",
        ),
        sa.CheckConstraint(
            "(secret_ciphertext IS NULL AND secret_nonce IS NULL "
            "AND secret_key_id IS NULL) OR "
            "(secret_ciphertext IS NOT NULL AND secret_nonce IS NOT NULL "
            "AND secret_key_id IS NOT NULL)",
            name="ck_central_node_broker_commands_secret_envelope",
        ),
        sa.CheckConstraint(
            "(operation IN ('provision', 'rotate') "
            "AND secret_ciphertext IS NOT NULL) OR "
            "(operation IN ('enable', 'disable', 'delete') "
            "AND secret_ciphertext IS NULL)",
            name="ck_central_node_broker_commands_operation_secret",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_broker_commands_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_broker_commands_node",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["central_node_credentials.id"],
            name="fk_central_node_broker_commands_credential",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_central_node_broker_commands_organization_deduplication",
        ),
    )
    op.create_index(
        "ix_central_node_broker_commands_ready",
        "central_node_broker_commands",
        ["state", "available_at", "created_at"],
    )
    op.create_index(
        "ix_central_node_broker_commands_node_history",
        "central_node_broker_commands",
        ["organization_id", "node_record_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_central_node_broker_commands_node_history",
        table_name="central_node_broker_commands",
    )
    op.drop_index(
        "ix_central_node_broker_commands_ready",
        table_name="central_node_broker_commands",
    )
    op.drop_table("central_node_broker_commands")
