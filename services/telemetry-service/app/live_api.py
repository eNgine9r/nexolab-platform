from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db import Database, TelemetryQuery, TelemetrySample
from app.live import OVERFLOW, SHUTDOWN, LiveTelemetryFilter, LiveTelemetryHub
from app.state import RuntimeState

ALLOWED_QUALITIES = {
    "valid",
    "sensor_error",
    "communication_error",
    "unknown",
}
ALLOWED_ALARMS = {"low", "high"}


def _sample_payload(sample: TelemetrySample) -> dict[str, Any]:
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
    return payload


def _parse_after(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    return parsed.astimezone(UTC)


def create_live_router(
    database: Database,
    hub: LiveTelemetryHub,
    state: RuntimeState,
    *,
    heartbeat_seconds: float,
    send_timeout_seconds: float,
    resume_limit: int,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry-live"])

    @router.websocket("/live")
    async def live(websocket: WebSocket) -> None:
        params = websocket.query_params
        quality = params.get("quality")
        alarm = params.get("alarm")

        await websocket.accept()

        if quality is not None and quality not in ALLOWED_QUALITIES:
            await websocket.send_json(
                {"type": "error", "detail": "unsupported quality filter"}
            )
            await websocket.close(code=1008, reason="invalid quality filter")
            return
        if alarm is not None and alarm not in ALLOWED_ALARMS:
            await websocket.send_json(
                {"type": "error", "detail": "unsupported alarm filter"}
            )
            await websocket.close(code=1008, reason="invalid alarm filter")
            return

        try:
            after = _parse_after(params.get("after"))
        except ValueError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1008, reason="invalid resume timestamp")
            return

        filters = LiveTelemetryFilter(
            node_id=params.get("node_id"),
            equipment_id=params.get("equipment_id"),
            channel_id=params.get("channel_id"),
            metric=params.get("metric"),
            quality=quality,
            alarm=alarm,
        )
        client = hub.register(filters)
        replayed_event_ids: set[str] = set()

        async def send(payload: dict[str, Any]) -> None:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=send_timeout_seconds,
            )

        try:
            if after is not None:
                replay_rows = database.history_samples(
                    query=TelemetryQuery(
                        node_id=filters.node_id,
                        equipment_id=filters.equipment_id,
                        channel_id=filters.channel_id,
                        metric=filters.metric,
                        quality=filters.quality,
                        alarm=filters.alarm,
                        from_at=after,
                    ),
                    limit=resume_limit + 1,
                    offset=0,
                )
                if len(replay_rows) > resume_limit:
                    await send(
                        {
                            "type": "error",
                            "detail": (
                                "resume result exceeds limit; reconnect with a "
                                "newer after timestamp"
                            ),
                        }
                    )
                    await websocket.close(code=1008, reason="resume limit exceeded")
                    return

                for sample in reversed(replay_rows):
                    payload = _sample_payload(sample)
                    await send(payload)
                    replayed_event_ids.add(sample.event_id)
                    state.increment("websocket_resume_total")

            while True:
                try:
                    item = await asyncio.wait_for(
                        client.queue.get(),
                        timeout=heartbeat_seconds,
                    )
                except TimeoutError:
                    await send(
                        {
                            "type": "heartbeat",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
                    state.increment("websocket_heartbeat_total")
                    continue

                if item is OVERFLOW:
                    await websocket.close(code=1013, reason="slow consumer")
                    return
                if item is SHUTDOWN:
                    await websocket.close(code=1012, reason="service restart")
                    return

                payload = item
                if not isinstance(payload, dict):
                    continue
                event_id = str(payload.get("event_id", ""))
                if event_id in replayed_event_ids:
                    continue
                await send(payload)
        except TimeoutError:
            state.increment("websocket_send_timeout_total")
            await websocket.close(code=1013, reason="send timeout")
        except WebSocketDisconnect:
            pass
        finally:
            hub.unregister(client)

    return router
