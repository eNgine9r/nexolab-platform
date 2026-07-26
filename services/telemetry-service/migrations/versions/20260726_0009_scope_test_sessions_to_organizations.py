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
    op.add_column(
        "test_sessions",
        sa.Column(
            "create_idempotency_key",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE test_sessions SET organization_id = :organization_id "
            "WHERE organization_id IS NULL"
        ).bindparams(organization_id=DEFAULT_ORGANIZATION_ID)
    )
    op.execute(
        """
        UPDATE test_sessions
        SET create_idempotency_key = COALESCE(
            (
                SELECT session_events.idempotency_key
                FROM session_events
                WHERE session_events.session_id = test_sessions.id
                  AND session_events.event_type = 'session_created'
                ORDER BY session_events.inserted_at, session_events.id
                LIMIT 1
            ),
            'legacy:' || test_sessions.id
        )
        WHERE create_idempotency_key IS NULL
        """
    )
    op.alter_column(
        "test_sessions",
        "organization_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "test_sessions",
        "create_idempotency_key",
        existing_type=sa.String(length=128),
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
    op.drop_index(
        "uq_session_created_idempotency_key",
        table_name="session_events",
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
    op.create_unique_constraint(
        "uq_test_sessions_organization_create_key",
        "test_sessions",
        ["organization_id", "create_idempotency_key"],
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
        "uq_test_sessions_organization_create_key",
        "test_sessions",
        type_="unique",
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
    op.create_index(
        "uq_session_created_idempotency_key",
        "session_events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("event_type = 'session_created'"),
        sqlite_where=sa.text("event_type = 'session_created'"),
    )
    op.drop_constraint(
        "fk_test_sessions_organization",
        "test_sessions",
        type_="foreignkey",
    )
    op.drop_column("test_sessions", "create_idempotency_key")
    op.drop_column("test_sessions", "organization_id")
