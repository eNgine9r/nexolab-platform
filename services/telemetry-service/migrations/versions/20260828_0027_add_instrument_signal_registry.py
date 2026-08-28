"""add generic Instrument and Signal registry

Revision ID: 20260828_0027
Revises: 20260820_0026
Create Date: 2026-08-28 10:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_0027"
down_revision = "20260820_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("inventory_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("instrument_kind", sa.String(length=64), nullable=False),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
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
            "lifecycle_state IN ('active', 'inactive', 'retired')",
            name="ck_instruments_lifecycle_state",
        ),
        sa.CheckConstraint("version >= 1", name="ck_instruments_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instruments_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_instruments_organization_id"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "inventory_key",
            name="uq_instruments_organization_inventory_key",
        ),
    )
    op.create_index(
        "ix_instruments_organization_lifecycle_name",
        "instruments",
        ["organization_id", "lifecycle_state", "display_name", "id"],
        unique=False,
    )

    op.create_table(
        "instrument_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("business_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("physical_quantity", sa.String(length=64), nullable=False),
        sa.Column("engineering_unit", sa.String(length=64), nullable=False),
        sa.Column(
            "lifecycle_state",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "metadata",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
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
            "lifecycle_state IN ('active', 'inactive', 'retired')",
            name="ck_instrument_signals_lifecycle_state",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_instrument_signals_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_signals_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_signals_instrument",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_instrument_signals_organization_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_instrument_signals_organization_business_key",
        ),
    )
    op.create_index(
        "ix_instrument_signals_instrument_lifecycle",
        "instrument_signals",
        [
            "organization_id",
            "instrument_id",
            "lifecycle_state",
            "display_name",
            "id",
        ],
        unique=False,
    )

    op.create_table(
        "instrument_acceptance_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("accepted_for_calculation", sa.Boolean(), nullable=False),
        sa.Column("state_label", sa.String(length=64), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 'acceptance-state/v1'",
            name="ck_instrument_acceptance_schema_version",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_instrument_acceptance_revision_positive"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_acceptance_interval",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_acceptance_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_acceptance_instrument",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "instrument_id",
            "revision",
            name="uq_instrument_acceptance_revision",
        ),
    )
    op.create_index(
        "ix_instrument_acceptance_as_of",
        "instrument_acceptance_history",
        [
            "organization_id",
            "instrument_id",
            "effective_from",
            "effective_to",
            "revision",
        ],
        unique=False,
    )
    op.create_index(
        "uq_instrument_acceptance_open",
        "instrument_acceptance_history",
        ["organization_id", "instrument_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    op.create_table(
        "instrument_calibration_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column(
            "calibration_scope",
            sa.String(length=64),
            server_default="instrument",
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("certificate_reference", sa.String(length=512), nullable=True),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 'calibration-state/v1'",
            name="ck_instrument_calibration_schema_version",
        ),
        sa.CheckConstraint(
            "state IN ('valid', 'due', 'expired', 'revoked', 'unknown')",
            name="ck_instrument_calibration_state",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_instrument_calibration_revision_positive"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_instrument_calibration_interval",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_calibration_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "instrument_id"],
            ["instruments.organization_id", "instruments.id"],
            name="fk_instrument_calibration_instrument",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "instrument_id",
            "calibration_scope",
            "revision",
            name="uq_instrument_calibration_revision",
        ),
    )
    op.create_index(
        "ix_instrument_calibration_as_of",
        "instrument_calibration_history",
        [
            "organization_id",
            "instrument_id",
            "calibration_scope",
            "valid_from",
            "valid_to",
            "revision",
        ],
        unique=False,
    )
    op.create_index(
        "uq_instrument_calibration_open",
        "instrument_calibration_history",
        ["organization_id", "instrument_id", "calibration_scope"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    _create_history_guards()


def _create_history_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_instrument_acceptance_history()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'instrument acceptance history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'effective_to') IS DISTINCT FROM
                    (to_jsonb(OLD) - 'effective_to')
                OR OLD.effective_to IS NOT NULL
                OR NEW.effective_to IS NULL
            ) THEN
                RAISE EXCEPTION 'instrument acceptance history is immutable except interval closure';
            END IF;
            PERFORM 1
            FROM instruments
            WHERE organization_id = NEW.organization_id
              AND id = NEW.instrument_id
            FOR UPDATE;
            IF EXISTS (
                SELECT 1
                FROM instrument_acceptance_history AS existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.instrument_id = NEW.instrument_id
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.effective_from, existing.effective_to, '[)')
                      && tstzrange(NEW.effective_from, NEW.effective_to, '[)')
            ) THEN
                RAISE EXCEPTION 'instrument acceptance history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_instrument_acceptance_history_guard
        BEFORE INSERT OR UPDATE OR DELETE ON instrument_acceptance_history
        FOR EACH ROW EXECUTE FUNCTION guard_instrument_acceptance_history();
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_instrument_calibration_history()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'instrument calibration history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM
                    (to_jsonb(OLD) - 'valid_to')
                OR OLD.valid_to IS NOT NULL
                OR NEW.valid_to IS NULL
            ) THEN
                RAISE EXCEPTION 'instrument calibration history is immutable except interval closure';
            END IF;
            PERFORM 1
            FROM instruments
            WHERE organization_id = NEW.organization_id
              AND id = NEW.instrument_id
            FOR UPDATE;
            IF EXISTS (
                SELECT 1
                FROM instrument_calibration_history AS existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.instrument_id = NEW.instrument_id
                  AND existing.calibration_scope = NEW.calibration_scope
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.valid_from, existing.valid_to, '[)')
                      && tstzrange(NEW.valid_from, NEW.valid_to, '[)')
            ) THEN
                RAISE EXCEPTION 'instrument calibration history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_instrument_calibration_history_guard
        BEFORE INSERT OR UPDATE OR DELETE ON instrument_calibration_history
        FOR EACH ROW EXECUTE FUNCTION guard_instrument_calibration_history();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_instrument_calibration_history_guard "
        "ON instrument_calibration_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_instrument_calibration_history()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_instrument_acceptance_history_guard "
        "ON instrument_acceptance_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_instrument_acceptance_history()")

    op.drop_index(
        "uq_instrument_calibration_open",
        table_name="instrument_calibration_history",
    )
    op.drop_index(
        "ix_instrument_calibration_as_of",
        table_name="instrument_calibration_history",
    )
    op.drop_table("instrument_calibration_history")
    op.drop_index(
        "uq_instrument_acceptance_open",
        table_name="instrument_acceptance_history",
    )
    op.drop_index(
        "ix_instrument_acceptance_as_of",
        table_name="instrument_acceptance_history",
    )
    op.drop_table("instrument_acceptance_history")
    op.drop_index(
        "ix_instrument_signals_instrument_lifecycle",
        table_name="instrument_signals",
    )
    op.drop_table("instrument_signals")
    op.drop_index(
        "ix_instruments_organization_lifecycle_name",
        table_name="instruments",
    )
    op.drop_table("instruments")
