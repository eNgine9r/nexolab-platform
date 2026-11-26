from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.contracts import Alarm, Quality
from app.db import Database, HistoryCapacityError, TelemetryQuery
from app.history_aggregate import (
    MAX_AGGREGATE_BUCKETS,
    MAX_AGGREGATE_SERIES,
    SeriesAggregate,
    SeriesKey,
    aggregate_history,
    bucket_width_ms,
    epoch_ms,
)
from app.delivery import PersistedTelemetryReadModel, StalenessState
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


class TelemetrySampleResponse(BaseModel):
    event_id: str
    node_id: str
    captured_at: datetime
    metric: str
    value: float | None
    unit: str
    quality: Quality
    source: str
    equipment_id: str
    channel_id: str
    alarm: Alarm | None
    raw_value: int | None
    raw_status: int | None
    received_at: datetime
    age_seconds: float
    stale_after_seconds: float | None
    is_stale: bool | None
    staleness: StalenessState
    state_source: Literal["persisted"]


class TelemetryCollectionResponse(BaseModel):
    items: list[TelemetrySampleResponse]
    count: int
    limit: int
    offset: int
    next_offset: int | None
    snapshot_at: datetime | None = None


class HistoryIntervalStatisticsResponse(BaseModel):
    """Exact interval statistics from original rows (#1813), same semantics as the browser."""

    valid_count: int
    invalid_count: int
    minimum: float | None
    maximum: float | None
    valid_sum: float
    first_valid_ms: int | None
    last_valid_ms: int | None
    median_spacing_ms: float | None
    gap_count: int
    gap_total_ms: int
    gap_longest_ms: int


class HistoryAggregateSeriesResponse(BaseModel):
    """One series of `GET /history/aggregate` (#1811).

    `raw` rows: [captured_ms, value, quality, alarm, event_id].
    `buckets` rows: [index, count, valid_count, invalid_count, first_invalid_ms, last_invalid_ms,
    first_ms, first_value, last_ms, last_value, min_ms, min_value, max_ms, max_value, valid_sum].
    Whole-window statistics come from the original rows, never from display points.
    """

    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    unit: str | None
    mode: Literal["raw", "aggregate"]
    count: int
    valid_count: int
    minimum: float | None
    maximum: float | None
    average: float | None
    first_ms: int | None
    last_ms: int | None
    raw: list[tuple[int, float | None, str, str | None, str]] | None = None
    buckets: list[list[int | float | None]] | None = None
    statistics: HistoryIntervalStatisticsResponse | None = None


class HistoryAggregateResponse(BaseModel):
    from_ms: int
    to_ms: int
    bucket_ms: int
    bucket_count: int
    snapshot_at: datetime
    series: list[HistoryAggregateSeriesResponse]


def _aggregate_series_response(item: SeriesAggregate) -> HistoryAggregateSeriesResponse:
    def pair(value: tuple[int, float] | None) -> list[int | float | None]:
        return [None, None] if value is None else [value[0], value[1]]

    return HistoryAggregateSeriesResponse(
        node_id=item.key.node_id,
        equipment_id=item.key.equipment_id,
        channel_id=item.key.channel_id,
        metric=item.key.metric,
        unit=item.unit,
        mode=item.mode,  # type: ignore[arg-type]
        count=item.count,
        valid_count=item.valid_count,
        minimum=item.minimum,
        maximum=item.maximum,
        average=item.average,
        first_ms=item.first_ms,
        last_ms=item.last_ms,
        statistics=(
            None
            if item.statistics is None
            else HistoryIntervalStatisticsResponse(**dataclasses.asdict(item.statistics))
        ),
        raw=item.raw if item.mode == "raw" else None,
        buckets=(
            [
                [
                    bucket.index,
                    bucket.count,
                    bucket.valid_count,
                    bucket.invalid_count,
                    bucket.first_invalid_ms,
                    bucket.last_invalid_ms,
                    *pair(bucket.first),
                    *pair(bucket.last),
                    *pair(bucket.minimum),
                    *pair(bucket.maximum),
                    bucket.total if bucket.valid_count else None,
                ]
                for bucket in item.buckets
            ]
            if item.mode == "aggregate"
            else None
        ),
    )


def _collection(
    rows: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
    snapshot_at: datetime | None = None,
) -> TelemetryCollectionResponse:
    has_more = len(rows) > limit
    page = rows[:limit]
    return TelemetryCollectionResponse(
        items=[TelemetrySampleResponse.model_validate(item) for item in page],
        count=len(page),
        limit=limit,
        offset=offset,
        next_offset=offset + limit if has_more else None,
        snapshot_at=snapshot_at,
    )


def create_api_router(
    database: Database,
    *,
    max_history_days: int,
    max_page_size: int,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
    read_access = _read_access_dependency(security_dependencies)
    read_model = PersistedTelemetryReadModel(database)

    def validate_limit(limit: int) -> None:
        if limit > max_page_size:
            raise HTTPException(
                status_code=422,
                detail=f"limit must not exceed {max_page_size}",
            )

    @router.get("/latest", response_model=TelemetryCollectionResponse)
    def latest(
        _authorized: AuthorizedRequest = Depends(read_access),
        node_id: str | None = None,
        equipment_id: str | None = None,
        channel_id: str | None = None,
        metric: str | None = None,
        quality: Quality | None = None,
        alarm: Alarm | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TelemetryCollectionResponse:
        validate_limit(limit)
        query = TelemetryQuery(
            node_id=node_id,
            equipment_id=equipment_id,
            channel_id=channel_id,
            metric=metric,
            quality=quality,
            alarm=alarm,
        )
        rows = read_model.latest_samples(
            query=query,
            limit=limit + 1,
            offset=offset,
        )
        return _collection(rows, limit=limit, offset=offset)

    @router.get("/history", response_model=TelemetryCollectionResponse)
    def history(
        from_at: Annotated[datetime, Query(alias="from")],
        to_at: Annotated[datetime, Query(alias="to")],
        _authorized: AuthorizedRequest = Depends(read_access),
        node_id: str | None = None,
        equipment_id: str | None = None,
        channel_id: str | None = None,
        metric: str | None = None,
        quality: Quality | None = None,
        alarm: Alarm | None = None,
        snapshot_at: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TelemetryCollectionResponse:
        validate_limit(limit)
        if from_at.tzinfo is None or to_at.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="from and to must be timezone-aware timestamps",
            )
        if snapshot_at is not None and snapshot_at.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="snapshot_at must be a timezone-aware timestamp",
            )
        if from_at >= to_at:
            raise HTTPException(status_code=422, detail="from must be earlier than to")
        if to_at - from_at > timedelta(days=max_history_days):
            raise HTTPException(
                status_code=422,
                detail=f"history range must not exceed {max_history_days} days",
            )

        query = TelemetryQuery(
            node_id=node_id,
            equipment_id=equipment_id,
            channel_id=channel_id,
            metric=metric,
            quality=quality,
            alarm=alarm,
            from_at=from_at,
            to_at=to_at,
        )
        try:
            rows, resolved_snapshot_at = read_model.history_snapshot_samples(
                query=query,
                limit=limit + 1,
                offset=offset,
                snapshot_at=snapshot_at,
            )
        except HistoryCapacityError as error:
            # #1807: fail fast inside the browser's request budget instead of queueing for a
            # pooled connection; the client retries this page under the same snapshot.
            raise HTTPException(
                status_code=503,
                detail=str(error),
                headers={"Retry-After": "1"},
            ) from error
        return _collection(
            rows,
            limit=limit,
            offset=offset,
            snapshot_at=resolved_snapshot_at,
        )

    @router.get("/history/aggregate", response_model=HistoryAggregateResponse)
    def history_aggregate(
        from_at: Annotated[datetime, Query(alias="from")],
        to_at: Annotated[datetime, Query(alias="to")],
        series: Annotated[list[str], Query(min_length=1, max_length=MAX_AGGREGATE_SERIES)],
        _authorized: AuthorizedRequest = Depends(read_access),
        buckets: Annotated[int, Query(ge=1, le=MAX_AGGREGATE_BUCKETS)] = 240,
        snapshot_at: datetime | None = None,
        statistics: bool = False,
    ) -> HistoryAggregateResponse:
        """Extremum-preserving history for up to 24 series in one request (#1811)."""
        if from_at.tzinfo is None or to_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="from and to must be timezone-aware timestamps")
        if snapshot_at is not None and snapshot_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="snapshot_at must be a timezone-aware timestamp")
        if from_at >= to_at:
            raise HTTPException(status_code=422, detail="from must be earlier than to")
        if to_at - from_at > timedelta(days=max_history_days):
            raise HTTPException(
                status_code=422,
                detail=f"history range must not exceed {max_history_days} days",
            )
        try:
            keys = list(dict.fromkeys(SeriesKey.parse(value) for value in series))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            results, resolved_snapshot_at = aggregate_history(
                database,
                keys,
                from_at=from_at,
                to_at=to_at,
                buckets=buckets,
                snapshot_at=snapshot_at,
                statistics=statistics,
            )
        except HistoryCapacityError as error:
            raise HTTPException(
                status_code=503,
                detail=str(error),
                headers={"Retry-After": "1"},
            ) from error
        from_ms = epoch_ms(from_at)
        to_ms = epoch_ms(to_at)
        return HistoryAggregateResponse(
            from_ms=from_ms,
            to_ms=to_ms,
            bucket_ms=bucket_width_ms(from_ms, to_ms, buckets),
            bucket_count=buckets,
            snapshot_at=resolved_snapshot_at,
            series=[_aggregate_series_response(item) for item in results],
        )

    return router


def _read_access_dependency(
    security_dependencies: SecurityDependencies | None,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(Permission.READ_TELEMETRY)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id="00000000-0000-0000-0000-000000000001",
                roles=frozenset({Role.ADMINISTRATOR}),
                provider="disabled",
            ),
        )

    return development_access
