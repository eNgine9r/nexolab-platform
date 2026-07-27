from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.domain import ProvisionNodeCommand, build_node_topic
from app.nodes.repository import NodeRepository
from app.nodes.stream_ingestion import NodeStreamIngestor
from app.nodes.stream_repository import NodeStreamRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.state import RuntimeState


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
ROLES = frozenset({Role.LABORATORY_MANAGER})


def wait_for(predicate, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def setup_active_node(database: Database) -> None:
    repository = NodeRepository(database).for_organization(ORGANIZATION_ID)
    repository.provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    repository.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="activate simulated health stream",
    )


def test_health_and_status_bypass_telemetry_samples(tmp_path: Path) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'node-stream-ingestion.db'}")
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
    setup_active_node(database)

    state = RuntimeState()
    ingestor = NodeStreamIngestor(database, state, queue_maxsize=10)
    ingestor.start()
    captured = datetime.now(UTC)
    health_event_id = str(uuid4())
    status_event_id = str(uuid4())

    assert ingestor.submit_payload(
        json.dumps(
            {
                "schema_version": 1,
                "event_id": health_event_id,
                "node_id": "edge-01",
                "captured_at": captured.isoformat(),
                "node_sequence": 1,
                "health": "healthy",
                "uptime_seconds": 60,
                "queue_depth": 0,
                "samples_total": 12,
                "software_version": "0.15.0",
                "device_mode": "simulator",
                "last_sample_at": None,
                "last_publish_at": None,
                "last_error": None,
            }
        ).encode("utf-8"),
        topic=build_node_topic(ORGANIZATION_ID, "edge-01", "health"),
    )
    assert ingestor.submit_payload(
        json.dumps(
            {
                "schema_version": 1,
                "event_id": status_event_id,
                "node_id": "edge-01",
                "captured_at": captured.isoformat(),
                "node_sequence": 1,
                "status": "online",
                "reason": "device agent connected",
                "software_version": "0.15.0",
                "graceful": True,
            }
        ).encode("utf-8"),
        topic=build_node_topic(ORGANIZATION_ID, "edge-01", "status"),
    )

    repository = NodeStreamRepository(database).for_organization(ORGANIZATION_ID)
    wait_for(
        lambda: repository.latest_health("edge-01") is not None
        and repository.latest_status("edge-01") is not None
    )
    ingestor.stop()

    assert repository.latest_health("edge-01").event_id == health_event_id
    assert repository.latest_status("edge-01").event_id == status_event_id
    assert database.count_samples() == 0
    database.dispose()


def test_foreign_health_topic_is_dead_lettered(tmp_path: Path) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'foreign-node-stream.db'}")
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
    setup_active_node(database)

    state = RuntimeState()
    ingestor = NodeStreamIngestor(database, state, queue_maxsize=10)
    ingestor.start()
    payload = json.dumps(
        {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "node_id": "edge-01",
            "captured_at": datetime.now(UTC).isoformat(),
            "node_sequence": 1,
            "health": "healthy",
            "uptime_seconds": 60,
            "queue_depth": 0,
            "samples_total": 12,
            "software_version": "0.15.0",
            "device_mode": "simulator",
            "last_sample_at": None,
            "last_publish_at": None,
            "last_error": None,
        }
    ).encode("utf-8")
    assert ingestor.submit_payload(
        payload,
        topic=build_node_topic(ORGANIZATION_ID, "edge-02", "health"),
    )

    wait_for(
        lambda: state.snapshot()["dead_letter_by_reason"].get(
            "node_authorization",
            0,
        )
        == 1
    )
    ingestor.stop()
    assert database.count_samples() == 0
    database.dispose()
