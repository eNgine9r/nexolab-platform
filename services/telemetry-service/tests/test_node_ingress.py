from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import Database
from app.ingestion import TelemetryIngestor
from app.model_registry import register_models
from app.nodes.domain import ProvisionNodeCommand, build_node_topic
from app.nodes.ingress import (
    NODE_AUTHORIZATION_REASON,
    NODE_REPLAY_REASON,
    NodeIngressAuthorizer,
)
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.state import RuntimeState


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
ROLES = frozenset({Role.LABORATORY_MANAGER})


def telemetry_payload(*, node_id: str, event_id: str, sequence: int | None) -> bytes:
    payload = {
        "event_id": event_id,
        "node_id": node_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "metric": "temperature.probe",
        "value": 3.25,
        "unit": "degC",
        "quality": "valid",
        "source": "simulated-node-ingress",
        "equipment_id": "K106",
        "channel_id": "106-01",
    }
    if sequence is not None:
        payload["node_sequence"] = sequence
    return json.dumps(payload).encode("utf-8")


def wait_for(predicate, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def build_active_node(tmp_path: Path) -> tuple[Database, NodeRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'node-ingress.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(
                id=ORGANIZATION_ID,
                slug="org-a",
                name="Organization A",
            )
        )
        session.commit()

    repository = NodeRepository(database).for_organization(ORGANIZATION_ID)
    provisioned = repository.provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    assert provisioned.secret is not None
    repository.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="simulated commissioning",
    )
    return database, repository


def test_trusted_broker_gate_persists_owned_topic_and_rejects_foreign_node(
    tmp_path: Path,
) -> None:
    database, repository = build_active_node(tmp_path)
    state = RuntimeState()
    authorizer = NodeIngressAuthorizer(database)
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        authorize_ingress=authorizer.authorize,
    )
    ingestor.start()

    owned_topic = build_node_topic(ORGANIZATION_ID, "edge-01", "telemetry")
    foreign_topic = build_node_topic(ORGANIZATION_ID, "edge-02", "telemetry")
    assert ingestor.submit_payload(
        telemetry_payload(node_id="edge-01", event_id=str(uuid4()), sequence=1),
        topic=owned_topic,
    )
    assert ingestor.submit_payload(
        telemetry_payload(node_id="edge-01", event_id=str(uuid4()), sequence=2),
        topic=foreign_topic,
    )

    wait_for(
        lambda: state.snapshot()["persisted_total"] == 1
        and state.snapshot()["dead_letter_by_reason"].get(
            NODE_AUTHORIZATION_REASON,
            0,
        )
        == 1
    )
    ingestor.stop()

    assert database.count_samples() == 1
    refreshed = repository.get_node("edge-01")
    assert refreshed.last_seen_at is not None
    assert refreshed.clock_observed_at is not None
    assert state.snapshot()["rejected_total"] == 1
    database.dispose()


def test_sequence_cursor_allows_exact_retry_and_rejects_replay(tmp_path: Path) -> None:
    database, _ = build_active_node(tmp_path)
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        authorize_ingress=NodeIngressAuthorizer(database).authorize,
    )
    ingestor.start()
    topic = build_node_topic(ORGANIZATION_ID, "edge-01", "telemetry")
    first_event_id = str(uuid4())
    first = telemetry_payload(node_id="edge-01", event_id=first_event_id, sequence=10)
    exact_retry = first
    conflicting_replay = telemetry_payload(
        node_id="edge-01",
        event_id=str(uuid4()),
        sequence=10,
    )
    older_replay = telemetry_payload(
        node_id="edge-01",
        event_id=str(uuid4()),
        sequence=9,
    )

    assert ingestor.submit_payload(first, topic=topic)
    assert ingestor.submit_payload(exact_retry, topic=topic)
    assert ingestor.submit_payload(conflicting_replay, topic=topic)
    assert ingestor.submit_payload(older_replay, topic=topic)

    wait_for(
        lambda: state.snapshot()["persisted_total"] == 1
        and state.snapshot()["duplicate_total"] == 1
        and state.snapshot()["dead_letter_by_reason"].get(NODE_REPLAY_REASON, 0)
        == 2
    )
    ingestor.stop()
    assert database.count_samples() == 1
    assert state.snapshot()["rejected_total"] == 2
    database.dispose()


def test_registry_enforcement_requires_topic_and_sequence(tmp_path: Path) -> None:
    database, _ = build_active_node(tmp_path)
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        authorize_ingress=NodeIngressAuthorizer(database).authorize,
    )
    ingestor.start()
    assert ingestor.submit_payload(
        telemetry_payload(node_id="edge-01", event_id=str(uuid4()), sequence=1)
    )
    assert ingestor.submit_payload(
        telemetry_payload(node_id="edge-01", event_id=str(uuid4()), sequence=None),
        topic=build_node_topic(ORGANIZATION_ID, "edge-01", "telemetry"),
    )
    wait_for(
        lambda: state.snapshot()["dead_letter_by_reason"].get(
            NODE_AUTHORIZATION_REASON,
            0,
        )
        == 1
        and state.snapshot()["dead_letter_by_reason"].get(NODE_REPLAY_REASON, 0)
        == 1
    )
    ingestor.stop()
    assert database.count_samples() == 0
    database.dispose()
