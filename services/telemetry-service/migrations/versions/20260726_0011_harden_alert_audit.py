"""harden append-only alert audit storage

Revision ID: 20260726_0011
Revises: 20260726_0010
Create Date: 2026-07-26 15:10:00
"""
from __future__ import annotations

from alembic import op

revision = "20260726_0011"
down_revision = "20260726_0010"
branch_labels = None
depends_on = None


TABLES = (
    "alert_rule_versions",
    "alert_transitions",
    "alert_evidence_samples",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION nexolab_reject_append_only_alert_mutation()
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
        for table_name in TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_update
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_append_only_alert_mutation()
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_delete
                BEFORE DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_append_only_alert_mutation()
                """
            )
        return

    if bind.dialect.name == "sqlite":
        for table_name in TABLES:
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_append_only_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_append_only_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_delete")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_update")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS nexolab_reject_append_only_alert_mutation()"
        )
