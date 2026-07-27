from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.broker_control import BrokerControlOperation
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.domain import (
    ClockStatus,
    NodeState,
    NodeTopicStream,
    ProvisionNodeCommand,
    RotateNodeCredentialCommand,
    authorize_node_topic,
    canonical_sha256,
    classify_clock_offset,
    generate_provisioning_secret,
    hash_provisioning_secret,
    normalize_node_id,
    transition_node_state,
    verify_provisioning_secret,
)
from app.nodes.models import CentralNode, CentralNodeCredential
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository


class NodeRepositoryError(RuntimeError):
    code = "node_repository_error"


class NodeNotFoundError(NodeRepositoryError):
    code = "node_not_found"


class NodeConflictError(NodeRepositoryError):
    code = "node_conflict"


class NodeIdempotencyConflictError(NodeRepositoryError):
    code = "node_idempotency_conflict"


class NodeAuthenticationError(NodeRepositoryError):
    code = "node_authentication_failed"


@dataclass(frozen=True, slots=True)
class ProvisionedNode:
    node: CentralNode
    credential: CentralNodeCredential
    secret: str | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class RotatedNodeCredential:
    node: CentralNode
    credential: CentralNodeCredential
    secret: str | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class NodePublishAuthorization:
    node: CentralNode
    credential: CentralNodeCredential
    stream: NodeTopicStream
    clock_status: ClockStatus
    clock_offset_ms: int | None


class NodeRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
        broker_control_repository: BrokerControlRepository | None = None,
        organization_id: str | None = None,
    ) -> None:
        self._database = database
        self._engine = database.engine
        self._security_repository = security_repository
        self._broker_control_repository = broker_control_repository
        self._organization_id = organization_id

    def for_organization(self, organization_id: str) -> "NodeRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return NodeRepository(
            self._database,
            security_repository=self._security_repository,
            broker_control_repository=self._broker_control_repository,
            organization_id=normalized,
        )

    def list_nodes(self, *, state: NodeState | str | None = None) -> list[CentralNode]:
        statement = (
            select(CentralNode)
            .where(CentralNode.organization_id == self._scope())
            .order_by(CentralNode.node_id)
        )
        if state is not None:
            statement = statement.where(CentralNode.state == NodeState(state).value)
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            for row in rows:
                session.expunge(row)
            return rows

    def get_node(self, node_id: str) -> CentralNode:
        normalized = normalize_node_id(node_id)
        with Session(self._engine, expire_on_commit=False) as session:
            row = self._node(session, normalized)
            session.expunge(row)
            return row

    def current_credential(self, node_id: str) -> CentralNodeCredential | None:
        normalized = normalize_node_id(node_id)
        with Session(self._engine, expire_on_commit=False) as session:
            node = self._node(session, normalized)
            row = self._active_credential(session, node.id)
            if row is not None:
                session.expunge(row)
            return row

    def provision(
        self,
        command: ProvisionNodeCommand,
        *,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
    ) -> ProvisionedNode:
        organization_id = self._scope()
        node_id = normalize_node_id(command.node_id)
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    replay = self._credential_by_idempotency(
                        session,
                        command.idempotency_key,
                    )
                    if replay is not None:
                        if replay.command_sha256 != command.command_sha256:
                            raise NodeIdempotencyConflictError(
                                "provisioning idempotency key is bound to "
                                "a different command"
                            )
                        node = session.get(CentralNode, replay.node_record_id)
                        if node is None or node.organization_id != organization_id:
                            raise NodeRepositoryError(
                                "provisioning replay references a missing node"
                            )
                        session.expunge(replay)
                        session.expunge(node)
                        return ProvisionedNode(node, replay, None, True)

                    existing = session.scalar(
                        select(CentralNode).where(
                            CentralNode.organization_id == organization_id,
                            CentralNode.node_id == node_id,
                        )
                    )
                    if existing is not None:
                        raise NodeConflictError(f"node {node_id!r} already exists")

                    now = datetime.now(UTC)
                    node = CentralNode(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        node_id=node_id,
                        display_name=command.display_name.strip(),
                        state=NodeState.PENDING.value,
                        state_reason="awaiting activation",
                        clock_warning_ms=command.clock_warning_ms,
                        clock_critical_ms=command.clock_critical_ms,
                        clock_status=ClockStatus.UNKNOWN.value,
                        created_by=command.actor_subject.strip(),
                        created_at=now,
                        updated_at=now,
                    )
                    secret = generate_provisioning_secret()
                    salt, secret_hash, fingerprint = hash_provisioning_secret(secret)
                    credential = CentralNodeCredential(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        node_record_id=node.id,
                        generation=1,
                        secret_salt=salt,
                        secret_hash=secret_hash,
                        secret_fingerprint=fingerprint,
                        idempotency_key=command.idempotency_key.strip(),
                        command_sha256=command.command_sha256,
                        issued_by=command.actor_subject.strip(),
                        issued_at=now,
                    )
                    session.add_all([node, credential])
                    session.flush()
                    self._enqueue_broker_command(
                        session,
                        node=node,
                        operation=BrokerControlOperation.PROVISION,
                        credential=credential,
                        secret=secret,
                        deduplication_key=(
                            f"node:{node.id}:credential:"
                            f"{credential.generation}:provision"
                        ),
                        command_sha256=canonical_sha256(
                            {
                                "operation": BrokerControlOperation.PROVISION.value,
                                "organization_id": organization_id,
                                "node_record_id": node.id,
                                "node_id": node.node_id,
                                "credential_id": credential.id,
                                "credential_generation": credential.generation,
                            }
                        ),
                        available_at=now,
                    )
                    self._audit(
                        session,
                        node=node,
                        identity_id=actor_identity_id,
                        actor_subject=command.actor_subject,
                        actor_roles=actor_roles,
                        action="node.provisioned",
                        reason="initial node provisioning",
                        after_snapshot={
                            "node_id": node.node_id,
                            "display_name": node.display_name,
                            "state": node.state,
                            "credential_generation": credential.generation,
                            "credential_fingerprint": credential.secret_fingerprint,
                            "clock_warning_ms": node.clock_warning_ms,
                            "clock_critical_ms": node.clock_critical_ms,
                            "broker_sync": "pending",
                        },
                    )
            except IntegrityError as error:
                raise NodeConflictError(
                    "node or provisioning key already exists"
                ) from error
            session.expunge(credential)
            session.expunge(node)
            return ProvisionedNode(node, credential, secret, False)

    def rotate_credential(
        self,
        command: RotateNodeCredentialCommand,
        *,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
    ) -> RotatedNodeCredential:
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    replay = self._credential_by_idempotency(
                        session,
                        command.idempotency_key,
                    )
                    if replay is not None:
                        if replay.command_sha256 != command.command_sha256:
                            raise NodeIdempotencyConflictError(
                                "credential idempotency key is bound to "
                                "a different command"
                            )
                        node = session.get(CentralNode, replay.node_record_id)
                        if node is None or node.organization_id != self._scope():
                            raise NodeRepositoryError(
                                "credential replay references a missing node"
                            )
                        session.expunge(replay)
                        session.expunge(node)
                        return RotatedNodeCredential(node, replay, None, True)

                    node = self._node_for_update(session, command.node_id)
                    if NodeState(node.state) is NodeState.REVOKED:
                        raise NodeConflictError(
                            "revoked node credentials cannot be rotated"
                        )
                    now = datetime.now(UTC)
                    active = list(
                        session.scalars(
                            select(CentralNodeCredential).where(
                                CentralNodeCredential.organization_id == self._scope(),
                                CentralNodeCredential.node_record_id == node.id,
                                CentralNodeCredential.revoked_at.is_(None),
                            )
                        )
                    )
                    for row in active:
                        row.revoked_at = now
                        row.revoked_by = command.actor_subject.strip()
                        row.revocation_reason = "credential rotation"
                    generation = max((row.generation for row in active), default=0)
                    historical_max = session.scalar(
                        select(CentralNodeCredential.generation)
                        .where(CentralNodeCredential.node_record_id == node.id)
                        .order_by(CentralNodeCredential.generation.desc())
                        .limit(1)
                    )
                    generation = max(generation, int(historical_max or 0)) + 1
                    secret = generate_provisioning_secret()
                    salt, secret_hash, fingerprint = hash_provisioning_secret(secret)
                    credential = CentralNodeCredential(
                        id=str(uuid4()),
                        organization_id=self._scope(),
                        node_record_id=node.id,
                        generation=generation,
                        secret_salt=salt,
                        secret_hash=secret_hash,
                        secret_fingerprint=fingerprint,
                        idempotency_key=command.idempotency_key.strip(),
                        command_sha256=command.command_sha256,
                        issued_by=command.actor_subject.strip(),
                        issued_at=now,
                    )
                    session.add(credential)
                    node.updated_at = now
                    session.flush()
                    self._enqueue_broker_command(
                        session,
                        node=node,
                        operation=BrokerControlOperation.ROTATE,
                        credential=credential,
                        secret=secret,
                        deduplication_key=(
                            f"node:{node.id}:credential:{credential.generation}:rotate"
                        ),
                        command_sha256=canonical_sha256(
                            {
                                "operation": BrokerControlOperation.ROTATE.value,
                                "organization_id": node.organization_id,
                                "node_record_id": node.id,
                                "node_id": node.node_id,
                                "credential_id": credential.id,
                                "credential_generation": credential.generation,
                            }
                        ),
                        available_at=now,
                    )
                    self._audit(
                        session,
                        node=node,
                        identity_id=actor_identity_id,
                        actor_subject=command.actor_subject,
                        actor_roles=actor_roles,
                        action="node.credential.rotated",
                        reason=command.reason,
                        after_snapshot={
                            "node_id": node.node_id,
                            "credential_generation": credential.generation,
                            "credential_fingerprint": credential.secret_fingerprint,
                            "previous_credentials_revoked": len(active),
                            "broker_sync": "pending",
                        },
                    )
            except IntegrityError as error:
                raise NodeConflictError(
                    "credential rotation conflicted with existing state"
                ) from error
            session.expunge(credential)
            session.expunge(node)
            return RotatedNodeCredential(node, credential, secret, False)

    def activate(
        self,
        node_id: str,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str,
    ) -> CentralNode:
        return self._change_state(
            node_id,
            NodeState.ACTIVE,
            actor_subject=actor_subject,
            actor_identity_id=actor_identity_id,
            actor_roles=actor_roles,
            reason=reason,
        )

    def suspend(
        self,
        node_id: str,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str,
    ) -> CentralNode:
        return self._change_state(
            node_id,
            NodeState.SUSPENDED,
            actor_subject=actor_subject,
            actor_identity_id=actor_identity_id,
            actor_roles=actor_roles,
            reason=reason,
        )

    def revoke(
        self,
        node_id: str,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str,
    ) -> CentralNode:
        return self._change_state(
            node_id,
            NodeState.REVOKED,
            actor_subject=actor_subject,
            actor_identity_id=actor_identity_id,
            actor_roles=actor_roles,
            reason=reason,
        )

    def authenticate_publish(
        self,
        *,
        node_id: str,
        secret: str,
        topic: str,
        observed_at: datetime,
        node_time: datetime | None = None,
    ) -> NodePublishAuthorization:
        observed = _aware_utc(observed_at)
        node_clock = None if node_time is None else _aware_utc(node_time)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                try:
                    node = self._node_for_update(session, node_id)
                except NodeNotFoundError as error:
                    raise NodeAuthenticationError(
                        "node authentication failed"
                    ) from error
                if NodeState(node.state) is not NodeState.ACTIVE:
                    raise NodeAuthenticationError("node authentication failed")
                credential = self._active_credential(session, node.id)
                if credential is None or not verify_provisioning_secret(
                    secret,
                    salt_hex=credential.secret_salt,
                    expected_hash_hex=credential.secret_hash,
                ):
                    raise NodeAuthenticationError("node authentication failed")
                try:
                    stream = authorize_node_topic(
                        organization_id=self._scope(),
                        node_id=node.node_id,
                        topic=topic,
                    )
                except ValueError as error:
                    raise NodeAuthenticationError(
                        "node authentication failed"
                    ) from error
                offset_ms = (
                    None
                    if node_clock is None
                    else round((node_clock - observed).total_seconds() * 1000)
                )
                clock_status = classify_clock_offset(
                    offset_ms,
                    warning_ms=node.clock_warning_ms,
                    critical_ms=node.clock_critical_ms,
                )
                node.last_seen_at = observed
                node.last_clock_offset_ms = offset_ms
                node.clock_status = clock_status.value
                node.clock_observed_at = observed if node_clock is not None else None
                node.updated_at = observed
                session.flush()
            session.expunge(credential)
            session.expunge(node)
            return NodePublishAuthorization(
                node=node,
                credential=credential,
                stream=stream,
                clock_status=clock_status,
                clock_offset_ms=offset_ms,
            )

    def _change_state(
        self,
        node_id: str,
        target: NodeState,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str,
    ) -> CentralNode:
        normalized_reason = _required_text(reason, "reason", 1024)
        actor = _required_text(actor_subject, "actor_subject", 255)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                node = self._node_for_update(session, node_id)
                source = NodeState(node.state)
                if source is target:
                    session.expunge(node)
                    return node
                transition_node_state(source, target)
                now = datetime.now(UTC)
                before = {"state": source.value, "state_reason": node.state_reason}
                node.state = target.value
                node.state_reason = normalized_reason
                node.updated_at = now
                if target is NodeState.REVOKED:
                    active = list(
                        session.scalars(
                            select(CentralNodeCredential).where(
                                CentralNodeCredential.organization_id == self._scope(),
                                CentralNodeCredential.node_record_id == node.id,
                                CentralNodeCredential.revoked_at.is_(None),
                            )
                        )
                    )
                    for credential in active:
                        credential.revoked_at = now
                        credential.revoked_by = actor
                        credential.revocation_reason = normalized_reason
                session.flush()
                broker_operation = _broker_operation_for_state(target)
                if broker_operation is not None:
                    command_sha256 = canonical_sha256(
                        {
                            "operation": broker_operation.value,
                            "organization_id": node.organization_id,
                            "node_record_id": node.id,
                            "node_id": node.node_id,
                            "source_state": source.value,
                            "target_state": target.value,
                            "actor_subject": actor,
                            "reason": normalized_reason,
                            "transitioned_at": now.isoformat(),
                        }
                    )
                    self._enqueue_broker_command(
                        session,
                        node=node,
                        operation=broker_operation,
                        credential=None,
                        secret=None,
                        deduplication_key=(
                            f"node:{node.id}:state:{target.value}:"
                            f"{command_sha256[:24]}"
                        ),
                        command_sha256=command_sha256,
                        available_at=now,
                    )
                self._audit(
                    session,
                    node=node,
                    identity_id=actor_identity_id,
                    actor_subject=actor,
                    actor_roles=actor_roles,
                    action=f"node.{target.value}",
                    reason=normalized_reason,
                    before_snapshot=before,
                    after_snapshot={
                        "state": node.state,
                        "state_reason": node.state_reason,
                        **(
                            {"broker_sync": "pending"}
                            if broker_operation is not None
                            else {}
                        ),
                    },
                )
            session.expunge(node)
            return node

    def _enqueue_broker_command(
        self,
        session: Session,
        *,
        node: CentralNode,
        operation: BrokerControlOperation,
        credential: CentralNodeCredential | None,
        secret: str | None,
        deduplication_key: str,
        command_sha256: str,
        available_at: datetime,
    ) -> None:
        if self._broker_control_repository is None:
            return
        self._broker_control_repository.enqueue_in_session(
            session,
            organization_id=node.organization_id,
            node_record_id=node.id,
            node_id=node.node_id,
            credential_id=None if credential is None else credential.id,
            operation=operation,
            deduplication_key=deduplication_key,
            command_sha256=command_sha256,
            secret=secret,
            available_at=available_at,
        )

    def _scope(self) -> str:
        if self._organization_id is None:
            raise NodeRepositoryError("organization scope is required")
        return self._organization_id

    def _node(self, session: Session, node_id: str) -> CentralNode:
        row = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == self._scope(),
                CentralNode.node_id == normalize_node_id(node_id),
            )
        )
        if row is None:
            raise NodeNotFoundError(f"node {node_id!r} was not found")
        return row

    def _node_for_update(self, session: Session, node_id: str) -> CentralNode:
        row = session.scalar(
            select(CentralNode)
            .where(
                CentralNode.organization_id == self._scope(),
                CentralNode.node_id == normalize_node_id(node_id),
            )
            .with_for_update()
        )
        if row is None:
            raise NodeNotFoundError(f"node {node_id!r} was not found")
        return row

    def _active_credential(
        self,
        session: Session,
        node_record_id: str,
    ) -> CentralNodeCredential | None:
        return session.scalar(
            select(CentralNodeCredential)
            .where(
                CentralNodeCredential.organization_id == self._scope(),
                CentralNodeCredential.node_record_id == node_record_id,
                CentralNodeCredential.revoked_at.is_(None),
            )
            .order_by(CentralNodeCredential.generation.desc())
            .limit(1)
        )

    def _credential_by_idempotency(
        self,
        session: Session,
        idempotency_key: str,
    ) -> CentralNodeCredential | None:
        return session.scalar(
            select(CentralNodeCredential).where(
                CentralNodeCredential.organization_id == self._scope(),
                CentralNodeCredential.idempotency_key
                == _required_text(idempotency_key, "idempotency_key", 128),
            )
        )

    def _audit(
        self,
        session: Session,
        *,
        node: CentralNode,
        identity_id: str | None,
        actor_subject: str,
        actor_roles: frozenset[Role],
        action: str,
        reason: str,
        after_snapshot: dict[str, object],
        before_snapshot: dict[str, object] | None = None,
    ) -> None:
        if self._security_repository is None:
            return
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=node.organization_id,
                actor_identity_id=identity_id,
                actor_subject=actor_subject,
                actor_roles=actor_roles,
                action=action,
                entity_type="central_node",
                entity_id=node.id,
                before_snapshot=before_snapshot,
                after_snapshot={"node_id": node.node_id, **after_snapshot},
                reason=reason,
            ),
            session=session,
        )


def _broker_operation_for_state(
    target: NodeState,
) -> BrokerControlOperation | None:
    if target is NodeState.SUSPENDED:
        return BrokerControlOperation.DISABLE
    if target is NodeState.REVOKED:
        return BrokerControlOperation.DELETE
    return None


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)
