from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.db import Database, TelemetryQuery
from app.delivery import PersistedTelemetryReadModel
from app.live import OVERFLOW, SHUTDOWN, LiveTelemetryFilter, LiveTelemetryHub
from app.security.authorization import Permission
from app.security.dependencies import SecurityDependencies
from app.state import RuntimeState

ALLOWED_QUALITIES = {
    "valid",
    "sensor_error",
    "communication_error",
    "unknown",
}
ALLOWED_ALARMS = {"low", "high"}


def _parse_after(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    return parsed.astimezone(UTC)


def _http_error(error: HTTPException) -> tuple[str, str]:
    if isinstance(error.detail, dict):
        code = str(error.detail.get("code") or "websocket_access_denied")
        message = str(error.detail.get("message") or "WebSocket access denied")
        return code, message
    return "websocket_access_denied", str(error.detail)


async def _authenticate_websocket(
    websocket: WebSocket,
    security_dependencies: SecurityDependencies | None,
    *,
    timeout_seconds: float,
) -> bool:
    if (
        security_dependencies is None
        or not security_dependencies.authentication_required
    ):
        return True

    try:
        payload = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        await websocket.send_json(
            {
                "type": "error",
                "code": "websocket_authentication_timeout",
                "detail": "Telemetry authentication message was not received in time",
            }
        )
        await websocket.close(code=1008, reason="authentication timeout")
        return False
    except WebSocketDisconnect:
        return False
    except Exception:
        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_websocket_authentication",
                "detail": "Telemetry authentication payload must be valid JSON",
            }
        )
        await websocket.close(code=1008, reason="invalid authentication payload")
        return False

    if not isinstance(payload, dict) or payload.get("type") != "authenticate":
        await websocket.send_json(
            {
                "type": "error",
                "code": "invalid_websocket_authentication",
                "detail": "The first WebSocket message must authenticate the session",
            }
        )
        await websocket.close(code=1008, reason="authentication required")
        return False

    access_token = payload.get("access_token")
    organization_id = payload.get("organization_id")
    if not isinstance(access_token, str) or not access_token.strip():
        await websocket.send_json(
            {
                "type": "error",
                "code": "missing_bearer_token",
                "detail": "A non-empty access token is required",
            }
        )
        await websocket.close(code=1008, reason="authentication required")
        return False
    if not isinstance(organization_id, str) or not organization_id.strip():
        await websocket.send_json(
            {
                "type": "error",
                "code": "organization_header_required",
                "detail": "A selected organization is required",
            }
        )
        await websocket.close(code=1008, reason="organization required")
        return False

    try:
        authorized = security_dependencies.authorize_credentials(
            f"Bearer {access_token.strip()}",
            organization_id.strip(),
            Permission.READ_TELEMETRY,
        )
    except HTTPException as error:
        code, message = _http_error(error)
        await websocket.send_json(
            {
                "type": "error",
                "code": code,
                "detail": message,
            }
        )
        await websocket.close(code=1008, reason="access denied")
        return False

    await websocket.send_json(
        {
            "type": "authenticated",
            "subject": authorized.principal.subject,
            "organization_id": authorized.principal.organization_id,
        }
    )
    return True


async def _wait_for_websocket_disconnect(websocket: WebSocket) -> None:
    """Consume the one inbound stream after authentication until disconnect."""

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return


def create_live_router(
    database: Database,
    hub: LiveTelemetryHub,
    state: RuntimeState,
    *,
    heartbeat_seconds: float,
    send_timeout_seconds: float,
    auth_timeout_seconds: float = 5.0,
    resume_limit: int,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry-live"])
    read_model = PersistedTelemetryReadModel(database)

    @router.websocket("/live")
    async def live(websocket: WebSocket) -> None:
        params = websocket.query_params
        quality = params.get("quality")
        alarm = params.get("alarm")

        await websocket.accept()
        if not await _authenticate_websocket(
            websocket,
            security_dependencies,
            timeout_seconds=auth_timeout_seconds,
        ):
            return

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
            await websocket.close(code=1008, reason="invalid quality filter")
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
        disconnect_task = asyncio.create_task(
            _wait_for_websocket_disconnect(websocket)
        )

        async def send(payload: dict[str, Any]) -> None:
            await asyncio.wait_for(
                websocket.send_json(payload),
                timeout=send_timeout_seconds,
            )

        try:
            if after is not None:
                replay_rows = read_model.history_samples(
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

                for payload in reversed(replay_rows):
                    await send(payload)
                    replayed_event_ids.add(str(payload["event_id"]))
                    state.increment("websocket_resume_total")

            while True:
                queue_task = asyncio.create_task(client.queue.get())
                done, _ = await asyncio.wait(
                    {disconnect_task, queue_task},
                    timeout=heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if disconnect_task in done:
                    queue_task.cancel()
                    await asyncio.gather(queue_task, return_exceptions=True)
                    return

                if queue_task not in done:
                    queue_task.cancel()
                    await asyncio.gather(queue_task, return_exceptions=True)
                    await send(
                        {
                            "type": "heartbeat",
                            "server_time": datetime.now(UTC).isoformat(),
                        }
                    )
                    state.increment("websocket_heartbeat_total")
                    continue

                item = queue_task.result()
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
            disconnect_task.cancel()
            await asyncio.gather(disconnect_task, return_exceptions=True)
            hub.unregister(client)

    return router
