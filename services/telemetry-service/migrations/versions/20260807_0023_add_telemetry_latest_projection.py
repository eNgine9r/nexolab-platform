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
                        WHEN json_typeof(raw_payload -> 'stale_after_seconds') = 'number'
                             AND (raw_payload ->> 'stale_after_seconds')::double precision > 0
                        THEN (raw_payload ->> 'stale_after_seconds')::double precision
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
    elif bind.dialect.name == "sqlite":
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
    else:
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


def downgrade() -> None:
    op.drop_index("ix_telemetry_latest_filters", table_name="telemetry_latest")
    op.drop_index("ix_telemetry_latest_order", table_name="telemetry_latest")
    op.drop_index("uq_telemetry_latest_series", table_name="telemetry_latest")
    op.drop_table("telemetry_latest")
