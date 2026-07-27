from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.broker_control import (
    BrokerControlOperation,
    BrokerControlSecretCipher,
    BrokerControlState,
)
from app.nodes.broker_models import CentralNodeBrokerCommand
from app.nodes.broker_repository import (
    BrokerControlConflictError,
    BrokerControlEnvelopeError,
    BrokerControlRepository,
)
from app.nodes.domain import ProvisionNodeCommand
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization


ORGANIZATION_A = "00000000-0000-0000-0000-000000000001"
ROLES = frozenset({Role.LABORATORY_MANAGER})
NOW = datetime(2026, 7, 27, 13, 0, tzinfo=UTC)


def build_repositories(
    tmp_path: Path,
) -> tuple[NodeRepository, BrokerControlRepository, Database]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-control.db'}")
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


def enqueue_provision(
    broker: BrokerControlRepository,
    provisioned,
    *,
    deduplication_key: str = "broker-provision-edge-01-generation-1",
    command_sha256: str = "a" * 64,
):
    return broker.enqueue(
        organization_id=ORGANIZATION_A,
        node_record_id=provisioned.node.id,
        node_id=provisioned.node.node_id,
        credential_id=provisioned.credential.id,
        operation=BrokerControlOperation.PROVISION,
        deduplication_key=deduplication_key,
        command_sha256=command_sha256,
        secret=provisioned.secret,
        available_at=NOW,
    )


def test_enqueue_replay_claim_retry_and_apply(tmp_path: Path) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)
    secret = provisioned.secret
    assert secret is not None

    first = enqueue_provision(broker, provisioned)
    replay = enqueue_provision(broker, provisioned)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.command.id == first.command.id
    assert first.command.secret_ciphertext is not None
    assert secret not in first.command.secret_ciphertext

    claimed = broker.claim_next(now=NOW)
    assert claimed is not None
    assert claimed.command.id == first.command.id
    assert claimed.command.state == BrokerControlState.PROCESSING.value
    assert claimed.command.attempts == 1
    assert claimed.secret == secret

    retry = broker.mark_retry(
        claimed.command.id,
        delay=timedelta(seconds=30),
        error_code="broker_unavailable",
        error_detail="connection refused\nretrying",
        now=NOW,
    )
    assert retry.state == BrokerControlState.RETRYING.value
    assert retry.error_detail == "connection refused retrying"
    assert broker.claim_next(now=NOW + timedelta(seconds=29)) is None

    second_claim = broker.claim_next(now=NOW + timedelta(seconds=30))
    assert second_claim is not None
    assert second_claim.command.attempts == 2
    assert second_claim.secret == secret

    applied = broker.mark_applied(
        second_claim.command.id,
        now=NOW + timedelta(seconds=31),
    )
    assert applied.state == BrokerControlState.APPLIED.value
    assert applied.applied_at is not None
    assert broker.claim_next(now=NOW + timedelta(minutes=1)) is None

    history = broker.history(
        organization_id=ORGANIZATION_A,
        node_id="edge-01",
    )
    assert [row.id for row in history] == [first.command.id]
    database.dispose()


def test_deduplication_conflict_is_rejected(tmp_path: Path) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)
    enqueue_provision(broker, provisioned)

    with pytest.raises(BrokerControlConflictError, match="bound to another command"):
        enqueue_provision(
            broker,
            provisioned,
            command_sha256="b" * 64,
        )

    database.dispose()


def test_disable_command_contains_no_secret(tmp_path: Path) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)

    stored = broker.enqueue(
        organization_id=ORGANIZATION_A,
        node_record_id=provisioned.node.id,
        node_id=provisioned.node.node_id,
        operation=BrokerControlOperation.DISABLE,
        deduplication_key="broker-disable-edge-01",
        command_sha256="c" * 64,
        available_at=NOW,
    )
    claimed = broker.claim_next(now=NOW)

    assert stored.command.secret_ciphertext is None
    assert stored.command.secret_nonce is None
    assert stored.command.secret_key_id is None
    assert claimed is not None
    assert claimed.secret is None
    database.dispose()


def test_corrupted_ciphertext_fails_closed_and_is_terminal(tmp_path: Path) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)
    stored = enqueue_provision(broker, provisioned)

    with Session(database.engine) as session:
        row = session.scalar(
            select(CentralNodeBrokerCommand).where(
                CentralNodeBrokerCommand.id == stored.command.id
            )
        )
        assert row is not None
        ciphertext = bytearray(base64.urlsafe_b64decode(row.secret_ciphertext or ""))
        ciphertext[-1] ^= 1
        row.secret_ciphertext = base64.urlsafe_b64encode(ciphertext).decode("ascii")
        session.commit()

    with pytest.raises(BrokerControlEnvelopeError, match="failed authentication"):
        broker.claim_next(now=NOW)

    with Session(database.engine) as session:
        row = session.get(CentralNodeBrokerCommand, stored.command.id)
        assert row is not None
        assert row.state == BrokerControlState.FAILED.value
        assert row.error_code == BrokerControlEnvelopeError.code
        assert row.error_detail == (
            "encrypted broker-control secret could not be authenticated"
        )
        assert provisioned.secret not in (row.error_detail or "")

    assert broker.claim_next(now=NOW + timedelta(days=1)) is None
    database.dispose()


@pytest.mark.parametrize(
    ("operation", "secret"),
    [
        (BrokerControlOperation.PROVISION, None),
        (BrokerControlOperation.ROTATE, None),
        (BrokerControlOperation.DISABLE, "forbidden"),
        (BrokerControlOperation.DELETE, "forbidden"),
    ],
)
def test_operation_secret_contract_is_enforced(
    tmp_path: Path,
    operation: BrokerControlOperation,
    secret: str | None,
) -> None:
    nodes, broker, database = build_repositories(tmp_path)
    provisioned = provision_node(nodes)

    with pytest.raises(ValueError):
        broker.enqueue(
            organization_id=ORGANIZATION_A,
            node_record_id=provisioned.node.id,
            node_id=provisioned.node.node_id,
            operation=operation,
            deduplication_key=f"invalid-{operation.value}",
            command_sha256="d" * 64,
            secret=secret,
            available_at=NOW,
        )

    database.dispose()
