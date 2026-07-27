from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.nodes.domain import build_node_topic
from app.nodes.stream_contracts import NodeHealthEvent, NodeStatusEvent
from app.nodes.stream_repository import NodeStreamRepository
from app.security.authorization import Role
from tests.test_node_api import build_client
from tests.test_report_api import ORGANIZATION_A, ORGANIZATION_B, headers


def provision_and_activate(client, node_id: str) -> None:
    created = client.post(
        "/api/v1/nodes",
        headers={
            **headers(role=Role.LABORATORY_MANAGER),
            "Idempotency-Key": f"provision-{node_id}",
        },
        json={
            "node_id": node_id,
            "display_name": f"Node {node_id}",
            "clock_warning_ms": 30_000,
            "clock_critical_ms": 120_000,
        },
    )
    assert created.status_code == 201, created.text
    activated = client.post(
        f"/api/v1/nodes/{node_id}/activate",
        headers=headers(role=Role.LABORATORY_MANAGER),
        json={"reason": "operational stream acceptance"},
    )
    assert activated.status_code == 200, activated.text


def test_operational_state_history_staleness_and_isolation(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    provision_and_activate(client, "edge-01")
    provision_and_activate(client, "edge-02")
    streams = NodeStreamRepository(database).for_organization(ORGANIZATION_A)
    now = datetime.now(UTC)

    streams.persist_status(
        NodeStatusEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=now - timedelta(seconds=10),
            node_sequence=1,
            status="online",
            reason="device agent connected",
            software_version="0.15.0",
            graceful=True,
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "status"),
        received_at=now - timedelta(seconds=10),
    )
    streams.persist_health(
        NodeHealthEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=now - timedelta(seconds=5),
            node_sequence=1,
            health="degraded",
            uptime_seconds=600,
            queue_depth=3,
            samples_total=120,
            software_version="0.15.0",
            device_mode="simulator",
            last_error="MQTT backlog is growing",
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "health"),
        received_at=now - timedelta(seconds=5),
    )

    state = client.get(
        "/api/v1/nodes/edge-01/operational-state",
        headers=headers(role=Role.VIEWER),
    )
    assert state.status_code == 200, state.text
    assert state.json()["availability"] == "online"
    assert state.json()["degraded_reason"] == "MQTT backlog is growing"
    assert state.json()["latest_health"]["queue_depth"] == 3
    assert state.json()["latest_status"]["status"] == "online"
    assert 0 <= state.json()["heartbeat_age_seconds"] < 30

    health_history = client.get(
        "/api/v1/nodes/edge-01/health-history?limit=1",
        headers=headers(role=Role.VIEWER),
    )
    status_history = client.get(
        "/api/v1/nodes/edge-01/status-history?limit=1",
        headers=headers(role=Role.VIEWER),
    )
    assert health_history.status_code == 200
    assert status_history.status_code == 200
    assert len(health_history.json()) == 1
    assert len(status_history.json()) == 1

    stale_received = now - timedelta(minutes=5)
    streams.persist_status(
        NodeStatusEvent(
            event_id=uuid4(),
            node_id="edge-02",
            captured_at=stale_received,
            node_sequence=1,
            status="online",
            reason="device agent connected",
            software_version="0.15.0",
            graceful=True,
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-02", "status"),
        received_at=stale_received,
    )
    streams.persist_health(
        NodeHealthEvent(
            event_id=uuid4(),
            node_id="edge-02",
            captured_at=stale_received,
            node_sequence=1,
            health="healthy",
            uptime_seconds=30,
            queue_depth=0,
            samples_total=6,
            software_version="0.15.0",
            device_mode="simulator",
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-02", "health"),
        received_at=stale_received,
    )
    stale = client.get(
        "/api/v1/nodes/edge-02/operational-state",
        headers=headers(role=Role.VIEWER),
    )
    assert stale.status_code == 200
    assert stale.json()["availability"] == "stale"
    assert stale.json()["degraded_reason"] == "node heartbeat is stale"
    assert stale.json()["heartbeat_age_seconds"] >= 299

    foreign = client.get(
        "/api/v1/nodes/edge-01/operational-state",
        headers=headers(ORGANIZATION_B, role=Role.VIEWER),
    )
    assert foreign.status_code == 404
    database.dispose()


def test_newer_retained_offline_status_overrides_previous_health(tmp_path: Path) -> None:
    client, database = build_client(tmp_path)
    provision_and_activate(client, "edge-01")
    streams = NodeStreamRepository(database).for_organization(ORGANIZATION_A)
    now = datetime.now(UTC)

    streams.persist_health(
        NodeHealthEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=now - timedelta(seconds=2),
            node_sequence=1,
            health="healthy",
            uptime_seconds=300,
            queue_depth=0,
            samples_total=60,
            software_version="0.15.0",
            device_mode="simulator",
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "health"),
        received_at=now - timedelta(seconds=2),
    )
    streams.persist_status(
        NodeStatusEvent(
            event_id=uuid4(),
            node_id="edge-01",
            captured_at=now - timedelta(seconds=1),
            node_sequence=1,
            status="offline",
            reason="mqtt last will",
            software_version="0.15.0",
            graceful=False,
        ),
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "status"),
        received_at=now - timedelta(seconds=1),
    )

    response = client.get(
        "/api/v1/nodes/edge-01/operational-state",
        headers=headers(role=Role.ENGINEER),
    )
    assert response.status_code == 200
    assert response.json()["availability"] == "offline"
    assert response.json()["degraded_reason"] == "mqtt last will"
    database.dispose()
