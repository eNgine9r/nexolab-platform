from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.broker_control import (
    BrokerControlOperation,
    BrokerControlSecretCipher,
    BrokerControlState,
)
from app.nodes.broker_models import CentralNodeBrokerCommand
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.domain import (
    ProvisionNodeCommand,
    RotateNodeCredentialCommand,
)
from app.nodes.models import CentralNode
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.security.repository import SecurityRepository


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ROLES = frozenset({Role.LABORATORY_MANAGER})


def build_repositories(
    tmp_path: Path,
) -> tuple[NodeRepository, BrokerControlRepository, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-lifecycle.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A")
        )
        session.commit()
    security = SecurityRepository(database)
    broker = BrokerControlRepository(
        database,
        BrokerControlSecretCipher(bytes(range(32)), key_id="broker-key-v1"),
    )
    nodes = NodeRepository(
        database,
        security_repository=security,
        broker_control_repository=broker,
    )
    return nodes, broker, database


def provision(nodes: NodeRepository):
    return nodes.for_organization(ORGANIZATION_A).provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )


def test_node_lifecycle_enqueues_exact_broker_commands_without_plaintext(
    tmp_path: Path,
) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    scoped = nodes.for_organization(ORGANIZATION_A)

    provisioned = provision(nodes)
    replayed_provision = provision(nodes)
    scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="commissioning approved",
    )
    rotated = scoped.rotate_credential(
        RotateNodeCredentialCommand(
            node_id="edge-01",
            idempotency_key="rotate-edge-01-2",
            actor_subject="manager-a",
            reason="scheduled rotation",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    replayed_rotation = scoped.rotate_credential(
        RotateNodeCredentialCommand(
            node_id="edge-01",
            idempotency_key="rotate-edge-01-2",
            actor_subject="manager-a",
            reason="scheduled rotation",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    scoped.suspend(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance",
    )
    scoped.suspend(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance",
    )
    scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance complete",
    )
    scoped.revoke(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="node retired",
    )
    scoped.revoke(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="node retired",
    )

    assert provisioned.secret is not None
    assert replayed_provision.replayed is True
    assert replayed_provision.secret is None
    assert rotated.secret is not None
    assert replayed_rotation.replayed is True
    assert replayed_rotation.secret is None

    with Session(database.engine) as session:
        commands = list(
            session.scalars(
                select(CentralNodeBrokerCommand).order_by(
                    CentralNodeBrokerCommand.created_at,
                    CentralNodeBrokerCommand.id,
                )
            )
        )

    assert len(commands) == 4
    assert {row.operation for row in commands} == {
        BrokerControlOperation.PROVISION.value,
        BrokerControlOperation.ROTATE.value,
        BrokerControlOperation.DISABLE.value,
        BrokerControlOperation.DELETE.value,
    }
    assert all(row.state == BrokerControlState.PENDING.value for row in commands)

    secret_commands = [
        row
        for row in commands
        if row.operation
        in {
            BrokerControlOperation.PROVISION.value,
            BrokerControlOperation.ROTATE.value,
        }
    ]
    nonsecret_commands = [
        row
        for row in commands
        if row.operation
        in {
            BrokerControlOperation.DISABLE.value,
            BrokerControlOperation.DELETE.value,
        }
    ]
    assert all(row.secret_ciphertext for row in secret_commands)
    assert all(row.secret_ciphertext is None for row in nonsecret_commands)
    serialized = " ".join(
        str(value)
        for row in commands
        for value in (
            row.secret_ciphertext,
            row.error_detail,
            row.deduplication_key,
            row.command_sha256,
        )
    )
    assert provisioned.secret not in serialized
    assert rotated.secret not in serialized

    history = broker.history(
        organization_id=ORGANIZATION_A,
        node_id="edge-01",
    )
    assert len(history) == 4
    database.dispose()


def test_broker_enqueue_failure_rolls_back_node_and_credential(
    tmp_path: Path,
) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-failure.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A")
        )
        session.commit()

    class FailingBrokerControlRepository:
        def enqueue_in_session(self, session: Session, **_: object) -> None:
            assert session.in_transaction()
            raise RuntimeError("broker outbox unavailable")

    nodes = NodeRepository(
        database,
        broker_control_repository=(
            FailingBrokerControlRepository()  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(RuntimeError, match="broker outbox unavailable"):
        provision(nodes)

    with Session(database.engine) as session:
        assert session.scalar(select(func.count()).select_from(CentralNode)) == 0
        assert session.scalar(
            select(func.count()).select_from(CentralNodeBrokerCommand)
        ) == 0
    database.dispose()
