from pathlib import Path

root = Path(__file__).resolve().parents[2]
models_path = root / "services/telemetry-service/app/sessions/models.py"
models = models_path.read_text()

states_marker = '''SESSION_STAGE_TYPES = (
    "preparation",
'''
if states_marker not in models:
    raise SystemExit("session model constants marker not found")
models = models.replace(
    states_marker,
    '''DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"

SESSION_STAGE_TYPES = (
    "preparation",
''',
    1,
)

old_args = '''        Index("ix_test_sessions_state_created", "state", "created_at"),
        Index("ix_test_sessions_node_state", "node_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_number: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
'''
new_args = '''        UniqueConstraint(
            "organization_id",
            "session_number",
            name="uq_test_sessions_organization_number",
        ),
        Index("ix_test_sessions_state_created", "state", "created_at"),
        Index("ix_test_sessions_node_state", "node_id", "state"),
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_test_sessions_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
        default=DEFAULT_ORGANIZATION_ID,
    )
    session_number: Mapped[str] = mapped_column(String(64), nullable=False)
'''
if old_args not in models:
    raise SystemExit("test session model table marker not found")
models_path.write_text(models.replace(old_args, new_args, 1))

migration_path = (
    root
    / "services/telemetry-service/migrations/versions/20260726_0009_scope_test_sessions_to_organizations.py"
)
migration_path.write_text('''"""scope laboratory sessions to organizations

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
''')

test_path = root / "services/telemetry-service/tests/test_session_schema.py"
tests = test_path.read_text()

old_metadata_test = '''def test_session_event_idempotency_is_enforced_in_metadata() -> None:
'''
new_metadata_test = '''def test_session_organization_scope_is_enforced_in_metadata() -> None:
    register_models()

    table = Base.metadata.tables["test_sessions"]
    assert table.columns["organization_id"].nullable is False
    assert table.columns["organization_id"].foreign_keys

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints["uq_test_sessions_organization_number"] == (
        "organization_id",
        "session_number",
    )

    indexes = {index.name: index for index in table.indexes}
    assert tuple(
        column.name
        for column in indexes[
            "ix_test_sessions_organization_state_created"
        ].columns
    ) == ("organization_id", "state", "created_at")


def test_session_event_idempotency_is_enforced_in_metadata() -> None:
'''
if old_metadata_test not in tests:
    raise SystemExit("session schema metadata test marker not found")
tests = tests.replace(old_metadata_test, new_metadata_test, 1)

old_fk_assert = '''        assert {
            "fk_test_sessions_current_stage_id",
            "fk_test_sessions_active_config_snapshot_id",
        } <= session_foreign_keys

        event_unique_constraints = {
'''
new_fk_assert = '''        assert {
            "fk_test_sessions_current_stage_id",
            "fk_test_sessions_active_config_snapshot_id",
            "fk_test_sessions_organization",
        } <= session_foreign_keys

        session_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("test_sessions")
        }
        assert session_unique_constraints[
            "uq_test_sessions_organization_number"
        ] == ("organization_id", "session_number")

        session_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("test_sessions")
        }
        assert {
            "ix_test_sessions_organization_state_created",
            "ix_test_sessions_organization_node_state",
        } <= set(session_indexes)

        event_unique_constraints = {
'''
if old_fk_assert not in tests:
    raise SystemExit("session schema migration test marker not found")
test_path.write_text(tests.replace(old_fk_assert, new_fk_assert, 1))
