from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.nodes.broker_adapter import BrokerControlAdapterError
from app.nodes.broker_control import (
    BrokerControlOperation,
    BrokerControlSecretCipher,
    BrokerControlState,
)
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.broker_worker import BrokerControlWorker
from app.nodes.domain import ProvisionNodeCommand
from app.nodes.repository import NodeRepository
from app.security.authorization import Role
from app.security.models import SecurityOrganization


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)
ROLES = frozenset({Role.LABORATORY_MANAGER})


class RecordingAdapter:
    def __init__(self, outcomes: list[Exception | None] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, str | None]] = []

    def apply(self, command, secret: str | None) -> None:
        self.calls.append((command.id, secret))
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome is not None:
                raise outcome


def build_stack(tmp_path: Path):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'broker-worker.db'}")
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

    nodes = NodeRepository(database).for_organization(ORGANIZATION_ID)
    provisioned = nodes.provision(
        ProvisionNodeCommand(
            node_id="edge-01",
            display_name="Primary edge node",
            idempotency_key="provision-edge-01",
            actor_subject="manager-a",
        ),
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    cipher = BrokerControlSecretCipher(bytes(range(32)), key_id="broker-key-v1")
    repository = BrokerControlRepository(database, cipher)
    return database, repository, provisioned


def enqueue_provision(repository: BrokerControlRepository, provisioned, *, suffix: str = "1"):
    return repository.enqueue(
        organization_id=ORGANIZATION_ID,
        node_record_id=provisioned.node.id,
        node_id=provisioned.node.node_id,
        credential_id=provisioned.credential.id,
        operation=BrokerControlOperation.PROVISION,
        deduplication_key=f"broker-provision-edge-01-{suffix}",
        command_sha256=(suffix[0] if suffix[0] in "abcdef" else "a") * 64,
        secret=provisioned.secret,
        available_at=NOW,
    )


def build_worker(
    database: Database,
    repository: BrokerControlRepository,
    adapter: RecordingAdapter,
    *,
    max_commands: int = 25,
    max_attempts: int = 3,
) -> BrokerControlWorker:
    return BrokerControlWorker(
        database=database,
        repository=repository,
        adapter=adapter,
        poll_interval_seconds=1,
        max_commands_per_run=max_commands,
        max_attempts=max_attempts,
        retry_initial_seconds=2,
        retry_max_seconds=8,
        stale_lock_seconds=60,
    )


def test_worker_applies_encrypted_command(tmp_path: Path) -> None:
    database, repository, provisioned = build_stack(tmp_path)
    stored = enqueue_provision(repository, provisioned)
    adapter = RecordingAdapter()
    worker = build_worker(database, repository, adapter)

    result = worker.run_once(now=NOW)
    history = repository.history(
        organization_id=ORGANIZATION_ID,
        node_id="edge-01",
    )

    assert result.claimed == 1
    assert result.applied == 1
    assert result.retried == 0
    assert result.failed == 0
    assert adapter.calls == [(stored.command.id, provisioned.secret)]
    assert history[0].state == BrokerControlState.APPLIED.value
    database.dispose()


def test_worker_retries_with_bounded_exponential_delay(tmp_path: Path) -> None:
    database, repository, provisioned = build_stack(tmp_path)
    enqueue_provision(repository, provisioned)
    adapter = RecordingAdapter(
        [
            BrokerControlAdapterError(
                "broker_unavailable",
                "broker administration command failed",
                retryable=True,
            ),
            None,
        ]
    )
    worker = build_worker(database, repository, adapter)

    first = worker.run_once(now=NOW)
    history = repository.history(
        organization_id=ORGANIZATION_ID,
        node_id="edge-01",
    )
    assert first.retried == 1
    assert history[0].state == BrokerControlState.RETRYING.value
    assert history[0].available_at == NOW + timedelta(seconds=2)

    assert worker.run_once(now=NOW + timedelta(seconds=1)).claimed == 0
    second = worker.run_once(now=NOW + timedelta(seconds=2))
    history = repository.history(
        organization_id=ORGANIZATION_ID,
        node_id="edge-01",
    )
    assert second.applied == 1
    assert history[0].attempts == 2
    assert history[0].state == BrokerControlState.APPLIED.value
    database.dispose()


def test_worker_marks_terminal_failure_at_attempt_limit(tmp_path: Path) -> None:
    database, repository, provisioned = build_stack(tmp_path)
    enqueue_provision(repository, provisioned)
    failure = BrokerControlAdapterError(
        "broker_unavailable",
        "broker administration command failed",
        retryable=True,
    )
    adapter = RecordingAdapter([failure, failure])
    worker = build_worker(database, repository, adapter, max_attempts=2)

    assert worker.run_once(now=NOW).retried == 1
    terminal = worker.run_once(now=NOW + timedelta(seconds=2))
    history = repository.history(
        organization_id=ORGANIZATION_ID,
        node_id="edge-01",
    )

    assert terminal.failed == 1
    assert history[0].state == BrokerControlState.FAILED.value
    assert history[0].attempts == 2
    assert history[0].error_code == "broker_unavailable"
    assert provisioned.secret not in (history[0].error_detail or "")
    database.dispose()


def test_worker_recovers_stale_processing_lease_after_restart(tmp_path: Path) -> None:
    database, repository, provisioned = build_stack(tmp_path)
    enqueue_provision(repository, provisioned)
    claimed = repository.claim_next(now=NOW)
    assert claimed is not None
    assert claimed.command.state == BrokerControlState.PROCESSING.value

    adapter = RecordingAdapter()
    worker = build_worker(database, repository, adapter)
    result = worker.run_once(now=NOW + timedelta(seconds=61))
    history = repository.history(
        organization_id=ORGANIZATION_ID,
        node_id="edge-01",
    )

    assert result.recovered == 1
    assert result.claimed == 1
    assert result.applied == 1
    assert history[0].state == BrokerControlState.APPLIED.value
    assert history[0].attempts == 2
    database.dispose()


def test_worker_respects_per_iteration_command_bound(tmp_path: Path) -> None:
    database, repository, provisioned = build_stack(tmp_path)
    for index in range(3):
        repository.enqueue(
            organization_id=ORGANIZATION_ID,
            node_record_id=provisioned.node.id,
            node_id=provisioned.node.node_id,
            operation=BrokerControlOperation.DISABLE,
            deduplication_key=f"disable-edge-01-{index}",
            command_sha256=f"{index + 1}" * 64,
            available_at=NOW,
        )

    adapter = RecordingAdapter()
    worker = build_worker(database, repository, adapter, max_commands=2)
    result = worker.run_once(now=NOW)
    states = [
        row.state
        for row in repository.history(
            organization_id=ORGANIZATION_ID,
            node_id="edge-01",
        )
    ]

    assert result.claimed == 2
    assert result.applied == 2
    assert states.count(BrokerControlState.APPLIED.value) == 2
    assert states.count(BrokerControlState.PENDING.value) == 1
    database.dispose()
