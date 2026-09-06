"""add Signal acquisition-source binding history

Revision ID: 20260906_0034
Revises: 20260906_0033
Create Date: 2026-09-06 04:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260906_0034"
down_revision = "20260906_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_signal_acquisition_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("evidence_reference", sa.String(length=512), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version = 'acquisition-source/v1'",
            name="ck_instrument_signal_acquisition_schema_version",
        ),
        sa.CheckConstraint(
            "evidence_status IN ('software_verified', 'hardware_unverified', 'hardware_verified')",
            name="ck_instrument_signal_acquisition_evidence_status",
        ),
        sa.CheckConstraint(
            "evidence_status <> 'hardware_verified' OR "
            "(evidence_reference IS NOT NULL AND btrim(evidence_reference) <> '')",
            name="ck_instrument_signal_acquisition_hardware_evidence",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_instrument_signal_acquisition_revision_positive"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_instrument_signal_acquisition_interval",
        ),
        sa.CheckConstraint(
            "btrim(node_id) <> '' AND btrim(equipment_id) <> '' AND "
            "btrim(channel_id) <> '' AND btrim(metric) <> '' AND btrim(unit) <> ''",
            name="ck_instrument_signal_acquisition_identity_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_signal_acquisition_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_instrument_signal_acquisition_signal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "signal_id",
            "revision",
            name="uq_instrument_signal_acquisition_revision",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "signal_id",
            "id",
            name="uq_instrument_signal_acquisition_identity",
        ),
    )
    op.create_index(
        "ix_instrument_signal_acquisition_as_of",
        "instrument_signal_acquisition_history",
        ["organization_id", "signal_id", "valid_from", "valid_to", "revision"],
    )
    op.create_index(
        "uq_instrument_signal_acquisition_open",
        "instrument_signal_acquisition_history",
        ["organization_id", "signal_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.add_column(
        "instrument_analog_scaling_history",
        sa.Column("acquisition_source_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_instrument_analog_scaling_acquisition_source",
        "instrument_analog_scaling_history",
        "instrument_signal_acquisition_history",
        ["organization_id", "signal_id", "acquisition_source_id"],
        ["organization_id", "signal_id", "id"],
        ondelete="RESTRICT",
    )
    _create_history_guard()


def _create_history_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_instrument_signal_acquisition_history()
        RETURNS trigger AS $$
        DECLARE
            signal_unit text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Signal acquisition-source history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_to')
                OR OLD.valid_to IS NOT NULL
                OR NEW.valid_to IS NULL
            ) THEN
                RAISE EXCEPTION 'Signal acquisition-source identity is immutable except interval closure';
            END IF;

            SELECT engineering_unit INTO signal_unit
            FROM instrument_signals
            WHERE organization_id = NEW.organization_id AND id = NEW.signal_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'owning instrument Signal was not found';
            END IF;
            IF NEW.unit IS DISTINCT FROM signal_unit THEN
                RAISE EXCEPTION 'acquisition-source unit must match owning Signal';
            END IF;
            IF NEW.evidence_status = 'hardware_verified' AND (
                NEW.evidence_reference IS NULL OR btrim(NEW.evidence_reference) = ''
            ) THEN
                RAISE EXCEPTION 'hardware-verified acquisition source requires evidence reference';
            END IF;

            IF EXISTS (
                SELECT 1 FROM instrument_signal_acquisition_history AS existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.signal_id = NEW.signal_id
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.valid_from, existing.valid_to, '[)')
                      && tstzrange(NEW.valid_from, NEW.valid_to, '[)')
            ) THEN
                RAISE EXCEPTION 'Signal acquisition-source history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_instrument_signal_acquisition_history_guard
        BEFORE INSERT OR UPDATE OR DELETE ON instrument_signal_acquisition_history
        FOR EACH ROW EXECUTE FUNCTION guard_instrument_signal_acquisition_history();
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_instrument_analog_scaling_acquisition_source",
        "instrument_analog_scaling_history",
        type_="foreignkey",
    )
    op.drop_column(
        "instrument_analog_scaling_history",
        "acquisition_source_id",
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_instrument_signal_acquisition_history_guard "
        "ON instrument_signal_acquisition_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_instrument_signal_acquisition_history()")
    op.drop_index(
        "uq_instrument_signal_acquisition_open",
        table_name="instrument_signal_acquisition_history",
    )
    op.drop_index(
        "ix_instrument_signal_acquisition_as_of",
        table_name="instrument_signal_acquisition_history",
    )
    op.drop_table("instrument_signal_acquisition_history")
