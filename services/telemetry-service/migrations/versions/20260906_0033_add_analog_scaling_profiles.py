"""add versioned analog scaling profile history

Revision ID: 20260906_0033
Revises: 20260905_0032
Create Date: 2026-09-06 02:05:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260906_0033"
down_revision = "20260905_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_analog_scaling_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("electrical_input_class", sa.String(length=32), nullable=False),
        sa.Column("raw_unit", sa.String(length=32), nullable=False),
        sa.Column("raw_min", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("raw_max", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("engineering_min", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("engineering_max", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("engineering_unit", sa.String(length=64), nullable=False),
        sa.Column("scaling_policy", sa.String(length=32), nullable=False),
        sa.Column("under_range_policy", sa.String(length=32), nullable=False),
        sa.Column("over_range_policy", sa.String(length=32), nullable=False),
        sa.Column("acquisition_device_family", sa.String(length=64), nullable=True),
        sa.Column("acquisition_profile_id", sa.String(length=128), nullable=True),
        sa.Column("acquisition_profile_version", sa.String(length=128), nullable=True),
        sa.Column("acquisition_channel_reference", sa.String(length=255), nullable=True),
        sa.Column("evidence_reference", sa.String(length=512), nullable=True),
        sa.Column("calibration_scope", sa.String(length=64), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
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
            "schema_version = 'analog-scaling/v1'",
            name="ck_instrument_analog_scaling_schema_version",
        ),
        sa.CheckConstraint(
            "electrical_input_class = 'current_loop_4_20ma'",
            name="ck_instrument_analog_scaling_input_class",
        ),
        sa.CheckConstraint(
            "scaling_policy = 'linear_two_point'",
            name="ck_instrument_analog_scaling_policy",
        ),
        sa.CheckConstraint(
            "under_range_policy = 'unavailable'",
            name="ck_instrument_analog_scaling_under_range",
        ),
        sa.CheckConstraint(
            "over_range_policy = 'unavailable'",
            name="ck_instrument_analog_scaling_over_range",
        ),
        sa.CheckConstraint(
            "evidence_status IN ('software_verified', 'hardware_unverified', 'hardware_verified')",
            name="ck_instrument_analog_scaling_evidence_status",
        ),
        sa.CheckConstraint(
            "raw_min < raw_max",
            name="ck_instrument_analog_scaling_raw_domain",
        ),
        sa.CheckConstraint(
            "raw_min::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "raw_max::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "engineering_min::text NOT IN ('NaN', 'Infinity', '-Infinity') AND "
            "engineering_max::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name="ck_instrument_analog_scaling_finite_values",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_instrument_analog_scaling_revision_positive",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_analog_scaling_interval",
        ),
        sa.CheckConstraint(
            "evidence_status <> 'hardware_verified' OR "
            "(acquisition_device_family IS NOT NULL AND acquisition_profile_id IS NOT NULL "
            "AND acquisition_profile_version IS NOT NULL AND acquisition_channel_reference IS NOT NULL "
            "AND evidence_reference IS NOT NULL)",
            name="ck_instrument_analog_scaling_hardware_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_analog_scaling_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_instrument_analog_scaling_signal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "signal_id",
            "revision",
            name="uq_instrument_analog_scaling_revision",
        ),
    )
    op.create_index(
        "ix_instrument_analog_scaling_as_of",
        "instrument_analog_scaling_history",
        ["organization_id", "signal_id", "effective_from", "effective_to", "revision"],
        unique=False,
    )
    op.create_index(
        "uq_instrument_analog_scaling_open",
        "instrument_analog_scaling_history",
        ["organization_id", "signal_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )
    _create_analog_scaling_history_guard()


def _create_analog_scaling_history_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_instrument_analog_scaling_history()
        RETURNS trigger AS $$
        DECLARE
            signal_unit text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'instrument analog scaling history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'effective_to') IS DISTINCT FROM
                    (to_jsonb(OLD) - 'effective_to')
                OR OLD.effective_to IS NOT NULL
                OR NEW.effective_to IS NULL
            ) THEN
                RAISE EXCEPTION
                    'instrument analog scaling history is immutable except interval closure';
            END IF;

            SELECT engineering_unit
            INTO signal_unit
            FROM instrument_signals
            WHERE organization_id = NEW.organization_id
              AND id = NEW.signal_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'owning instrument signal was not found';
            END IF;
            IF NEW.engineering_unit IS DISTINCT FROM signal_unit THEN
                RAISE EXCEPTION
                    'analog scaling engineering_unit must match owning instrument signal';
            END IF;

            IF NEW.evidence_status = 'hardware_verified' AND (
                NEW.acquisition_device_family IS NULL
                OR btrim(NEW.acquisition_device_family) = ''
                OR NEW.acquisition_profile_id IS NULL
                OR btrim(NEW.acquisition_profile_id) = ''
                OR NEW.acquisition_profile_version IS NULL
                OR btrim(NEW.acquisition_profile_version) = ''
                OR NEW.acquisition_channel_reference IS NULL
                OR btrim(NEW.acquisition_channel_reference) = ''
                OR NEW.evidence_reference IS NULL
                OR btrim(NEW.evidence_reference) = ''
            ) THEN
                RAISE EXCEPTION
                    'hardware-verified analog scaling profile requires complete acquisition provenance';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM instrument_analog_scaling_history AS existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.signal_id = NEW.signal_id
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.effective_from, existing.effective_to, '[)')
                      && tstzrange(NEW.effective_from, NEW.effective_to, '[)')
            ) THEN
                RAISE EXCEPTION 'instrument analog scaling history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_instrument_analog_scaling_history_guard
        BEFORE INSERT OR UPDATE OR DELETE ON instrument_analog_scaling_history
        FOR EACH ROW EXECUTE FUNCTION guard_instrument_analog_scaling_history();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_instrument_analog_scaling_history_guard "
        "ON instrument_analog_scaling_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_instrument_analog_scaling_history()")
    op.drop_index(
        "uq_instrument_analog_scaling_open",
        table_name="instrument_analog_scaling_history",
    )
    op.drop_index(
        "ix_instrument_analog_scaling_as_of",
        table_name="instrument_analog_scaling_history",
    )
    op.drop_table("instrument_analog_scaling_history")
