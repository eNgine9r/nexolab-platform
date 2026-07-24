"""harden immutable session audit and create idempotency

Revision ID: 20260724_0006
Revises: 20260724_0005
Create Date: 2026-07-24 13:35:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260724_0006"
down_revision = "20260724_0005"
branch_labels = None
depends_on = None


def _replace_transaction_foreign_keys(*, deferred: bool) -> None:
    op.drop_constraint(
        "fk_session_events_session_id",
        "session_events",
        type_="foreignkey",
    )
    for constraint_name in (
        "fk_audit_log_session_id",
        "fk_audit_log_session_event_id",
    ):
        op.drop_constraint(
            constraint_name,
            "audit_log",
            type_="foreignkey",
        )

    options = (
        {"deferrable": True, "initially": "DEFERRED"}
        if deferred
        else {}
    )
    op.create_foreign_key(
        "fk_session_events_session_id",
        "session_events",
        "test_sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
        **options,
    )
    op.create_foreign_key(
        "fk_audit_log_session_id",
        "audit_log",
        "test_sessions",
        ["session_id"],
        ["id"],
        ondelete="RESTRICT",
        **options,
    )
    op.create_foreign_key(
        "fk_audit_log_session_event_id",
        "audit_log",
        "session_events",
        ["session_event_id"],
        ["id"],
        ondelete="RESTRICT",
        **options,
    )


def upgrade() -> None:
    op.create_index(
        "uq_session_created_idempotency_key",
        "session_events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("event_type = 'session_created'"),
        sqlite_where=sa.text("event_type = 'session_created'"),
    )
    op.create_index(
        "ix_session_events_stable_order",
        "session_events",
        ["session_id", "occurred_at", "inserted_at", "id"],
    )
    op.create_index(
        "ix_audit_log_stable_order",
        "audit_log",
        ["session_id", "occurred_at", "inserted_at", "id"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _replace_transaction_foreign_keys(deferred=True)
        op.execute(
            """
            CREATE OR REPLACE FUNCTION nexolab_reject_audit_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END;
            $$
            """
        )
        for table_name in ("session_events", "audit_log"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_audit_mutation()
                """
            )
    elif dialect == "sqlite":
        for table_name in ("session_events", "audit_log"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in ("session_events", "audit_log"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
                f"ON {table_name}"
            )
        op.execute("DROP FUNCTION IF EXISTS nexolab_reject_audit_mutation()")
        _replace_transaction_foreign_keys(deferred=False)
    elif dialect == "sqlite":
        for table_name in ("session_events", "audit_log"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_update"
            )
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_delete"
            )

    op.drop_index("ix_audit_log_stable_order", table_name="audit_log")
    op.drop_index("ix_session_events_stable_order", table_name="session_events")
    op.drop_index(
        "uq_session_created_idempotency_key",
        table_name="session_events",
    )
