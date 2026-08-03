from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.contracts import Alarm, Quality
from app.db import Database, TelemetryQuery
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


class TelemetrySampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class TelemetryCollectionResponse(BaseModel):
    items: list[TelemetrySampleResponse]
    count: int
    limit: int
    offset: int
    next_offset: int | None
    snapshot_at: datetime | None = None


def _collection(
    rows: list[object],
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
        rows = database.latest_samples(
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
        rows, resolved_snapshot_at = database.history_snapshot_samples(
            query=query,
            limit=limit + 1,
            offset=offset,
            snapshot_at=snapshot_at,
        )
        return _collection(
            rows,
            limit=limit,
            offset=offset,
            snapshot_at=resolved_snapshot_at,
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
