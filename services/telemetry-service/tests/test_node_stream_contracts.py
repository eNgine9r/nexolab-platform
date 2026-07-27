from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.nodes.stream_contracts import NodeHealthEvent, NodeStatusEvent


def test_health_contract_normalizes_identity_and_utc_payload() -> None:
    event = NodeHealthEvent(
        event_id=uuid4(),
        node_id=" EDGE-01 ",
        captured_at=datetime(2026, 7, 27, 5, 0, tzinfo=UTC),
        node_sequence=41,
        health="healthy",
        uptime_seconds=7200,
        queue_depth=0,
        samples_total=1440,
        software_version="0.15.0",
        device_mode="simulator",
    )

    assert event.node_id == "edge-01"
    assert event.captured_at.tzinfo is UTC
    assert event.normalized_payload() == {
        "schema_version": 1,
        "event_id": str(event.event_id),
        "node_id": "edge-01",
        "captured_at": "2026-07-27T05:00:00Z",
        "node_sequence": 41,
        "health": "healthy",
        "uptime_seconds": 7200,
        "queue_depth": 0,
        "samples_total": 1440,
        "software_version": "0.15.0",
        "device_mode": "simulator",
        "last_sample_at": None,
        "last_publish_at": None,
        "last_error": None,
    }


def test_degraded_health_requires_a_reason_and_healthy_rejects_one() -> None:
    base = {
        "event_id": uuid4(),
        "node_id": "edge-01",
        "captured_at": datetime.now(UTC),
        "node_sequence": 1,
        "uptime_seconds": 1,
        "queue_depth": 2,
        "samples_total": 3,
        "software_version": "0.15.0",
        "device_mode": "simulator",
    }

    with pytest.raises(ValidationError, match="degraded node health requires last_error"):
        NodeHealthEvent(**base, health="degraded")

    with pytest.raises(ValidationError, match="healthy node health cannot include last_error"):
        NodeHealthEvent(**base, health="healthy", last_error="stale serial bus")

    degraded = NodeHealthEvent(
        **base,
        health="degraded",
        last_error="MQTT backlog is growing",
    )
    assert degraded.last_error == "MQTT backlog is growing"


def test_status_contract_models_online_and_last_will_offline_transitions() -> None:
    online = NodeStatusEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=datetime.now(UTC),
        node_sequence=7,
        status="online",
        reason="device agent connected",
        software_version="0.15.0",
        graceful=True,
    )
    offline = NodeStatusEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=datetime.now(UTC),
        node_sequence=8,
        status="offline",
        reason="mqtt last will",
        software_version="0.15.0",
        graceful=False,
    )

    assert online.status == "online"
    assert offline.status == "offline"
    assert offline.graceful is False

    with pytest.raises(ValidationError, match="online status must be an explicit graceful publish"):
        NodeStatusEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=datetime.now(UTC),
            node_sequence=9,
            status="online",
            reason="invalid last will",
            graceful=False,
        )


def test_operational_streams_reject_unknown_fields_and_invalid_sequences() -> None:
    with pytest.raises(ValidationError):
        NodeStatusEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=datetime.now(UTC),
            node_sequence=0,
            status="offline",
            reason="invalid sequence",
            graceful=False,
            unexpected=True,
        )
