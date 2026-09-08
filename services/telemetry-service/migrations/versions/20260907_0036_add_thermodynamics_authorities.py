"""add thermodynamics calculation-policy and acquisition-profile authorities

Revision ID: 20260907_0036
Revises: 20260906_0035
Create Date: 2026-09-07 15:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260907_0036"
down_revision = "20260906_0035"
branch_labels = None
depends_on = None

POLICY_SCHEMA = "refrigeration-calculation-policy/v1"
CALIBRATION_SCHEMA = "calibration-state/v1"
ACCEPTANCE_SCHEMA = "acceptance-state/v1"


def upgrade() -> None:
    op.add_column(
        "instrument_signal_acquisition_history",
        sa.Column("acquisition_profile_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "instrument_signal_acquisition_history",
        sa.Column("acquisition_profile_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "instrument_signal_acquisition_history",
        sa.Column("calibration_scope", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_instrument_signal_acquisition_profile_identity",
        "instrument_signal_acquisition_history",
        "(acquisition_profile_id IS NULL AND acquisition_profile_version IS NULL) OR "
        "(acquisition_profile_id IS NOT NULL AND btrim(acquisition_profile_id) <> '' "
        "AND acquisition_profile_version IS NOT NULL AND btrim(acquisition_profile_version) <> '')",
    )
    op.create_check_constraint(
        "ck_instrument_signal_acquisition_calibration_scope",
        "instrument_signal_acquisition_history",
        "calibration_scope IS NULL OR btrim(calibration_scope) <> ''",
    )
    op.create_unique_constraint(
        "uq_instrument_analog_scaling_identity",
        "instrument_analog_scaling_history",
        ["organization_id", "signal_id", "id"],
    )

    op.create_table(
        "refrigeration_calculation_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=128), nullable=False),
        sa.Column("maximum_age_ms", sa.BigInteger(), nullable=False),
        sa.Column("maximum_future_clock_skew_ms", sa.BigInteger(), nullable=False),
        sa.Column("maximum_cross_input_skew_ms", sa.BigInteger(), nullable=False),
        sa.Column(
            "calibration_vocabulary_version", sa.String(length=64), nullable=False
        ),
        sa.Column("accepted_calibration_states", sa.JSON(), nullable=False),
        sa.Column("require_calibration_at_observation", sa.Boolean(), nullable=False),
        sa.Column("calibration_required_roles", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"schema_version = '{POLICY_SCHEMA}'",
            name="ck_refrigeration_calculation_policy_schema",
        ),
        sa.CheckConstraint(
            f"calibration_vocabulary_version = '{CALIBRATION_SCHEMA}'",
            name="ck_refrigeration_calculation_policy_calibration_vocabulary",
        ),
        sa.CheckConstraint(
            "maximum_age_ms >= 0 AND maximum_future_clock_skew_ms >= 0 "
            "AND maximum_cross_input_skew_ms >= 0",
            name="ck_refrigeration_calculation_policy_durations",
        ),
        sa.CheckConstraint(
            "btrim(version) <> ''",
            name="ck_refrigeration_calculation_policy_version_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_refrigeration_calculation_policy_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "version",
            name="uq_refrigeration_calculation_policy_version",
        ),
    )

    op.create_table(
        "instrument_acquisition_profile_acceptance_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("acquisition_source_id", sa.String(length=36), nullable=False),
        sa.Column("scaling_profile_id", sa.String(length=36), nullable=True),
        sa.Column("profile_target_key", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("acquisition_profile_id", sa.String(length=128), nullable=False),
        sa.Column("acquisition_profile_version", sa.String(length=128), nullable=False),
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
            f"schema_version = '{ACCEPTANCE_SCHEMA}'",
            name="ck_instrument_acquisition_profile_acceptance_schema_version",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_instrument_acquisition_profile_acceptance_revision_positive",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_instrument_acquisition_profile_acceptance_interval",
        ),
        sa.CheckConstraint(
            "btrim(profile_target_key) <> '' AND btrim(acquisition_profile_id) <> '' "
            "AND btrim(acquisition_profile_version) <> ''",
            name="ck_instrument_acquisition_profile_acceptance_identity",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_instrument_acquisition_profile_acceptance_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_id", "acquisition_source_id"],
            [
                "instrument_signal_acquisition_history.organization_id",
                "instrument_signal_acquisition_history.signal_id",
                "instrument_signal_acquisition_history.id",
            ],
            name="fk_instrument_acquisition_profile_acceptance_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "signal_id", "scaling_profile_id"],
            [
                "instrument_analog_scaling_history.organization_id",
                "instrument_analog_scaling_history.signal_id",
                "instrument_analog_scaling_history.id",
            ],
            name="fk_instrument_acquisition_profile_acceptance_scaling_profile",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "signal_id",
            "profile_target_key",
            "revision",
            name="uq_instrument_acquisition_profile_acceptance_revision",
        ),
    )
    op.create_index(
        "ix_instrument_acquisition_profile_acceptance_as_of",
        "instrument_acquisition_profile_acceptance_history",
        [
            "organization_id",
            "signal_id",
            "profile_target_key",
            "effective_from",
            "effective_to",
            "revision",
        ],
    )
    op.create_index(
        "uq_instrument_acquisition_profile_acceptance_open",
        "instrument_acquisition_profile_acceptance_history",
        ["organization_id", "signal_id", "profile_target_key"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
    )

    _create_policy_guard()
    _create_profile_acceptance_guard()


def _create_policy_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_refrigeration_calculation_policy()
        RETURNS trigger AS $$
        DECLARE
            state_count integer;
            state_distinct_count integer;
            invalid_state_count integer;
            role_count integer;
            role_distinct_count integer;
            invalid_role_count integer;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                RAISE EXCEPTION 'Refrigeration calculation policy is immutable';
            END IF;
            IF json_typeof(NEW.accepted_calibration_states) <> 'array' THEN
                RAISE EXCEPTION 'accepted_calibration_states must be a JSON array';
            END IF;
            SELECT count(*), count(DISTINCT value),
                   count(*) FILTER (WHERE value NOT IN ('valid', 'due'))
              INTO state_count, state_distinct_count, invalid_state_count
              FROM json_array_elements_text(NEW.accepted_calibration_states);
            IF state_count = 0 OR state_count <> state_distinct_count OR invalid_state_count <> 0 THEN
                RAISE EXCEPTION 'accepted_calibration_states must be a non-empty unique subset of valid/due';
            END IF;
            IF json_typeof(NEW.calibration_required_roles) <> 'array' THEN
                RAISE EXCEPTION 'calibration_required_roles must be a JSON array';
            END IF;
            SELECT count(*), count(DISTINCT value),
                   count(*) FILTER (
                       WHERE value NOT IN (
                           'suction_pressure', 'condensing_pressure',
                           'suction_line_temperature', 'liquid_line_temperature',
                           'atmospheric_pressure'
                       )
                   )
              INTO role_count, role_distinct_count, invalid_role_count
              FROM json_array_elements_text(NEW.calibration_required_roles);
            IF role_count <> role_distinct_count OR invalid_role_count <> 0 THEN
                RAISE EXCEPTION 'calibration_required_roles contains unsupported or duplicate roles';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refrigeration_calculation_policy_guard
        BEFORE INSERT OR UPDATE OR DELETE ON refrigeration_calculation_policies
        FOR EACH ROW EXECUTE FUNCTION guard_refrigeration_calculation_policy();
        """
    )


def _create_profile_acceptance_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_instrument_acquisition_profile_acceptance_history()
        RETURNS trigger AS $$
        DECLARE
            expected_profile_id text;
            expected_profile_version text;
            scaling_source_id text;
            scaling_profile_id_value text;
            scaling_profile_version_value text;
            expected_target_key text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Acquisition profile acceptance history is append-oriented';
            END IF;
            IF TG_OP = 'UPDATE' AND (
                (to_jsonb(NEW) - 'effective_to') IS DISTINCT FROM
                    (to_jsonb(OLD) - 'effective_to')
                OR OLD.effective_to IS NOT NULL
                OR NEW.effective_to IS NULL
            ) THEN
                RAISE EXCEPTION 'Acquisition profile acceptance history is immutable except interval closure';
            END IF;

            SELECT acquisition_profile_id, acquisition_profile_version
              INTO expected_profile_id, expected_profile_version
              FROM instrument_signal_acquisition_history
             WHERE organization_id = NEW.organization_id
               AND signal_id = NEW.signal_id
               AND id = NEW.acquisition_source_id
             FOR UPDATE;
            IF NOT FOUND OR expected_profile_id IS NULL OR btrim(expected_profile_id) = ''
               OR expected_profile_version IS NULL OR btrim(expected_profile_version) = '' THEN
                RAISE EXCEPTION 'Referenced acquisition source has no explicit profile identity';
            END IF;

            expected_target_key := 'source:' || NEW.acquisition_source_id;
            IF NEW.scaling_profile_id IS NOT NULL THEN
                SELECT acquisition_source_id, acquisition_profile_id, acquisition_profile_version
                  INTO scaling_source_id, scaling_profile_id_value, scaling_profile_version_value
                  FROM instrument_analog_scaling_history
                 WHERE organization_id = NEW.organization_id
                   AND signal_id = NEW.signal_id
                   AND id = NEW.scaling_profile_id
                 FOR UPDATE;
                IF NOT FOUND
                   OR scaling_source_id IS DISTINCT FROM NEW.acquisition_source_id
                   OR scaling_profile_id_value IS DISTINCT FROM expected_profile_id
                   OR scaling_profile_version_value IS DISTINCT FROM expected_profile_version THEN
                    RAISE EXCEPTION 'Analog scaling profile does not match acquisition profile identity';
                END IF;
                expected_target_key := expected_target_key || '/scaling:' || NEW.scaling_profile_id;
            END IF;

            IF NEW.profile_target_key IS DISTINCT FROM expected_target_key
               OR NEW.acquisition_profile_id IS DISTINCT FROM expected_profile_id
               OR NEW.acquisition_profile_version IS DISTINCT FROM expected_profile_version THEN
                RAISE EXCEPTION 'Acquisition profile acceptance identity does not match referenced target';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM instrument_acquisition_profile_acceptance_history AS existing
                 WHERE existing.organization_id = NEW.organization_id
                   AND existing.signal_id = NEW.signal_id
                   AND existing.profile_target_key = NEW.profile_target_key
                   AND existing.id <> NEW.id
                   AND tstzrange(existing.effective_from, existing.effective_to, '[)')
                       && tstzrange(NEW.effective_from, NEW.effective_to, '[)')
            ) THEN
                RAISE EXCEPTION 'Acquisition profile acceptance history intervals overlap';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_instrument_acquisition_profile_acceptance_history_guard
        BEFORE INSERT OR UPDATE OR DELETE
        ON instrument_acquisition_profile_acceptance_history
        FOR EACH ROW EXECUTE FUNCTION guard_instrument_acquisition_profile_acceptance_history();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_instrument_acquisition_profile_acceptance_history_guard "
        "ON instrument_acquisition_profile_acceptance_history"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS guard_instrument_acquisition_profile_acceptance_history()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_refrigeration_calculation_policy_guard "
        "ON refrigeration_calculation_policies"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_refrigeration_calculation_policy()")
    op.drop_index(
        "uq_instrument_acquisition_profile_acceptance_open",
        table_name="instrument_acquisition_profile_acceptance_history",
    )
    op.drop_index(
        "ix_instrument_acquisition_profile_acceptance_as_of",
        table_name="instrument_acquisition_profile_acceptance_history",
    )
    op.drop_table("instrument_acquisition_profile_acceptance_history")
    op.drop_table("refrigeration_calculation_policies")
    op.drop_constraint(
        "uq_instrument_analog_scaling_identity",
        "instrument_analog_scaling_history",
        type_="unique",
    )
    op.drop_constraint(
        "ck_instrument_signal_acquisition_calibration_scope",
        "instrument_signal_acquisition_history",
        type_="check",
    )
    op.drop_constraint(
        "ck_instrument_signal_acquisition_profile_identity",
        "instrument_signal_acquisition_history",
        type_="check",
    )
    op.drop_column("instrument_signal_acquisition_history", "calibration_scope")
    op.drop_column(
        "instrument_signal_acquisition_history", "acquisition_profile_version"
    )
    op.drop_column("instrument_signal_acquisition_history", "acquisition_profile_id")
