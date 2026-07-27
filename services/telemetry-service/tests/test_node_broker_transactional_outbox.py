from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.broker_control import BrokerControlOperation, BrokerControlSecretCipher
from app.nodes.broker_models import CentralNodeBrokerCommand
from app.nodes.broker_repository import (
    BrokerControlConflictError,
    BrokerControlRepository,
    BrokerControlStateError,
)
from app.nodes.domain import ProvisionNodeCommand
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ROLES = frozenset({Role.LABORATORY_MANAGER})
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)


def build_repositories(
    tmp_path: Path,
) -> tuple[NodeRepository, BrokerControlRepository, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-transaction.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A")
        )
        session.commit()
    cipher = BrokerControlSecretCipher(bytes(range(32)), key_id="broker-key-v1")
    return NodeRepository(database), BrokerControlRepository(database, cipher), database


def provision_node(nodes: NodeRepository):
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


def enqueue_in_transaction(
    broker: BrokerControlRepository,
    session: Session,
    provisioned,
    *,
    command_sha256: str = "a" * 64,
):
    return broker.enqueue_in_session(
        session,
        organization_id=ORGANIZATION_A,
        node_record_id=provisioned.node.id,
        node_id=provisioned.node.node_id,
        credential_id=provisioned.credential.id,
        operation=BrokerControlOperation.PROVISION,
        deduplication_key="broker-provision-edge-01-generation-1",
        command_sha256=command_sha256,
        secret=provisioned.secret,
        available_at=NOW,
    )


def test_transactional_enqueue_rolls_back_with_caller_transaction(
    tmp_path: Path,
) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)

    with pytest.raises(RuntimeError, match="force rollback"):
        with Session(database.engine) as session:
            with session.begin():
                result = enqueue_in_transaction(broker, session, provisioned)
                assert result.replayed is False
                assert result.command.secret_ciphertext is not None
                assert provisioned.secret not in result.command.secret_ciphertext
                assert session.scalar(
                    select(func.count()).select_from(CentralNodeBrokerCommand)
                ) == 1
                raise RuntimeError("force rollback")

    with Session(database.engine) as session:
        assert session.scalar(
            select(func.count()).select_from(CentralNodeBrokerCommand)
        ) == 0
    database.dispose()


def test_transactional_enqueue_commits_and_exact_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)

    with Session(database.engine, expire_on_commit=False) as session:
        with session.begin():
            first = enqueue_in_transaction(broker, session, provisioned)
            replay = enqueue_in_transaction(broker, session, provisioned)
            assert first.replayed is False
            assert replay.replayed is True
            assert replay.command.id == first.command.id

    history = broker.history(
        organization_id=ORGANIZATION_A,
        node_id="edge-01",
    )
    assert len(history) == 1
    assert history[0].id == first.command.id
    database.dispose()


def test_transactional_enqueue_rejects_conflict_and_requires_owned_transaction(
    tmp_path: Path,
) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)

    with Session(database.engine) as session:
        with pytest.raises(BrokerControlStateError, match="active transaction"):
            enqueue_in_transaction(broker, session, provisioned)

    with Session(database.engine) as session:
        with session.begin():
            enqueue_in_transaction(broker, session, provisioned)
            with pytest.raises(BrokerControlConflictError, match="another command"):
                enqueue_in_transaction(
                    broker,
                    session,
                    provisioned,
                    command_sha256="b" * 64,
                )

    database.dispose()
