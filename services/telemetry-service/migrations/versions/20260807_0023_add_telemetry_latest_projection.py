"""Add durable latest telemetry projection.

Revision ID: 20260807_0023
Revises: 20260805_0022
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_0023"
down_revision: str | None = "20260805_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TELEMETRY_HISTORY_ADVISORY_LOCK_ID = 263_000_001

_POSTGRES_LATEST_COLUMNS = """
    sample_id,
    event_id,
    node_id,
    captured_at,
    metric,
    value,
    unit,
    quality,
    source,
    equipment_id,
    channel_id,
    alarm,
    raw_value,
    raw_status,
    stale_after_seconds,
    received_at
"""

_POSTGRES_LATEST_SELECT = """
    sample.id AS sample_id,
    sample.event_id,
    sample.node_id,
    sample.captured_at,
    sample.metric,
    sample.value,
    sample.unit,
    sample.quality,
    sample.source,
    sample.equipment_id,
    sample.channel_id,
    sample.alarm,
    sample.raw_value,
    sample.raw_status,
    CASE
        WHEN json_typeof(sample.raw_payload -> 'stale_after_seconds') = 'number'
             AND (sample.raw_payload ->> 'stale_after_seconds')::double precision > 0
        THEN (sample.raw_payload ->> 'stale_after_seconds')::double precision
        ELSE NULL
    END AS stale_after_seconds,
    sample.received_at
"""

_POSTGRES_UPSERT = """
ON CONFLICT (node_id, equipment_id, channel_id, metric)
DO UPDATE SET
    sample_id = EXCLUDED.sample_id,
    event_id = EXCLUDED.event_id,
    captured_at = EXCLUDED.captured_at,
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    quality = EXCLUDED.quality,
    source = EXCLUDED.source,
    alarm = EXCLUDED.alarm,
    raw_value = EXCLUDED.raw_value,
    raw_status = EXCLUDED.raw_status,
    stale_after_seconds = EXCLUDED.stale_after_seconds,
    received_at = EXCLUDED.received_at
WHERE
    EXCLUDED.captured_at > telemetry_latest.captured_at
    OR (
        EXCLUDED.captured_at = telemetry_latest.captured_at
        AND EXCLUDED.sample_id > telemetry_latest.sample_id
    )
"""


def _upgrade_postgresql() -> None:
    # Capture the current end of immutable history before the long read phase.
    # Old service instances may continue ingesting while the initial projection
    # is built; the final catch-up below covers every row committed afterwards.
    op.execute(
        """
        CREATE TEMPORARY TABLE telemetry_latest_backfill_watermark
        ON COMMIT DROP
        AS
        SELECT COALESCE(MAX(id), 0)::bigint AS sample_id
        FROM telemetry_samples
        """
    )

    # Build the bulk projection without taking the ingestion advisory lock.
    # The existing ix_telemetry_latest_lookup index starts with the canonical
    # series columns, so DISTINCT ON can enumerate series without carrying the
    # 1+ GB wide telemetry rows through a full-history window sort. The lateral
    # lookup fetches only one full row per canonical series.
    op.execute(
        sa.text(
            f"""
            INSERT INTO telemetry_latest ({_POSTGRES_LATEST_COLUMNS})
            SELECT
                {_POSTGRES_LATEST_SELECT}
            FROM (
                SELECT DISTINCT ON (
                    node_id,
                    equipment_id,
                    channel_id,
                    metric
                )
                    node_id,
                    equipment_id,
                    channel_id,
                    metric
                FROM telemetry_samples
                ORDER BY
                    node_id,
                    equipment_id,
                    channel_id,
                    metric
            ) AS series
            CROSS JOIN LATERAL (
                SELECT candidate.*
                FROM telemetry_samples AS candidate
                WHERE candidate.node_id = series.node_id
                  AND candidate.equipment_id = series.equipment_id
                  AND candidate.channel_id = series.channel_id
                  AND candidate.metric = series.metric
                ORDER BY candidate.captured_at DESC, candidate.id DESC
                LIMIT 1
            ) AS sample
            {_POSTGRES_UPSERT}
            """
        )
    )

    # Only the cutover is serialized. Once this exclusive lock is granted,
    # every old-writer transaction that previously held the shared lock has
    # committed. No new old-writer transaction can enter until this migration
    # commits, so a small id-bounded catch-up closes the race deterministically.
    op.execute(
        f"SELECT pg_advisory_xact_lock({TELEMETRY_HISTORY_ADVISORY_LOCK_ID})"
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO telemetry_latest ({_POSTGRES_LATEST_COLUMNS})
            SELECT
                {_POSTGRES_LATEST_SELECT}
            FROM (
                SELECT DISTINCT ON (
                    node_id,
                    equipment_id,
                    channel_id,
                    metric
                )
                    candidate.*
                FROM telemetry_samples AS candidate
                WHERE candidate.id > (
                    SELECT sample_id
                    FROM telemetry_latest_backfill_watermark
                )
                ORDER BY
                    node_id,
                    equipment_id,
                    channel_id,
                    metric,
                    captured_at DESC,
                    id DESC
            ) AS sample
            {_POSTGRES_UPSERT}
            """
        )
    )


def _upgrade_sqlite() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO telemetry_latest (
                sample_id,
                event_id,
                node_id,
                captured_at,
                metric,
                value,
                unit,
                quality,
                source,
                equipment_id,
                channel_id,
                alarm,
                raw_value,
                raw_status,
                stale_after_seconds,
                received_at
            )
            SELECT
                sample_id,
                event_id,
                node_id,
                captured_at,
                metric,
                value,
                unit,
                quality,
                source,
                equipment_id,
                channel_id,
                alarm,
                raw_value,
                raw_status,
                CASE
                    WHEN json_type(raw_payload, '$.stale_after_seconds')
                         IN ('integer', 'real')
                         AND CAST(
                             json_extract(
                                 raw_payload,
                                 '$.stale_after_seconds'
                             ) AS REAL
                         ) > 0
                    THEN CAST(
                        json_extract(
                            raw_payload,
                            '$.stale_after_seconds'
                        ) AS REAL
                    )
                    ELSE NULL
                END,
                received_at
            FROM (
                SELECT
                    id AS sample_id,
                    event_id,
                    node_id,
                    captured_at,
                    metric,
                    value,
                    unit,
                    quality,
                    source,
                    equipment_id,
                    channel_id,
                    alarm,
                    raw_value,
                    raw_status,
                    raw_payload,
                    received_at,
                    row_number() OVER (
                        PARTITION BY node_id, equipment_id, channel_id, metric
                        ORDER BY captured_at DESC, id DESC
                    ) AS sample_rank
                FROM telemetry_samples
            ) AS ranked
            WHERE sample_rank = 1
            """
        )
    )


def _upgrade_fallback() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO telemetry_latest (
                sample_id,
                event_id,
                node_id,
                captured_at,
                metric,
                value,
                unit,
                quality,
                source,
                equipment_id,
                channel_id,
                alarm,
                raw_value,
                raw_status,
                stale_after_seconds,
                received_at
            )
            SELECT
                sample_id,
                event_id,
                node_id,
                captured_at,
                metric,
                value,
                unit,
                quality,
                source,
                equipment_id,
                channel_id,
                alarm,
                raw_value,
                raw_status,
                NULL,
                received_at
            FROM (
                SELECT
                    id AS sample_id,
                    event_id,
                    node_id,
                    captured_at,
                    metric,
                    value,
                    unit,
                    quality,
                    source,
                    equipment_id,
                    channel_id,
                    alarm,
                    raw_value,
                    raw_status,
                    received_at,
                    row_number() OVER (
                        PARTITION BY node_id, equipment_id, channel_id, metric
                        ORDER BY captured_at DESC, id DESC
                    ) AS sample_rank
                FROM telemetry_samples
            ) AS ranked
            WHERE sample_rank = 1
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "telemetry_latest",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sample_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("alarm", sa.String(length=32), nullable=True),
        sa.Column("raw_value", sa.BigInteger(), nullable=True),
        sa.Column("raw_status", sa.BigInteger(), nullable=True),
        sa.Column("stale_after_seconds", sa.Float(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_telemetry_latest_series",
        "telemetry_latest",
        ["node_id", "equipment_id", "channel_id", "metric"],
        unique=True,
    )
    op.create_index(
        "ix_telemetry_latest_order",
        "telemetry_latest",
        ["captured_at", "event_id"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_latest_filters",
        "telemetry_latest",
        ["quality", "alarm", "captured_at", "event_id"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _upgrade_postgresql()
    elif bind.dialect.name == "sqlite":
        _upgrade_sqlite()
    else:
        _upgrade_fallback()


def downgrade() -> None:
    op.drop_index("ix_telemetry_latest_filters", table_name="telemetry_latest")
    op.drop_index("ix_telemetry_latest_order", table_name="telemetry_latest")
    op.drop_index("uq_telemetry_latest_series", table_name="telemetry_latest")
    op.drop_table("telemetry_latest")
