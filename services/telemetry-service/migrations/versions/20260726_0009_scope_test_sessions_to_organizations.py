"""scope laboratory sessions to organizations

Revision ID: 20260726_0009
Revises: 20260725_0008
Create Date: 2026-07-26 11:55:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.add_column(
        "test_sessions",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE test_sessions SET organization_id = :organization_id "
            "WHERE organization_id IS NULL"
        ).bindparams(organization_id=DEFAULT_ORGANIZATION_ID)
    )
    op.alter_column(
        "test_sessions",
        "organization_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_test_sessions_organization",
        "test_sessions",
        "security_organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        ["organization_id", "session_number"],
    )
    op.create_index(
        "ix_test_sessions_organization_state_created",
        "test_sessions",
        ["organization_id", "state", "created_at"],
    )
    op.create_index(
        "ix_test_sessions_organization_node_state",
        "test_sessions",
        ["organization_id", "node_id", "state"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_test_sessions_organization_node_state",
        table_name="test_sessions",
    )
    op.drop_index(
        "ix_test_sessions_organization_state_created",
        table_name="test_sessions",
    )
    op.drop_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        ["session_number"],
    )
    op.drop_constraint(
        "fk_test_sessions_organization",
        "test_sessions",
        type_="foreignkey",
    )
    op.drop_column("test_sessions", "organization_id")
