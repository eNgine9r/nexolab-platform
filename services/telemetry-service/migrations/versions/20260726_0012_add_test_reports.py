"""add immutable test reports and evidence artifacts

Revision ID: 20260726_0012
Revises: 20260726_0011
Create Date: 2026-07-26 17:40:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0012"
down_revision = "20260726_0011"
branch_labels = None
depends_on = None

REPORTABLE_SESSION_STATES = "'completed', 'archived'"
APPEND_ONLY_TABLES = ("test_report_versions", "test_report_artifacts")


def upgrade() -> None:
    op.create_table(
        "test_report_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("config_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("session_state", sa.String(length=32), nullable=False),
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("generated_by", sa.String(length=255), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_test_report_versions_version_positive",
        ),
        sa.CheckConstraint(
            f"session_state IN ({REPORTABLE_SESSION_STATES})",
            name="ck_test_report_versions_session_state",
        ),
        sa.CheckConstraint(
            "source_ended_at >= source_started_at",
            name="ck_test_report_versions_source_window",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_test_report_versions_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_test_report_versions_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"],
            ["session_config_snapshots.id"],
            name="fk_test_report_versions_config_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "version",
            name="uq_test_report_versions_session_version",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_test_report_versions_organization_idempotency",
        ),
    )
    op.create_index(
        "ix_test_report_versions_organization_generated",
        "test_report_versions",
        ["organization_id", "generated_at"],
    )
    op.create_index(
        "ix_test_report_versions_session_version",
        "test_report_versions",
        ["session_id", "version"],
    )

    op.create_table(
        "test_report_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_test_report_artifacts_size_nonnegative",
        ),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_test_report_artifacts_rows_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["test_report_versions.id"],
            name="fk_test_report_artifacts_report",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id",
            "name",
            name="uq_test_report_artifacts_report_name",
        ),
    )
    op.create_index(
        "ix_test_report_artifacts_report",
        "test_report_artifacts",
        ["report_id", "name"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION nexolab_reject_append_only_report_mutation()
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
        for table_name in APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_update
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_append_only_report_mutation()
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_delete
                BEFORE DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_append_only_report_mutation()
                """
            )
        return

    if bind.dialect.name == "sqlite":
        for table_name in APPEND_ONLY_TABLES:
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
    for table_name in reversed(APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_delete")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_update")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS nexolab_reject_append_only_report_mutation()"
        )

    op.drop_index(
        "ix_test_report_artifacts_report",
        table_name="test_report_artifacts",
    )
    op.drop_table("test_report_artifacts")
    op.drop_index(
        "ix_test_report_versions_session_version",
        table_name="test_report_versions",
    )
    op.drop_index(
        "ix_test_report_versions_organization_generated",
        table_name="test_report_versions",
    )
    op.drop_table("test_report_versions")
