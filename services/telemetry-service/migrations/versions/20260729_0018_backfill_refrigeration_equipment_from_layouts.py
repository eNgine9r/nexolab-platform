"""backfill refrigeration equipment passports from existing layouts

Revision ID: 20260729_0018
Revises: 20260729_0017
Create Date: 2026-07-29 11:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260729_0018"
down_revision = "20260729_0017"
branch_labels = None
depends_on = None

_BACKFILL_ACTOR = "migration-layout-backfill"
_TRIGGER_ACTOR = "layout-draft-compatibility"
_TRIGGER_NAME = "trg_refrigeration_layout_ensure_equipment"
_FUNCTION_NAME = "nexolab_ensure_refrigeration_equipment_for_layout"


def upgrade() -> None:
    connection = op.get_bind()
    _reject_oversized_legacy_ids(connection)
    _backfill_existing_layouts(connection)
    _install_layout_equipment_invariant()


def _reject_oversized_legacy_ids(connection: sa.Connection) -> None:
    oversized = connection.execute(
        sa.text(
            """
            SELECT organization_id, equipment_id
            FROM refrigeration_layout_drafts AS draft
            WHERE length(draft.equipment_id) > 36
              AND NOT EXISTS (
                SELECT 1
                FROM refrigeration_equipment AS equipment
                WHERE equipment.organization_id = draft.organization_id
                  AND equipment.id = draft.equipment_id
              )
            ORDER BY organization_id, equipment_id
            LIMIT 1
            """
        )
    ).mappings().first()
    if oversized is not None:
        raise RuntimeError(
            "cannot backfill refrigeration equipment passport for legacy equipment id "
            f"{oversized['equipment_id']!r} in organization {oversized['organization_id']!r}: "
            "the catalog identifier limit is 36 characters"
        )


def _backfill_existing_layouts(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO refrigeration_equipment (
                id,
                organization_id,
                code,
                name,
                location,
                equipment_type,
                manufacturer,
                model,
                serial_number,
                temperature_class,
                installed_at,
                serviced_at,
                status,
                average_temperature_c,
                min_temperature_c,
                max_temperature_c,
                online_sensors,
                total_sensors,
                active_alarms,
                last_seen_at,
                version,
                created_by,
                created_at,
                updated_at,
                deleted_by,
                deleted_at
            )
            SELECT
                draft.equipment_id,
                draft.organization_id,
                'LEGACY-' || upper(md5(draft.organization_id || ':' || draft.equipment_id)),
                'Imported equipment ' || draft.equipment_id,
                'Imported from existing layout',
                'Холодильне обладнання',
                'Unknown',
                'Unknown',
                'UNKNOWN-' || upper(substr(md5(draft.organization_id || ':' || draft.equipment_id), 1, 16)),
                'Not specified',
                NULL,
                NULL,
                'offline',
                0,
                0,
                0,
                0,
                0,
                0,
                NULL,
                1,
                :backfill_actor,
                min(draft.created_at),
                max(draft.updated_at),
                NULL,
                NULL
            FROM refrigeration_layout_drafts AS draft
            WHERE NOT EXISTS (
                SELECT 1
                FROM refrigeration_equipment AS equipment
                WHERE equipment.organization_id = draft.organization_id
                  AND equipment.id = draft.equipment_id
            )
            GROUP BY draft.organization_id, draft.equipment_id
            """
        ),
        {"backfill_actor": _BACKFILL_ACTOR},
    )


def _install_layout_equipment_invariant() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_FUNCTION_NAME}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF length(NEW.equipment_id) > 36 THEN
                    RAISE EXCEPTION
                        'equipment id % exceeds refrigeration catalog limit of 36 characters',
                        NEW.equipment_id;
                END IF;

                INSERT INTO refrigeration_equipment (
                    id,
                    organization_id,
                    code,
                    name,
                    location,
                    equipment_type,
                    manufacturer,
                    model,
                    serial_number,
                    temperature_class,
                    installed_at,
                    serviced_at,
                    status,
                    average_temperature_c,
                    min_temperature_c,
                    max_temperature_c,
                    online_sensors,
                    total_sensors,
                    active_alarms,
                    last_seen_at,
                    version,
                    created_by,
                    created_at,
                    updated_at,
                    deleted_by,
                    deleted_at
                ) VALUES (
                    NEW.equipment_id,
                    NEW.organization_id,
                    'LEGACY-' || upper(md5(NEW.organization_id || ':' || NEW.equipment_id)),
                    'Imported equipment ' || NEW.equipment_id,
                    'Imported from existing layout',
                    'Холодильне обладнання',
                    'Unknown',
                    'Unknown',
                    'UNKNOWN-' || upper(substr(md5(NEW.organization_id || ':' || NEW.equipment_id), 1, 16)),
                    'Not specified',
                    NULL,
                    NULL,
                    'offline',
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    NULL,
                    1,
                    '{_TRIGGER_ACTOR}',
                    coalesce(NEW.created_at, CURRENT_TIMESTAMP),
                    coalesce(NEW.updated_at, CURRENT_TIMESTAMP),
                    NULL,
                    NULL
                )
                ON CONFLICT (id) DO NOTHING;

                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_TRIGGER_NAME}
            BEFORE INSERT OR UPDATE OF organization_id, equipment_id
            ON refrigeration_layout_drafts
            FOR EACH ROW
            EXECUTE FUNCTION {_FUNCTION_NAME}()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON refrigeration_layout_drafts"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()"))
    op.execute(
        sa.text(
            """
            DELETE FROM refrigeration_equipment
            WHERE created_by IN (:backfill_actor, :trigger_actor)
            """
        ).bindparams(
            backfill_actor=_BACKFILL_ACTOR,
            trigger_actor=_TRIGGER_ACTOR,
        )
    )
