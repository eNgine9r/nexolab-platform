"""add refrigeration circuit configuration and semantic binding domain

Revision ID: 20260906_0035
Revises: 20260906_0034
Create Date: 2026-09-06 11:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260906_0035"
down_revision = "20260906_0034"
branch_labels = None
depends_on = None


LIFECYCLE_STATES = "'active', 'inactive', 'retired'"
PROCESS_ROLES = (
    "'suction_pressure', 'condensing_pressure', 'suction_line_temperature', "
    "'liquid_line_temperature', 'atmospheric_pressure', 'relative_humidity'"
)


def upgrade() -> None:
    op.create_table(
        "refrigeration_circuits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=36), nullable=False),
        sa.Column("business_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "btrim(business_key) <> ''", name="ck_refrigeration_circuits_business_key"
        ),
        sa.CheckConstraint(
            "btrim(display_name) <> ''", name="ck_refrigeration_circuits_display_name"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_refrigeration_circuits_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_refrigeration_circuits_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "id", name="uq_refrigeration_circuits_organization_id"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "business_key",
            name="uq_refrigeration_circuits_organization_business_key",
        ),
    )
    op.create_index(
        "ix_refrigeration_circuits_equipment",
        "refrigeration_circuits",
        ["organization_id", "equipment_id", "business_key"],
    )

    op.create_table(
        "refrigeration_circuit_lifecycle_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("circuit_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"state IN ({LIFECYCLE_STATES})", name="ck_refrigeration_circuit_lifecycle_state"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_lifecycle_interval",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_refrigeration_circuit_lifecycle_revision"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_lifecycle_circuit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "circuit_id",
            "revision",
            name="uq_refrigeration_circuit_lifecycle_revision",
        ),
    )
    op.create_index(
        "ix_refrigeration_circuit_lifecycle_as_of",
        "refrigeration_circuit_lifecycle_history",
        ["organization_id", "circuit_id", "valid_from", "valid_to", "revision"],
    )
    op.create_index(
        "uq_refrigeration_circuit_lifecycle_open",
        "refrigeration_circuit_lifecycle_history",
        ["organization_id", "circuit_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "refrigeration_circuit_configuration_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("circuit_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("refrigerant_code", sa.String(length=64), nullable=False),
        sa.Column("calculation_policy_version", sa.String(length=128), nullable=False),
        sa.Column("property_provider_profile", sa.String(length=255), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "schema_version = 'refrigeration-circuit-configuration/v1'",
            name="ck_refrigeration_circuit_configuration_schema",
        ),
        sa.CheckConstraint(
            "btrim(refrigerant_code) <> ''", name="ck_refrigeration_circuit_refrigerant"
        ),
        sa.CheckConstraint(
            "btrim(calculation_policy_version) <> ''",
            name="ck_refrigeration_circuit_calculation_policy",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_configuration_interval",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_refrigeration_circuit_configuration_revision"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_configuration_circuit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "circuit_id",
            "revision",
            name="uq_refrigeration_circuit_configuration_revision",
        ),
    )
    op.create_index(
        "ix_refrigeration_circuit_configuration_as_of",
        "refrigeration_circuit_configuration_history",
        ["organization_id", "circuit_id", "valid_from", "valid_to", "revision"],
    )
    op.create_index(
        "uq_refrigeration_circuit_configuration_open",
        "refrigeration_circuit_configuration_history",
        ["organization_id", "circuit_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "refrigeration_circuit_signal_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("circuit_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(length=255), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_by", sa.String(length=255), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"role IN ({PROCESS_ROLES})", name="ck_refrigeration_circuit_signal_binding_role"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_refrigeration_circuit_signal_binding_interval",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_refrigeration_circuit_signal_binding_revision"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "circuit_id"],
            ["refrigeration_circuits.organization_id", "refrigeration_circuits.id"],
            name="fk_refrigeration_circuit_signal_binding_circuit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_id"],
            ["instrument_signals.organization_id", "instrument_signals.id"],
            name="fk_refrigeration_circuit_signal_binding_signal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "circuit_id",
            "role",
            "revision",
            name="uq_refrigeration_circuit_signal_binding_revision",
        ),
    )
    op.create_index(
        "ix_refrigeration_circuit_signal_binding_as_of",
        "refrigeration_circuit_signal_bindings",
        ["organization_id", "circuit_id", "role", "valid_from", "valid_to", "revision"],
    )
    op.create_index(
        "uq_refrigeration_circuit_signal_binding_open",
        "refrigeration_circuit_signal_bindings",
        ["organization_id", "circuit_id", "role"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    _create_history_guards()


def _create_history_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_refrigeration_circuit_lifecycle_history()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Refrigeration circuit lifecycle history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_to')
                OR OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
            ) THEN
                RAISE EXCEPTION 'Circuit lifecycle history identity is immutable except interval closure';
            END IF;
            PERFORM 1
            FROM refrigeration_circuits
            WHERE organization_id = NEW.organization_id AND id = NEW.circuit_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refrigeration circuit authority was not found';
            END IF;
            IF EXISTS (
                SELECT 1 FROM refrigeration_circuit_lifecycle_history existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.circuit_id = NEW.circuit_id
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.valid_from, existing.valid_to, '[)')
                      && tstzrange(NEW.valid_from, NEW.valid_to, '[)')
            ) THEN
                RAISE EXCEPTION 'Circuit lifecycle history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refrigeration_circuit_lifecycle_guard
        BEFORE INSERT OR UPDATE OR DELETE ON refrigeration_circuit_lifecycle_history
        FOR EACH ROW EXECUTE FUNCTION guard_refrigeration_circuit_lifecycle_history();
        """
    )

    op.execute(
        """
        CREATE FUNCTION guard_refrigeration_circuit_configuration_history()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Refrigeration circuit configuration history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'valid_to') IS DISTINCT FROM (to_jsonb(OLD) - 'valid_to')
                OR OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
            ) THEN
                RAISE EXCEPTION 'Circuit configuration identity is immutable except interval closure';
            END IF;
            PERFORM 1
            FROM refrigeration_circuits
            WHERE organization_id = NEW.organization_id AND id = NEW.circuit_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refrigeration circuit authority was not found';
            END IF;
            IF EXISTS (
                SELECT 1 FROM refrigeration_circuit_configuration_history existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.circuit_id = NEW.circuit_id
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.valid_from, existing.valid_to, '[)')
                      && tstzrange(NEW.valid_from, NEW.valid_to, '[)')
            ) THEN
                RAISE EXCEPTION 'Circuit configuration history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refrigeration_circuit_configuration_guard
        BEFORE INSERT OR UPDATE OR DELETE ON refrigeration_circuit_configuration_history
        FOR EACH ROW EXECUTE FUNCTION guard_refrigeration_circuit_configuration_history();
        """
    )

    op.execute(
        """
        CREATE FUNCTION guard_refrigeration_circuit_signal_binding()
        RETURNS trigger AS $$
        DECLARE
            signal_quantity text;
            signal_unit text;
            signal_state text;
            instrument_kind text;
            pressure_reference text;
            instrument_state text;
            accepted_count integer;
            accepted_value boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Refrigeration circuit semantic binding history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - ARRAY['valid_to', 'ended_by', 'ended_at'])
                    IS DISTINCT FROM
                (to_jsonb(OLD) - ARRAY['valid_to', 'ended_by', 'ended_at'])
                OR OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
                OR NEW.ended_by IS NULL OR btrim(NEW.ended_by) = '' OR NEW.ended_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Semantic binding identity is immutable except explicit interval closure';
            END IF;

            PERFORM 1
            FROM refrigeration_circuits
            WHERE organization_id = NEW.organization_id AND id = NEW.circuit_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Refrigeration circuit authority was not found';
            END IF;

            SELECT s.physical_quantity, s.engineering_unit, s.lifecycle_state,
                   i.instrument_kind, i.pressure_reference, i.lifecycle_state
            INTO signal_quantity, signal_unit, signal_state,
                 instrument_kind, pressure_reference, instrument_state
            FROM instrument_signals s
            JOIN instruments i
              ON i.organization_id = s.organization_id AND i.id = s.instrument_id
            WHERE s.organization_id = NEW.organization_id AND s.id = NEW.signal_id
            FOR UPDATE OF s, i;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Semantic binding Signal/Instrument authority was not found';
            END IF;
            IF TG_OP = 'INSERT' AND (
                signal_state <> 'active' OR instrument_state <> 'active'
            ) THEN
                RAISE EXCEPTION 'Semantic binding requires active Signal and Instrument';
            END IF;

            IF NEW.role IN ('suction_pressure', 'condensing_pressure', 'atmospheric_pressure') THEN
                IF signal_quantity <> 'pressure' OR signal_unit NOT IN ('bar', 'kPa')
                   OR pressure_reference NOT IN ('absolute', 'gauge') THEN
                    RAISE EXCEPTION 'Pressure role requires typed pressure Signal, supported explicit unit and pressure reference';
                END IF;
                IF NEW.role = 'atmospheric_pressure' AND (
                    pressure_reference <> 'absolute' OR instrument_kind <> 'barometric_pressure_sensor'
                ) THEN
                    RAISE EXCEPTION 'Atmospheric role requires absolute barometric pressure authority';
                END IF;
            ELSIF NEW.role IN ('suction_line_temperature', 'liquid_line_temperature') THEN
                IF signal_quantity <> 'temperature' OR signal_unit <> 'degC' THEN
                    RAISE EXCEPTION 'Temperature role requires temperature Signal in degC';
                END IF;
            ELSIF NEW.role = 'relative_humidity' THEN
                IF signal_quantity <> 'relative_humidity' OR signal_unit <> '%RH' THEN
                    RAISE EXCEPTION 'Humidity role requires the canonical relative humidity unit';
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported refrigeration circuit semantic role';
            END IF;

            SELECT count(*), bool_and(accepted_for_calculation)
            INTO accepted_count, accepted_value
            FROM instrument_acceptance_history
            WHERE organization_id = NEW.organization_id
              AND instrument_id = (
                  SELECT instrument_id FROM instrument_signals
                  WHERE organization_id = NEW.organization_id AND id = NEW.signal_id
              )
              AND effective_from <= NEW.valid_from
              AND (effective_to IS NULL OR effective_to > NEW.valid_from);
            IF accepted_count <> 1 OR accepted_value IS DISTINCT FROM true THEN
                RAISE EXCEPTION 'Semantic binding requires exactly one accepted Instrument authority';
            END IF;

            IF EXISTS (
                SELECT 1 FROM refrigeration_circuit_signal_bindings existing
                WHERE existing.organization_id = NEW.organization_id
                  AND existing.circuit_id = NEW.circuit_id
                  AND existing.role = NEW.role
                  AND existing.id <> NEW.id
                  AND tstzrange(existing.valid_from, existing.valid_to, '[)')
                      && tstzrange(NEW.valid_from, NEW.valid_to, '[)')
            ) THEN
                RAISE EXCEPTION 'Semantic binding intervals overlap for circuit role';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refrigeration_circuit_signal_binding_guard
        BEFORE INSERT OR UPDATE OR DELETE ON refrigeration_circuit_signal_bindings
        FOR EACH ROW EXECUTE FUNCTION guard_refrigeration_circuit_signal_binding();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_refrigeration_circuit_signal_binding_guard "
        "ON refrigeration_circuit_signal_bindings"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_refrigeration_circuit_signal_binding()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_refrigeration_circuit_configuration_guard "
        "ON refrigeration_circuit_configuration_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_refrigeration_circuit_configuration_history()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_refrigeration_circuit_lifecycle_guard "
        "ON refrigeration_circuit_lifecycle_history"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_refrigeration_circuit_lifecycle_history()")

    op.drop_index(
        "uq_refrigeration_circuit_signal_binding_open",
        table_name="refrigeration_circuit_signal_bindings",
    )
    op.drop_index(
        "ix_refrigeration_circuit_signal_binding_as_of",
        table_name="refrigeration_circuit_signal_bindings",
    )
    op.drop_table("refrigeration_circuit_signal_bindings")
    op.drop_index(
        "uq_refrigeration_circuit_configuration_open",
        table_name="refrigeration_circuit_configuration_history",
    )
    op.drop_index(
        "ix_refrigeration_circuit_configuration_as_of",
        table_name="refrigeration_circuit_configuration_history",
    )
    op.drop_table("refrigeration_circuit_configuration_history")
    op.drop_index(
        "uq_refrigeration_circuit_lifecycle_open",
        table_name="refrigeration_circuit_lifecycle_history",
    )
    op.drop_index(
        "ix_refrigeration_circuit_lifecycle_as_of",
        table_name="refrigeration_circuit_lifecycle_history",
    )
    op.drop_table("refrigeration_circuit_lifecycle_history")
    op.drop_index("ix_refrigeration_circuits_equipment", table_name="refrigeration_circuits")
    op.drop_table("refrigeration_circuits")
