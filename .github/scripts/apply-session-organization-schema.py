from pathlib import Path

root = Path(__file__).resolve().parents[2]
models = root / "services/telemetry-service/app/sessions/models.py"
text = models.read_text()
old = '''        Index("ix_test_sessions_state_created", "state", "created_at"),
        Index("ix_test_sessions_node_state", "node_id", "state"),
'''
new = '''        UniqueConstraint(
            "organization_id",
            "session_number",
            name="uq_test_sessions_organization_number",
        ),
        Index(
            "ix_test_sessions_organization_state_created",
            "organization_id",
            "state",
            "created_at",
        ),
        Index(
            "ix_test_sessions_organization_node_state",
            "organization_id",
            "node_id",
            "state",
        ),
'''
if old not in text:
    raise SystemExit("test session table args anchor not found")
text = text.replace(old, new, 1)
old = '''    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_number: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
'''
new = '''    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_test_sessions_organization_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_number: Mapped[str] = mapped_column(String(64), nullable=False)
'''
if old not in text:
    raise SystemExit("test session columns anchor not found")
models.write_text(text.replace(old, new, 1))

migration = root / "services/telemetry-service/migrations/versions/20260726_0009_scope_sessions_to_organizations.py"
migration.write_text('''"""scope test sessions to organizations

Revision ID: 20260726_0009
Revises: 20260725_0008
Create Date: 2026-07-26 09:00:00
"""
from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

revision = "20260726_0009"
down_revision = "20260725_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    default_organization_id = os.environ.get(
        "AUTH_DEFAULT_ORGANIZATION_ID",
        "00000000-0000-0000-0000-000000000001",
    )
    op.add_column(
        "test_sessions",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE test_sessions SET organization_id = :organization_id "
            "WHERE organization_id IS NULL"
        ).bindparams(organization_id=default_organization_id)
    )
    op.alter_column("test_sessions", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_test_sessions_organization_id",
        "test_sessions",
        "security_organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("test_sessions_session_number_key", "test_sessions", type_="unique")
    op.drop_index("ix_test_sessions_state_created", table_name="test_sessions")
    op.drop_index("ix_test_sessions_node_state", table_name="test_sessions")
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
    op.drop_index("ix_test_sessions_organization_node_state", table_name="test_sessions")
    op.drop_index("ix_test_sessions_organization_state_created", table_name="test_sessions")
    op.drop_constraint(
        "uq_test_sessions_organization_number", "test_sessions", type_="unique"
    )
    op.create_index(
        "ix_test_sessions_state_created", "test_sessions", ["state", "created_at"]
    )
    op.create_index(
        "ix_test_sessions_node_state", "test_sessions", ["node_id", "state"]
    )
    op.create_unique_constraint(
        "test_sessions_session_number_key", "test_sessions", ["session_number"]
    )
    op.drop_constraint(
        "fk_test_sessions_organization_id", "test_sessions", type_="foreignkey"
    )
    op.drop_column("test_sessions", "organization_id")
''')

test = root / "services/telemetry-service/tests/test_session_organization_schema.py"
test.write_text('''from sqlalchemy import inspect

from app.sessions.models import TestSession


def test_session_model_has_required_organization_scope() -> None:
    columns = {column.name: column for column in TestSession.__table__.columns}
    assert columns["organization_id"].nullable is False
    assert columns["organization_id"].foreign_keys

    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in TestSession.__table__.constraints
        if constraint.name
    }
    assert constraints["uq_test_sessions_organization_number"] == (
        "organization_id",
        "session_number",
    )

    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in TestSession.__table__.indexes
    }
    assert indexes["ix_test_sessions_organization_state_created"] == (
        "organization_id",
        "state",
        "created_at",
    )
    assert indexes["ix_test_sessions_organization_node_state"] == (
        "organization_id",
        "node_id",
        "state",
    )
''')
