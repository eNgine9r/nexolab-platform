from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.contracts import Alarm, Quality
from app.sessions.telemetry_attribution import (
    SessionAwareDatabase,
    SessionTelemetryQuery,
)


class AttributedTelemetrySampleResponse(BaseModel):
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
    session_id: str
    stage_id: str | None
    binding_id: str
    config_snapshot_id: str
    resolver_version: str


class AttributedTelemetryCollectionResponse(BaseModel):
    items: list[AttributedTelemetrySampleResponse]
    count: int
    limit: int
    offset: int
    next_offset: int | None


def _collection(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
) -> AttributedTelemetryCollectionResponse:
    has_more = len(rows) > limit
    page = rows[:limit]
    return AttributedTelemetryCollectionResponse(
        items=[AttributedTelemetrySampleResponse.model_validate(item) for item in page],
        count=len(page),
        limit=limit,
        offset=offset,
        next_offset=offset + limit if has_more else None,
    )


def create_session_telemetry_router(
    database: SessionAwareDatabase,
    *,
    max_history_days: int,
    max_page_size: int,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/sessions/{session_id}/telemetry",
        tags=["session-telemetry"],
    )

    def require_session(session_id: str) -> None:
        if not database.session_exists(session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "session_not_found",
                    "message": f"session {session_id!r} was not found",
                },
            )

    def validate_limit(limit: int) -> None:
        if limit > max_page_size:
            raise HTTPException(
                status_code=422,
                detail=f"limit must not exceed {max_page_size}",
            )

    @router.get("/latest", response_model=AttributedTelemetryCollectionResponse)
    def latest(
        session_id: str,
        stage_id: str | None = None,
        node_id: str | None = None,
        equipment_id: str | None = None,
        channel_id: str | None = None,
        metric: str | None = None,
        quality: Quality | None = None,
        alarm: Alarm | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AttributedTelemetryCollectionResponse:
        require_session(session_id)
        validate_limit(limit)
        rows = database.session_latest_samples(
            session_id=session_id,
            query=SessionTelemetryQuery(
                stage_id=stage_id,
                node_id=node_id,
                equipment_id=equipment_id,
                channel_id=channel_id,
                metric=metric,
                quality=quality,
                alarm=alarm,
            ),
            limit=limit + 1,
            offset=offset,
        )
        return _collection(rows, limit=limit, offset=offset)

    @router.get("/history", response_model=AttributedTelemetryCollectionResponse)
    def history(
        session_id: str,
        from_at: Annotated[datetime, Query(alias="from")],
        to_at: Annotated[datetime, Query(alias="to")],
        stage_id: str | None = None,
        node_id: str | None = None,
        equipment_id: str | None = None,
        channel_id: str | None = None,
        metric: str | None = None,
        quality: Quality | None = None,
        alarm: Alarm | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AttributedTelemetryCollectionResponse:
        require_session(session_id)
        validate_limit(limit)
        if from_at.tzinfo is None or to_at.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="from and to must be timezone-aware timestamps",
            )
        if from_at >= to_at:
            raise HTTPException(status_code=422, detail="from must be earlier than to")
        if to_at - from_at > timedelta(days=max_history_days):
            raise HTTPException(
                status_code=422,
                detail=f"history range must not exceed {max_history_days} days",
            )

        rows = database.session_history_samples(
            session_id=session_id,
            query=SessionTelemetryQuery(
                stage_id=stage_id,
                node_id=node_id,
                equipment_id=equipment_id,
                channel_id=channel_id,
                metric=metric,
                quality=quality,
                alarm=alarm,
                from_at=from_at,
                to_at=to_at,
            ),
            limit=limit + 1,
            offset=offset,
        )
        return _collection(rows, limit=limit, offset=offset)

    return router
