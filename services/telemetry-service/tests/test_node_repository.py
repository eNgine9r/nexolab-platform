from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.domain import (
    ClockStatus,
    NodeState,
    ProvisionNodeCommand,
    RotateNodeCredentialCommand,
    build_node_topic,
)
from app.nodes.repository import NodeAuthenticationError, NodeNotFoundError, NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.security.repository import SecurityRepository


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ORGANIZATION_B = "00000000-0000-0000-0000-000000000002"
ROLES = frozenset({Role.LABORATORY_MANAGER})


def build_repository(tmp_path: Path) -> tuple[NodeRepository, SecurityRepository, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'nodes.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add_all(
            [
                SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A"),
                SecurityOrganization(id=ORGANIZATION_B, slug="org-b", name="Org B"),
            ]
        )
        session.commit()
    security = SecurityRepository(database)
    return NodeRepository(database, security_repository=security), security, database


def provision(repository: NodeRepository):
    return repository.for_organization(ORGANIZATION_A).provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )


def test_provision_replay_rotation_topic_ownership_and_clock_policy(tmp_path: Path) -> None:
    repository, security, database = build_repository(tmp_path)
    scoped = repository.for_organization(ORGANIZATION_A)

    first = provision(repository)
    replay = provision(repository)
    assert first.replayed is False
    assert first.secret is not None
    assert first.node.state == NodeState.PENDING.value
    assert first.credential.secret_hash != first.secret
    assert replay.replayed is True
    assert replay.secret is None
    assert replay.node.id == first.node.id
    assert replay.credential.id == first.credential.id

    active = scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="commissioning approved",
    )
    assert active.state == NodeState.ACTIVE.value

    observed_at = datetime(2026, 7, 26, 21, 0, tzinfo=UTC)
    authorized = scoped.authenticate_publish(
        node_id="edge-01",
        secret=first.secret,
        topic=build_node_topic(ORGANIZATION_A, "edge-01", "telemetry"),
        observed_at=observed_at,
        node_time=observed_at + timedelta(seconds=45),
    )
    assert authorized.clock_status is ClockStatus.WARNING
    assert authorized.clock_offset_ms == 45_000
    assert authorized.node.last_seen_at is not None

    with pytest.raises(NodeAuthenticationError):
        scoped.authenticate_publish(
            node_id="edge-01",
            secret=first.secret,
            topic=build_node_topic(ORGANIZATION_A, "edge-02", "telemetry"),
            observed_at=observed_at,
            node_time=observed_at,
        )

    rotated = scoped.rotate_credential(
        RotateNodeCredentialCommand(
            node_id="edge-01",
            idempotency_key="rotate-edge-01-2",
            actor_subject="manager-a",
            reason="scheduled credential rotation",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    assert rotated.secret is not None
    assert rotated.credential.generation == 2

    with pytest.raises(NodeAuthenticationError):
        scoped.authenticate_publish(
            node_id="edge-01",
            secret=first.secret,
            topic=build_node_topic(ORGANIZATION_A, "edge-01", "health"),
            observed_at=observed_at,
            node_time=observed_at,
        )
    assert (
        scoped.authenticate_publish(
            node_id="edge-01",
            secret=rotated.secret,
            topic=build_node_topic(ORGANIZATION_A, "edge-01", "health"),
            observed_at=observed_at,
            node_time=observed_at + timedelta(seconds=121),
        ).clock_status
        is ClockStatus.CRITICAL
    )

    suspended = scoped.suspend(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance window",
    )
    assert suspended.state == NodeState.SUSPENDED.value
    with pytest.raises(NodeAuthenticationError):
        scoped.authenticate_publish(
            node_id="edge-01",
            secret=rotated.secret,
            topic=build_node_topic(ORGANIZATION_A, "edge-01", "status"),
            observed_at=observed_at,
            node_time=observed_at,
        )

    with pytest.raises(NodeNotFoundError):
        repository.for_organization(ORGANIZATION_B).get_node("edge-01")

    events = security.list_audit_events(organization_id=ORGANIZATION_A, limit=20)
    actions = {event.action for event in events}
    assert {
        "node.provisioned",
        "node.active",
        "node.credential.rotated",
        "node.suspended",
    }.issubset(actions)
    serialized = " ".join(str(event.after_snapshot) for event in events)
    assert first.secret not in serialized
    assert rotated.secret not in serialized

    database.dispose()


def test_revocation_invalidates_current_credential(tmp_path: Path) -> None:
    repository, _, database = build_repository(tmp_path)
    scoped = repository.for_organization(ORGANIZATION_A)
    provisioned = provision(repository)
    scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="activate",
    )
    revoked = scoped.revoke(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="node retired",
    )
    assert revoked.state == NodeState.REVOKED.value
    assert scoped.current_credential("edge-01") is None
    with pytest.raises(NodeAuthenticationError):
        scoped.authenticate_publish(
            node_id="edge-01",
            secret=provisioned.secret or "",
            topic=build_node_topic(ORGANIZATION_A, "edge-01", "telemetry"),
            observed_at=datetime.now(UTC),
        )
    database.dispose()
