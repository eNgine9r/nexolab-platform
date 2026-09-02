"""add deterministic daily refrigeration report profiles and snapshots

Revision ID: 20260902_0031
Revises: 20260902_0030
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260902_0031"
down_revision = "20260902_0030"
branch_labels = None
depends_on = None

_SNAPSHOT_TABLE = "refrigeration_daily_report_snapshots"


def upgrade() -> None:
    op.create_table(
        "refrigeration_daily_report_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Europe/Kyiv", nullable=False),
        sa.Column("report_hour", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("report_minute", sa.Integer(), server_default=sa.text("50"), nullable=False),
        sa.Column("weekdays", sa.JSON(), server_default=sa.text("'[0,1,2,3,4]'"), nullable=False),
        sa.Column("analysis_window_minutes", sa.Integer(), server_default=sa.text("720"), nullable=False),
        sa.Column("m_packet_channels", sa.JSON(), nullable=False),
        sa.Column("temperature_min_c", sa.Float(), nullable=True),
        sa.Column("temperature_max_c", sa.Float(), nullable=True),
        sa.Column("energy_source", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_daily_report_profiles_version_positive"),
        sa.CheckConstraint("report_hour BETWEEN 0 AND 23", name="ck_daily_report_profiles_hour"),
        sa.CheckConstraint("report_minute BETWEEN 0 AND 59", name="ck_daily_report_profiles_minute"),
        sa.CheckConstraint(
            "analysis_window_minutes BETWEEN 1 AND 10080",
            name="ck_daily_report_profiles_window",
        ),
        sa.CheckConstraint(
            "temperature_min_c IS NULL OR temperature_max_c IS NULL "
            "OR temperature_min_c < temperature_max_c",
            name="ck_daily_report_profiles_temperature_limits",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_daily_report_profiles_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_daily_report_profiles_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_daily_report_profiles_organization_id"
        ),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_daily_report_profiles_organization_name"
        ),
    )
    op.create_index(
        "ix_daily_report_profiles_organization_enabled",
        "refrigeration_daily_report_profiles",
        ["organization_id", "enabled", "equipment_id", "name"],
    )

    op.create_table(
        _SNAPSHOT_TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=36), nullable=False),
        sa.Column("local_report_date", sa.Date(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("generated_by", sa.String(length=255), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('normal', 'attention', 'critical', 'incomplete')",
            name="ck_daily_report_snapshots_status",
        ),
        sa.CheckConstraint("window_end > window_start", name="ck_daily_report_snapshots_window"),
        sa.ForeignKeyConstraint(
            ["organization_id", "profile_id"],
            [
                "refrigeration_daily_report_profiles.organization_id",
                "refrigeration_daily_report_profiles.id",
            ],
            name="fk_daily_report_snapshots_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_daily_report_snapshots_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "profile_id",
            "local_report_date",
            name="uq_daily_report_snapshots_profile_date",
        ),
    )
    op.create_index(
        "ix_daily_report_snapshots_organization_scheduled",
        _SNAPSHOT_TABLE,
        ["organization_id", "scheduled_for", "profile_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{_SNAPSHOT_TABLE}_append_only_{operation.lower()}
                BEFORE {operation} ON {_SNAPSHOT_TABLE}
                FOR EACH ROW
                EXECUTE FUNCTION nexolab_reject_append_only_report_mutation()
                """
            )
    elif bind.dialect.name == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{_SNAPSHOT_TABLE}_append_only_update
            BEFORE UPDATE ON {_SNAPSHOT_TABLE}
            BEGIN
                SELECT RAISE(ABORT, '{_SNAPSHOT_TABLE} is append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{_SNAPSHOT_TABLE}_append_only_delete
            BEFORE DELETE ON {_SNAPSHOT_TABLE}
            BEGIN
                SELECT RAISE(ABORT, '{_SNAPSHOT_TABLE} is append-only');
            END
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{_SNAPSHOT_TABLE}_append_only_delete ON {_SNAPSHOT_TABLE}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{_SNAPSHOT_TABLE}_append_only_update ON {_SNAPSHOT_TABLE}"
        )
    else:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{_SNAPSHOT_TABLE}_append_only_delete")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{_SNAPSHOT_TABLE}_append_only_update")
    op.drop_index(
        "ix_daily_report_snapshots_organization_scheduled",
        table_name=_SNAPSHOT_TABLE,
    )
    op.drop_table(_SNAPSHOT_TABLE)
    op.drop_index(
        "ix_daily_report_profiles_organization_enabled",
        table_name="refrigeration_daily_report_profiles",
    )
    op.drop_table("refrigeration_daily_report_profiles")
