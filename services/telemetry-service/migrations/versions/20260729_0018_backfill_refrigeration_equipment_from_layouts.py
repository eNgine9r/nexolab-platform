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


def upgrade() -> None:
    connection = op.get_bind()
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


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM refrigeration_equipment
            WHERE created_by = :backfill_actor
            """
        ).bindparams(backfill_actor=_BACKFILL_ACTOR)
    )
