from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final
from uuid import uuid4

from app.state import RuntimeState


OVERFLOW: Final = object()
SHUTDOWN: Final = object()


@dataclass(frozen=True)
class LiveTelemetryFilter:
    node_id: str | None = None
    equipment_id: str | None = None
    channel_id: str | None = None
    metric: str | None = None
    quality: str | None = None
    alarm: str | None = None
    session_id: str | None = None
    stage_id: str | None = None
    binding_id: str | None = None
    config_snapshot_id: str | None = None
    session_state: str | None = None

    def matches(self, payload: dict[str, Any]) -> bool:
        for field in (
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            "quality",
            "alarm",
            "session_id",
            "stage_id",
            "binding_id",
            "config_snapshot_id",
            "session_state",
        ):
            expected = getattr(self, field)
            if expected is not None and payload.get(field) != expected:
                return False
        return True


@dataclass
class LiveClient:
    client_id: str
    filters: LiveTelemetryFilter
    queue: asyncio.Queue[object]
    closed: bool = False


class LiveTelemetryHub:
    """Thread-safe fan-out hub with one bounded queue per WebSocket client."""

    def __init__(self, state: RuntimeState, queue_maxsize: int) -> None:
        self._state = state
        self._queue_maxsize = queue_maxsize
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[str, LiveClient] = {}

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()

    def stop(self) -> None:
        for client in list(self._clients.values()):
            self._close_client(client, SHUTDOWN, dropped=False)
        self._clients.clear()
        self._state.set_websocket_clients(0)
        self._loop = None

    def register(self, filters: LiveTelemetryFilter) -> LiveClient:
        if self._loop is None:
            raise RuntimeError("live telemetry hub is not running")
        client = LiveClient(
            client_id=str(uuid4()),
            filters=filters,
            queue=asyncio.Queue(maxsize=self._queue_maxsize),
        )
        self._clients[client.client_id] = client
        self._state.set_websocket_clients(len(self._clients))
        self._state.increment("websocket_connect_total")
        return client

    def unregister(self, client: LiveClient) -> None:
        removed = self._clients.pop(client.client_id, None)
        if removed is not None:
            client.closed = True
            self._state.set_websocket_clients(len(self._clients))
            self._state.increment("websocket_disconnect_total")

    def publish_from_thread(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self.publish, payload)

    def publish(self, payload: dict[str, Any]) -> None:
        """Publish without awaiting any client or network operation."""

        for client in list(self._clients.values()):
            if client.closed:
                continue
            if not client.filters.matches(payload):
                self._state.increment("websocket_filtered_total")
                continue
            try:
                client.queue.put_nowait(dict(payload))
            except asyncio.QueueFull:
                self._close_client(client, OVERFLOW, dropped=True)
            else:
                self._state.increment("websocket_broadcast_total")

    def _close_client(
        self,
        client: LiveClient,
        sentinel: object,
        *,
        dropped: bool,
    ) -> None:
        if client.closed:
            return
        client.closed = True
        self._clients.pop(client.client_id, None)
        while not client.queue.empty():
            try:
                client.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        client.queue.put_nowait(sentinel)
        self._state.set_websocket_clients(len(self._clients))
        self._state.increment("websocket_disconnect_total")
        if dropped:
            self._state.increment("websocket_slow_consumer_total")
