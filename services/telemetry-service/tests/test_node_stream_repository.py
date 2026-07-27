from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.domain import ProvisionNodeCommand, build_node_topic
from app.nodes.repository import NodeRepository
from app.nodes.stream_contracts import NodeHealthEvent, NodeStatusEvent
from app.nodes.stream_repository import (
    NodeStreamAuthorizationError,
    NodeStreamReplayError,
    NodeStreamRepository,
)
from app.security.authorization import Role
from app.security.models import SecurityOrganization


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"
ROLES = frozenset({Role.LABORATORY_MANAGER})


def build_repositories(tmp_path: Path) -> tuple[NodeRepository, NodeStreamRepository, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'node-streams.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add_all(
            [
                SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A"),
                SecurityOrganization(id=ORGANIZATION_B, slug="org-b", name="Org B"),
            ]
        )
        session.commit()
    return NodeRepository(database), NodeStreamRepository(database), database


def activate_node(repository: NodeRepository) -> None:
    scoped = repository.for_organization(ORGANIZATION_A)
    scoped.provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="software commissioning",
    )


def health_event(*, sequence: int, event_id=None, captured_at=None) -> NodeHealthEvent:
    return NodeHealthEvent(
        event_id=event_id or uuid4(),
        node_id="edge-01",
        captured_at=captured_at or datetime(2026, 7, 27, 6, 0, tzinfo=UTC),
        node_sequence=sequence,
        health="healthy",
        uptime_seconds=sequence * 30,
        queue_depth=0,
        samples_total=sequence * 6,
        software_version="0.15.0",
        device_mode="simulator",
    )


def test_health_history_exact_replay_and_sequence_guards(tmp_path: Path) -> None:
    nodes, streams, database = build_repositories(tmp_path)
    activate_node(nodes)
    scoped = streams.for_organization(ORGANIZATION_A)
    topic = build_node_topic(ORGANIZATION_A, "edge-01", "health")
    received = datetime(2026, 7, 27, 6, 0, 1, tzinfo=UTC)

    first_event = health_event(sequence=1)
    first, replayed = scoped.persist_health(
        first_event,
        topic=topic,
        received_at=received,
    )
    replay, replayed_again = scoped.persist_health(
        first_event,
        topic=topic,
        received_at=received + timedelta(seconds=1),
    )

    assert replayed is False
    assert replayed_again is True
    assert replay.id == first.id
    assert scoped.latest_health("edge-01").event_id == str(first_event.event_id)
    assert len(scoped.health_history("edge-01")) == 1

    second_event = health_event(
        sequence=2,
        captured_at=received + timedelta(seconds=30),
    )
    scoped.persist_health(
        second_event,
        topic=topic,
        received_at=received + timedelta(seconds=31),
    )
    history = scoped.health_history("edge-01")
    assert [row.node_sequence for row in history] == [2, 1]

    with pytest.raises(NodeStreamReplayError, match="lower than"):
        scoped.persist_health(
            health_event(sequence=1),
            topic=topic,
            received_at=received + timedelta(seconds=32),
        )

    with pytest.raises(NodeStreamReplayError, match="bound to another event"):
        scoped.persist_health(
            health_event(sequence=2),
            topic=topic,
            received_at=received + timedelta(seconds=33),
        )

    database.dispose()


def test_status_latest_foreign_topic_and_suspended_node_rejection(tmp_path: Path) -> None:
    nodes, streams, database = build_repositories(tmp_path)
    activate_node(nodes)
    scoped = streams.for_organization(ORGANIZATION_A)
    captured = datetime(2026, 7, 27, 7, 0, tzinfo=UTC)
    online = NodeStatusEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured,
        node_sequence=1,
        status="online",
        reason="device agent connected",
        software_version="0.15.0",
        graceful=True,
    )
    row, replayed = scoped.persist_status(
        online,
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "status"),
        received_at=captured + timedelta(milliseconds=50),
    )
    assert replayed is False
    assert row.status == "online"
    assert scoped.latest_status("edge-01").event_id == str(online.event_id)

    with pytest.raises(NodeStreamAuthorizationError):
        scoped.persist_status(
            NodeStatusEvent(
                event_id=uuid4(),
                node_id="edge-01",
                captured_at=captured + timedelta(seconds=1),
                node_sequence=2,
                status="offline",
                reason="foreign topic",
                graceful=False,
            ),
            topic=build_node_topic(ORGANIZATION_B, "edge-01", "status"),
            received_at=captured + timedelta(seconds=1),
        )

    nodes.for_organization(ORGANIZATION_A).suspend(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance",
    )
    with pytest.raises(NodeStreamAuthorizationError, match="not active"):
        scoped.persist_status(
            NodeStatusEvent(
                event_id=uuid4(),
                node_id="edge-01",
                captured_at=captured + timedelta(seconds=2),
                node_sequence=2,
                status="offline",
                reason="maintenance disconnect",
                graceful=True,
            ),
            topic=build_node_topic(ORGANIZATION_A, "edge-01", "status"),
            received_at=captured + timedelta(seconds=2),
        )

    database.dispose()
