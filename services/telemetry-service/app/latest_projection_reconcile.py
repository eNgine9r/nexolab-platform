from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text

from app.db import (
    TELEMETRY_HISTORY_ADVISORY_LOCK_ID,
    Database,
    TelemetryLatest,
    TelemetrySample,
)


LOGGER = logging.getLogger(__name__)
MAX_STARTUP_RECONCILE_ROWS = 10_000


def reconcile_latest_projection(
    database: Database,
    *,
    max_rows: int = MAX_STARTUP_RECONCILE_ROWS,
) -> int:
    """Reconcile only telemetry persisted after the migration backfill cutover.

    The migration is authoritative for the historical backfill. Startup owns only
    the bounded deployment gap between migration commit and replacement of the
    previous telemetry-service binary. A non-empty history with an empty latest
    projection is therefore treated as a failed/incomplete migration rather than
    silently rebuilding retained history during service startup.
    """

    if max_rows < 1:
        raise ValueError("max_rows must be positive")

    history = TelemetrySample.__table__
    latest = TelemetryLatest.__table__
    dialect = database.engine.dialect.name

    with database.engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": TELEMETRY_HISTORY_ADVISORY_LOCK_ID},
            )

        history_max_id = connection.execute(select(func.max(history.c.id))).scalar_one()
        if history_max_id is None:
            return 0

        latest_max_sample_id = connection.execute(
            select(func.max(latest.c.sample_id))
        ).scalar_one()
        if latest_max_sample_id is None:
            raise RuntimeError(
                "telemetry_latest is empty while telemetry history exists; "
                "run the latest-projection migration backfill before starting ingestion"
            )

        if int(latest_max_sample_id) >= int(history_max_id):
            return 0

        rows = (
            connection.execute(
                select(history)
                .where(history.c.id > int(latest_max_sample_id))
                .order_by(history.c.id.asc())
                .limit(max_rows + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) > max_rows:
            raise RuntimeError(
                "latest-projection startup reconciliation exceeds bounded deployment "
                f"gap ({max_rows} rows); investigate migration/cutover state"
            )

        for row in rows:
            raw_payload = row["raw_payload"]
            if not isinstance(raw_payload, dict):
                raw_payload = {}
            values: dict[str, Any] = {
                "event_id": row["event_id"],
                "node_id": row["node_id"],
                "captured_at": row["captured_at"],
                "metric": row["metric"],
                "value": row["value"],
                "unit": row["unit"],
                "quality": row["quality"],
                "source": row["source"],
                "equipment_id": row["equipment_id"],
                "channel_id": row["channel_id"],
                "alarm": row["alarm"],
                "raw_value": row["raw_value"],
                "raw_status": row["raw_status"],
            }
            latest_values = database._latest_values(
                values=values,
                sample_id=int(row["id"]),
                received_at=row["received_at"],
                raw_payload=raw_payload,
            )
            database._upsert_latest(
                connection,
                dialect=dialect,
                values=latest_values,
            )

    reconciled = len(rows)
    if reconciled:
        LOGGER.info(
            "Reconciled %s post-migration telemetry rows into telemetry_latest",
            reconciled,
        )
    return reconciled
