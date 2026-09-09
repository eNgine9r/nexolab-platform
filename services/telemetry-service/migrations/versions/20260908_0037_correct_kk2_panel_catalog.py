"""correct KK2 panel-backed sensor inventory

Revision ID: 20260908_0037
Revises: 20260907_0036
Create Date: 2026-09-08 10:45:00

The legacy KK2 catalog modelled every XJP60D input as two synthetic A/B
physical sensors.  Physical panel evidence establishes one physical sensor per
input.  Existing K101..K114 channel identities and telemetry keys remain
unchanged; only the synthetic physical-sensor projection is reconciled here.
K96..K100 are deliberately created by the normal climate-catalog seed that
runs immediately after ``alembic upgrade head`` so their IDs keep the same
repository UUIDv5 contract as a fresh installation.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260908_0037"
down_revision = "20260907_0036"
branch_labels = None
depends_on = None


_UPGRADE_PREFLIGHT = r"""
DO $nexolab$
DECLARE
    bad_count bigint;
BEGIN
    -- A partially populated legacy KK2 catalog is ambiguous.  Either there is
    -- no legacy catalog yet (fresh DB before seed) or every chamber carrying
    -- legacy KK2 channels must contain all 84 K101..K114 inputs.
    SELECT count(*) INTO bad_count
    FROM (
        SELECT cc.organization_id, cc.id
        FROM climate_chambers AS cc
        JOIN measurement_channels AS mc
          ON mc.organization_id = cc.organization_id
         AND mc.climate_chamber_id = cc.id
        JOIN measurement_devices AS md
          ON md.organization_id = mc.organization_id
         AND md.id = mc.device_id
        WHERE cc.code = 'KK2'
          AND md.device_type = 'temperature_controller'
          AND md.unit_id BETWEEN 101 AND 114
        GROUP BY cc.organization_id, cc.id
        HAVING count(*) <> 84
    ) AS partial_catalogs;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: legacy K101..K114 channel set is incomplete';
    END IF;

    SELECT count(*) INTO bad_count
    FROM measurement_channels AS mc
    JOIN climate_chambers AS cc
      ON cc.organization_id = mc.organization_id
     AND cc.id = mc.climate_chamber_id
    JOIN measurement_devices AS md
      ON md.organization_id = mc.organization_id
     AND md.id = mc.device_id
    WHERE cc.code = 'KK2'
      AND md.device_type = 'temperature_controller'
      AND md.unit_id BETWEEN 101 AND 114
      AND (
          mc.channel_number NOT BETWEEN 1 AND 6
          OR mc.channel_id <> lpad(md.unit_id::text, 3, '0') || '-' || lpad(mc.channel_number::text, 2, '0')
          OR mc.source_channel_id <> lpad(md.unit_id::text, 3, '0') || '-' || lpad(mc.channel_number::text, 2, '0')
          OR mc.logical_sensor_number <> 441 + (md.unit_id - 96) * 6 + (mc.channel_number - 1)
          OR mc.physical_sensor_count <> 2
      );
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: legacy channel identity/cardinality differs from expected #173 shape';
    END IF;

    -- Each legacy channel must still have one A and one B row.  The A row is
    -- retained (including operator-edited inventory and audit history) and its
    -- inventory is reconciled to panel truth.  The B row can be removed only
    -- while it remains an untouched synthetic projection.
    SELECT count(*) INTO bad_count
    FROM measurement_channels AS mc
    JOIN climate_chambers AS cc
      ON cc.organization_id = mc.organization_id
     AND cc.id = mc.climate_chamber_id
    JOIN measurement_devices AS md
      ON md.organization_id = mc.organization_id
     AND md.id = mc.device_id
    WHERE cc.code = 'KK2'
      AND md.device_type = 'temperature_controller'
      AND md.unit_id BETWEEN 101 AND 114
      AND (
          (SELECT count(*) FROM physical_sensors AS ps
             WHERE ps.organization_id = mc.organization_id
               AND ps.channel_id = mc.id) <> 2
          OR NOT EXISTS (
              SELECT 1 FROM physical_sensors AS ps
              WHERE ps.organization_id = mc.organization_id
                AND ps.channel_id = mc.id
                AND ps.sensor_position = 'A'
          )
          OR NOT EXISTS (
              SELECT 1 FROM physical_sensors AS ps
              WHERE ps.organization_id = mc.organization_id
                AND ps.channel_id = mc.id
                AND ps.sensor_position = 'B'
                AND ps.inventory_number = mc.logical_sensor_number::text || '-B'
                AND ps.serial_number IS NULL
                AND ps.calibration_status = 'untracked'
                AND ps.status = 'active'
                AND ps.version = 1
          )
      );
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: synthetic A/B sensor rows contain non-reconcilable state';
    END IF;

    SELECT count(*) INTO bad_count
    FROM equipment_discovery_candidates AS candidate
    JOIN physical_sensors AS ps
      ON candidate.linked_equipment_key = 'sensor:' || ps.id
    JOIN climate_chambers AS cc
      ON cc.organization_id = ps.organization_id
     AND cc.id = ps.climate_chamber_id
    JOIN measurement_channels AS mc
      ON mc.organization_id = ps.organization_id
     AND mc.id = ps.channel_id
    WHERE cc.code = 'KK2'
      AND ps.sensor_position = 'B'
      AND mc.logical_sensor_number BETWEEN 471 AND 554;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: a synthetic B sensor is referenced by equipment discovery';
    END IF;

    SELECT count(*) INTO bad_count
    FROM security_audit_events AS audit
    JOIN physical_sensors AS ps
      ON audit.organization_id = ps.organization_id
     AND audit.entity_id = ps.id
    JOIN climate_chambers AS cc
      ON cc.organization_id = ps.organization_id
     AND cc.id = ps.climate_chamber_id
    JOIN measurement_channels AS mc
      ON mc.organization_id = ps.organization_id
     AND mc.id = ps.channel_id
    WHERE cc.code = 'KK2'
      AND ps.sensor_position = 'B'
      AND mc.logical_sensor_number BETWEEN 471 AND 554;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: a synthetic B sensor has audit history';
    END IF;

    -- Numeric 441..554 inventory values are the target namespace.  Existing
    -- rows there would make a silent merge unsafe.  The legacy KK2 rows use
    -- -A/-B suffixes, while KK1 occupies 197..274.
    SELECT count(*) INTO bad_count
    FROM physical_sensors AS ps
    JOIN climate_chambers AS cc
      ON cc.organization_id = ps.organization_id
     AND cc.id = ps.climate_chamber_id
    WHERE cc.code <> 'KK2'
      AND ps.inventory_number ~ '^[0-9]+$'
      AND ps.inventory_number::integer BETWEEN 441 AND 554;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: physical inventory 441..554 conflicts with another chamber';
    END IF;

    -- K96..K100 are added by the normal seed.  Fail early if their stable
    -- business-key/unit/logical namespaces are already occupied elsewhere.
    SELECT count(*) INTO bad_count
    FROM climate_chambers AS kk2
    JOIN measurement_devices AS conflict
      ON conflict.organization_id = kk2.organization_id
     AND (
         conflict.business_key IN ('DIXELL-96','DIXELL-97','DIXELL-98','DIXELL-99','DIXELL-100')
         OR (conflict.bus_id = kk2.bus_id AND conflict.unit_id BETWEEN 96 AND 100)
     )
    WHERE kk2.code = 'KK2'
      AND conflict.climate_chamber_id <> kk2.id;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: K96..K100 device namespace is already occupied';
    END IF;

    SELECT count(*) INTO bad_count
    FROM climate_chambers AS kk2
    JOIN measurement_channels AS conflict
      ON conflict.organization_id = kk2.organization_id
     AND conflict.logical_sensor_number BETWEEN 441 AND 470
    WHERE kk2.code = 'KK2'
      AND conflict.climate_chamber_id <> kk2.id;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'KK2 catalog reconciliation refused: logical sensor namespace 441..470 is already occupied';
    END IF;
END
$nexolab$;
"""


_UPGRADE_RECONCILE = r"""
UPDATE physical_sensors AS ps
SET inventory_number = mc.logical_sensor_number::text,
    version = ps.version + 1,
    updated_at = CURRENT_TIMESTAMP
FROM measurement_channels AS mc,
     climate_chambers AS cc,
     measurement_devices AS md
WHERE ps.organization_id = mc.organization_id
  AND ps.channel_id = mc.id
  AND ps.sensor_position = 'A'
  AND cc.organization_id = mc.organization_id
  AND cc.id = mc.climate_chamber_id
  AND cc.code = 'KK2'
  AND md.organization_id = mc.organization_id
  AND md.id = mc.device_id
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;

DELETE FROM physical_sensors AS ps
USING measurement_channels AS mc,
      climate_chambers AS cc,
      measurement_devices AS md
WHERE ps.organization_id = mc.organization_id
  AND ps.channel_id = mc.id
  AND ps.sensor_position = 'B'
  AND cc.organization_id = mc.organization_id
  AND cc.id = mc.climate_chamber_id
  AND cc.code = 'KK2'
  AND md.organization_id = mc.organization_id
  AND md.id = mc.device_id
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;

UPDATE measurement_channels AS mc
SET physical_sensor_count = 1,
    updated_at = CURRENT_TIMESTAMP
FROM climate_chambers AS cc,
     measurement_devices AS md
WHERE cc.organization_id = mc.organization_id
  AND cc.id = mc.climate_chamber_id
  AND cc.code = 'KK2'
  AND md.organization_id = mc.organization_id
  AND md.id = mc.device_id
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;
"""


_DOWNGRADE_PREFLIGHT = r"""
DO $nexolab$
DECLARE
    bad_count bigint;
BEGIN
    -- The post-migration seed adds K96..K100.  A downgrade after that catalog
    -- has been exposed would require an explicit operator reconciliation; do
    -- not silently discard those new stable assets or their possible history.
    SELECT count(*) INTO bad_count
    FROM measurement_devices AS md
    JOIN climate_chambers AS cc
      ON cc.organization_id = md.organization_id
     AND cc.id = md.climate_chamber_id
    WHERE cc.code = 'KK2'
      AND md.device_type = 'temperature_controller'
      AND md.unit_id BETWEEN 96 AND 100;
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'cannot downgrade KK2 catalog correction after K96..K100 have been seeded';
    END IF;

    SELECT count(*) INTO bad_count
    FROM measurement_channels AS mc
    JOIN climate_chambers AS cc
      ON cc.organization_id = mc.organization_id
     AND cc.id = mc.climate_chamber_id
    JOIN measurement_devices AS md
      ON md.organization_id = mc.organization_id
     AND md.id = mc.device_id
    WHERE cc.code = 'KK2'
      AND md.device_type = 'temperature_controller'
      AND md.unit_id BETWEEN 101 AND 114
      AND (
          mc.physical_sensor_count <> 1
          OR NOT EXISTS (
              SELECT 1 FROM physical_sensors AS ps
              WHERE ps.organization_id = mc.organization_id
                AND ps.channel_id = mc.id
                AND ps.sensor_position = 'A'
                AND ps.inventory_number = mc.logical_sensor_number::text
          )
          OR (SELECT count(*) FROM physical_sensors AS ps
                WHERE ps.organization_id = mc.organization_id
                  AND ps.channel_id = mc.id) <> 1
      );
    IF bad_count <> 0 THEN
        RAISE EXCEPTION
            'cannot downgrade KK2 catalog correction after corrected sensor cardinality changed';
    END IF;
END
$nexolab$;
"""


_DOWNGRADE_RECONCILE = r"""
UPDATE physical_sensors AS ps
SET inventory_number = mc.logical_sensor_number::text || '-A',
    updated_at = CURRENT_TIMESTAMP
FROM measurement_channels AS mc,
     climate_chambers AS cc,
     measurement_devices AS md
WHERE ps.organization_id = mc.organization_id
  AND ps.channel_id = mc.id
  AND ps.sensor_position = 'A'
  AND cc.organization_id = mc.organization_id
  AND cc.id = mc.climate_chamber_id
  AND cc.code = 'KK2'
  AND md.organization_id = mc.organization_id
  AND md.id = mc.device_id
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;

UPDATE measurement_channels AS mc
SET physical_sensor_count = 2,
    updated_at = CURRENT_TIMESTAMP
FROM climate_chambers AS cc,
     measurement_devices AS md
WHERE cc.organization_id = mc.organization_id
  AND cc.id = mc.climate_chamber_id
  AND cc.code = 'KK2'
  AND md.organization_id = mc.organization_id
  AND md.id = mc.device_id
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;

-- Recreate the purely synthetic B projection.  Upgrade proved that these rows
-- had no metadata, audit history or discovery references before removal.  A
-- deterministic migration-only ID is sufficient because no surviving object
-- can reference the deleted legacy B IDs.
INSERT INTO physical_sensors (
    id,
    organization_id,
    climate_chamber_id,
    channel_id,
    sensor_position,
    inventory_number,
    serial_number,
    calibration_status,
    status,
    version,
    created_at,
    updated_at
)
SELECT
    substr(md5('nexolab-0037-downgrade:' || mc.organization_id || ':' || mc.logical_sensor_number::text), 1, 8)
    || '-' || substr(md5('nexolab-0037-downgrade:' || mc.organization_id || ':' || mc.logical_sensor_number::text), 9, 4)
    || '-' || substr(md5('nexolab-0037-downgrade:' || mc.organization_id || ':' || mc.logical_sensor_number::text), 13, 4)
    || '-' || substr(md5('nexolab-0037-downgrade:' || mc.organization_id || ':' || mc.logical_sensor_number::text), 17, 4)
    || '-' || substr(md5('nexolab-0037-downgrade:' || mc.organization_id || ':' || mc.logical_sensor_number::text), 21, 12),
    mc.organization_id,
    mc.climate_chamber_id,
    mc.id,
    'B',
    mc.logical_sensor_number::text || '-B',
    NULL,
    'untracked',
    'active',
    1,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM measurement_channels AS mc
JOIN climate_chambers AS cc
  ON cc.organization_id = mc.organization_id
 AND cc.id = mc.climate_chamber_id
JOIN measurement_devices AS md
  ON md.organization_id = mc.organization_id
 AND md.id = mc.device_id
WHERE cc.code = 'KK2'
  AND md.device_type = 'temperature_controller'
  AND md.unit_id BETWEEN 101 AND 114;
"""


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("KK2 catalog correction migration requires PostgreSQL")


def upgrade() -> None:
    _require_postgresql()
    # SQL-only reconciliation keeps `alembic upgrade head --sql` renderable.
    op.execute(sa.text(_UPGRADE_PREFLIGHT))
    op.execute(sa.text(_UPGRADE_RECONCILE))


def downgrade() -> None:
    _require_postgresql()
    op.execute(sa.text(_DOWNGRADE_PREFLIGHT))
    op.execute(sa.text(_DOWNGRADE_RECONCILE))
