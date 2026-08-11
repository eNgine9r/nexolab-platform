from __future__ import annotations

from datetime import UTC, datetime
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


def _normalized_datetime_pair(
    existing: datetime,
    incoming: datetime,
) -> tuple[datetime, datetime]:
    if existing.tzinfo is None and incoming.tzinfo is not None:
        existing = existing.replace(tzinfo=UTC)
    if incoming.tzinfo is None and existing.tzinfo is not None:
        incoming = incoming.replace(tzinfo=UTC)
    return existing, incoming


def _would_advance_latest(
    connection: Any,
    *,
    latest: Any,
    row: Any,
) -> bool:
    existing = connection.execute(
        select(latest.c.captured_at, latest.c.sample_id).where(
            latest.c.node_id == row["node_id"],
            latest.c.equipment_id == row["equipment_id"],
            latest.c.channel_id == row["channel_id"],
            latest.c.metric == row["metric"],
        )
    ).first()
    if existing is None:
        return True

    existing_captured_at, incoming_captured_at = _normalized_datetime_pair(
        existing.captured_at,
        row["captured_at"],
    )
    return incoming_captured_at > existing_captured_at or (
        incoming_captured_at == existing_captured_at
        and int(row["id"]) > int(existing.sample_id)
    )


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

    The return value is the number of latest-projection mutations applied, not the
    number of history rows inspected. Delayed older rows are intentionally scanned
    within the bounded deployment gap but do not count as reconciled again when
    they cannot advance canonical latest state.
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

        reconciled = 0
        for row in rows:
            will_advance = _would_advance_latest(
                connection,
                latest=latest,
                row=row,
            )
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
            if will_advance:
                reconciled += 1

    if reconciled:
        LOGGER.info(
            "Reconciled %s post-migration telemetry rows into telemetry_latest",
            reconciled,
        )
    return reconciled
