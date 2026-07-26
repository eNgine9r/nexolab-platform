"""add append-only rendered reports and approval events

Revision ID: 20260726_0013
Revises: 20260726_0012
Create Date: 2026-07-26 20:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260726_0013"
down_revision = "20260726_0012"
branch_labels = None
depends_on = None

RENDER_FORMATS = "'xlsx', 'pdf'"
APPROVAL_EVENT_TYPES = "'approved', 'superseded'"
APPEND_ONLY_TABLES = ("test_report_renders", "test_report_approval_events")


def upgrade() -> None:
    op.create_table(
        "test_report_renders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("artifact_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("renderer_version", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("rendered_by", sa.String(length=255), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"format IN ({RENDER_FORMATS})",
            name="ck_test_report_renders_format",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_test_report_renders_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["test_report_versions.id"],
            name="fk_test_report_renders_report",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_test_report_renders_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_test_report_renders_organization_idempotency",
        ),
    )
    op.create_index(
        "ix_test_report_renders_organization_report",
        "test_report_renders",
        ["organization_id", "report_id", "format", "rendered_at"],
    )

    op.create_table(
        "test_report_approval_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("actor_identity_id", sa.String(length=36), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by_report_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"event_type IN ({APPROVAL_EVENT_TYPES})",
            name="ck_test_report_approval_events_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'approved' AND superseded_by_report_id IS NULL) "
            "OR (event_type = 'superseded' AND superseded_by_report_id IS NOT NULL)",
            name="ck_test_report_approval_events_payload",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["test_report_versions.id"],
            name="fk_test_report_approval_events_report",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_test_report_approval_events_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_report_id"],
            ["test_report_versions.id"],
            name="fk_test_report_approval_events_replacement",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_test_report_approval_events_organization_idempotency",
        ),
        sa.UniqueConstraint(
            "report_id",
            "event_type",
            name="uq_test_report_approval_events_report_type",
        ),
    )
    op.create_index(
        "ix_test_report_approval_events_organization_report",
        "test_report_approval_events",
        ["organization_id", "report_id", "occurred_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
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
    for table_name in reversed(APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_delete")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_update")

    op.drop_index(
        "ix_test_report_approval_events_organization_report",
        table_name="test_report_approval_events",
    )
    op.drop_table("test_report_approval_events")
    op.drop_index(
        "ix_test_report_renders_organization_report",
        table_name="test_report_renders",
    )
    op.drop_table("test_report_renders")
