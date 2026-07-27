from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.broker_api import create_broker_control_router
from app.nodes.broker_control import BrokerControlSecretCipher
from app.nodes.broker_node_repository import BrokerSynchronizedNodeRepository
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.domain import ProvisionNodeCommand
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from tests.test_report_api import (
    ORGANIZATION_A,
    ORGANIZATION_B,
    TestSecurityDependencies,
    headers,
)


ROLES = frozenset({Role.LABORATORY_MANAGER})


def seed_organizations(database: Database) -> None:
    with Session(database.engine) as session:
        session.add_all(
            [
                SecurityOrganization(id=ORGANIZATION_A, slug="org-a", name="Org A"),
                SecurityOrganization(id=ORGANIZATION_B, slug="org-b", name="Org B"),
            ]
        )
        session.commit()


def provision(nodes: NodeRepository) -> str:
    stored = nodes.for_organization(ORGANIZATION_A).provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    assert stored.secret is not None
    return stored.secret


def build_client(
    tmp_path: Path,
) -> tuple[
    TestClient,
    BrokerSynchronizedNodeRepository,
    BrokerControlRepository,
    Database,
]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-api.db'}")
    database.create_schema()
    seed_organizations(database)
    broker = BrokerControlRepository(
        database,
        BrokerControlSecretCipher(bytes(range(32)), key_id="broker-key-v1"),
    )
    nodes = BrokerSynchronizedNodeRepository(
        database,
        broker_control_repository=broker,
    )
    app = FastAPI()
    app.include_router(
        create_broker_control_router(
            nodes,
            broker,
            TestSecurityDependencies(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app), nodes, broker, database


def test_broker_reconciliation_status_history_and_isolation(tmp_path: Path) -> None:
    client, nodes, broker, database = build_client(tmp_path)
    secret = provision(nodes)

    pending = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(role=Role.VIEWER),
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["enabled"] is True
    assert pending.json()["desired_state"] == "provisioned"
    assert pending.json()["synchronization"] == "pending"
    assert pending.json()["synchronized"] is False
    assert len(pending.json()["commands"]) == 1
    serialized = pending.text
    for forbidden in (
        secret,
        "secret_ciphertext",
        "secret_nonce",
        "secret_key_id",
        "deduplication_key",
        "command_sha256",
    ):
        assert forbidden not in serialized

    claimed = broker.claim_next()
    assert claimed is not None
    broker.mark_applied(claimed.command.id)

    applied = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(role=Role.VIEWER),
    )
    assert applied.status_code == 200
    assert applied.json()["synchronization"] == "applied"
    assert applied.json()["synchronized"] is True
    assert applied.json()["latest_command"]["operation"] == "provision"

    scoped = nodes.for_organization(ORGANIZATION_A)
    scoped.activate(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="commissioning approved",
    )
    active = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(role=Role.VIEWER),
    )
    assert active.json()["desired_state"] == "enabled"
    assert active.json()["synchronized"] is True

    scoped.suspend(
        "edge-01",
        actor_subject="manager-a",
        actor_identity_id=None,
        actor_roles=ROLES,
        reason="maintenance",
    )
    suspended = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(role=Role.VIEWER),
    )
    assert suspended.json()["desired_state"] == "disabled"
    assert suspended.json()["synchronization"] == "pending"
    assert suspended.json()["latest_command"]["operation"] == "disable"

    foreign = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(ORGANIZATION_B, role=Role.VIEWER),
    )
    assert foreign.status_code == 404
    database.dispose()


def test_broker_reconciliation_reports_disabled_runtime(tmp_path: Path) -> None:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-disabled.db'}")
    database.create_schema()
    seed_organizations(database)
    nodes = NodeRepository(database)
    provision(nodes)
    app = FastAPI()
    app.include_router(
        create_broker_control_router(
            nodes,
            None,
            TestSecurityDependencies(),  # type: ignore[arg-type]
        )
    )
    client = TestClient(app)

    response = client.get(
        "/api/v1/nodes/edge-01/broker-control",
        headers=headers(role=Role.VIEWER),
    )
    assert response.status_code == 200
    assert response.json() == {
        "node_id": "edge-01",
        "lifecycle_state": "pending",
        "enabled": False,
        "desired_state": "provisioned",
        "synchronization": "disabled",
        "synchronized": False,
        "latest_command": None,
        "commands": [],
    }
    database.dispose()
