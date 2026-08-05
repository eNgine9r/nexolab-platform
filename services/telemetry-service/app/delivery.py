from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from app.db import Database, TelemetryQuery, TelemetrySample

StalenessState = Literal["fresh", "stale", "unknown"]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | str) -> datetime:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stale_after_seconds(payload: dict[str, Any]) -> float | None:
    value = payload.get("stale_after_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if resolved > 0 else None


class PersistedTelemetryProjection:
    """Adds truthful delivery metadata without influencing acquisition cadence."""

    def __init__(self, *, clock: Clock = _utc_now) -> None:
        self._clock = clock

    def project(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        projected = dict(payload)
        observed_at = _as_utc(self._clock())
        captured_at = _as_utc(str(projected["captured_at"]))
        age_seconds = max(0.0, (observed_at - captured_at).total_seconds())
        stale_after_seconds = _stale_after_seconds(projected)

        if stale_after_seconds is None:
            is_stale: bool | None = None
            staleness: StalenessState = "unknown"
        else:
            is_stale = age_seconds > stale_after_seconds
            staleness = "stale" if is_stale else "fresh"

        resolved_received_at = (
            _as_utc(received_at) if received_at is not None else observed_at
        )
        projected.update(
            received_at=resolved_received_at.isoformat(),
            age_seconds=round(age_seconds, 6),
            stale_after_seconds=stale_after_seconds,
            is_stale=is_stale,
            staleness=staleness,
            state_source="persisted",
        )
        return projected


class PersistedTelemetryReadModel:
    """Read-only REST/WebSocket view over committed telemetry rows."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._database = database
        self._projection = PersistedTelemetryProjection(clock=clock)

    def _project_sample(self, sample: TelemetrySample) -> dict[str, Any]:
        payload = dict(sample.raw_payload)
        payload.update(
            {
                "event_id": sample.event_id,
                "node_id": sample.node_id,
                "captured_at": sample.captured_at.isoformat(),
                "metric": sample.metric,
                "value": sample.value,
                "unit": sample.unit,
                "quality": sample.quality,
                "source": sample.source,
                "equipment_id": sample.equipment_id,
                "channel_id": sample.channel_id,
                "alarm": sample.alarm,
                "raw_value": sample.raw_value,
                "raw_status": sample.raw_status,
            }
        )
        return self._projection.project(payload, received_at=sample.received_at)

    def latest_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = self._database.latest_samples(
            query=query,
            limit=limit,
            offset=offset,
        )
        return [self._project_sample(row) for row in rows]

    def history_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = self._database.history_samples(
            query=query,
            limit=limit,
            offset=offset,
        )
        return [self._project_sample(row) for row in rows]

    def history_snapshot_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
        snapshot_at: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], datetime]:
        rows, resolved_snapshot_at = self._database.history_snapshot_samples(
            query=query,
            limit=limit,
            offset=offset,
            snapshot_at=snapshot_at,
        )
        return (
            [self._project_sample(row) for row in rows],
            resolved_snapshot_at,
        )
