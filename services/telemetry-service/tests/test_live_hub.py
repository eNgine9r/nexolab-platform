from __future__ import annotations

import asyncio
from uuid import uuid4

from app.live import OVERFLOW, LiveTelemetryFilter, LiveTelemetryHub
from app.state import RuntimeState


def payload(*, channel_id: str, metric: str = "temperature.probe") -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "node_id": "edge-01",
        "captured_at": "2026-07-23T12:00:00+00:00",
        "metric": metric,
        "value": 26.0,
        "unit": "degC",
        "quality": "valid",
        "source": "dixell-xjp60d",
        "equipment_id": "K106",
        "channel_id": channel_id,
        "alarm": "high",
        "raw_value": 260,
        "raw_status": 4354,
    }


def test_hub_enforces_server_side_filters() -> None:
    async def scenario() -> None:
        state = RuntimeState()
        hub = LiveTelemetryHub(state, queue_maxsize=4)
        hub.start(asyncio.get_running_loop())
        matching = hub.register(LiveTelemetryFilter(channel_id="106-03"))
        filtered = hub.register(LiveTelemetryFilter(channel_id="106-04"))

        event = payload(channel_id="106-03")
        hub.publish_committed(event)

        delivered = await matching.queue.get()
        assert isinstance(delivered, dict)
        assert delivered["event_id"] == event["event_id"]
        assert delivered["state_source"] == "persisted"
        assert delivered["staleness"] == "unknown"
        assert delivered["age_seconds"] >= 0
        assert filtered.queue.empty()
        snapshot = state.snapshot()
        assert snapshot["websocket_clients"] == 2
        assert snapshot["websocket_broadcast_total"] == 1
        assert snapshot["websocket_filtered_total"] == 1

        hub.unregister(matching)
        hub.unregister(filtered)
        hub.stop()

    asyncio.run(scenario())


def test_slow_consumer_isolated_without_blocking_other_clients() -> None:
    async def scenario() -> None:
        state = RuntimeState()
        hub = LiveTelemetryHub(state, queue_maxsize=1)
        hub.start(asyncio.get_running_loop())
        slow = hub.register(LiveTelemetryFilter())
        fast = hub.register(LiveTelemetryFilter())

        first = payload(channel_id="106-03")
        second = payload(channel_id="106-04")
        hub.publish_committed(first)
        fast_first = await fast.queue.get()
        assert isinstance(fast_first, dict)
        assert fast_first["event_id"] == first["event_id"]

        hub.publish_committed(second)

        assert await slow.queue.get() is OVERFLOW
        fast_second = await fast.queue.get()
        assert isinstance(fast_second, dict)
        assert fast_second["event_id"] == second["event_id"]
        snapshot = state.snapshot()
        assert snapshot["websocket_slow_consumer_total"] == 1
        assert snapshot["websocket_clients"] == 1
        assert snapshot["websocket_broadcast_total"] == 3

        hub.unregister(fast)
        hub.stop()

    asyncio.run(scenario())


def test_client_churn_changes_only_fanout_metrics() -> None:
    async def scenario() -> None:
        state = RuntimeState()
        hub = LiveTelemetryHub(state, queue_maxsize=4)
        hub.start(asyncio.get_running_loop())

        for _ in range(100):
            client = hub.register(LiveTelemetryFilter())
            hub.unregister(client)

        snapshot = state.snapshot()
        assert snapshot["websocket_clients"] == 0
        assert snapshot["websocket_connect_total"] == 100
        assert snapshot["websocket_disconnect_total"] == 100
        assert snapshot["received_total"] == 0
        assert snapshot["accepted_total"] == 0
        assert snapshot["persisted_total"] == 0
        hub.stop()

    asyncio.run(scenario())
