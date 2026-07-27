from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.broker_crypto import BrokerCommandCipher, broker_secret_context
from app.nodes.broker_models import CentralNodeBrokerCommand
from app.nodes.domain import NodeState
from app.nodes.models import CentralNode, CentralNodeCredential


class BrokerCommandRepositoryError(RuntimeError):
    code = "broker_command_repository_error"


class BrokerCommandIdempotencyError(BrokerCommandRepositoryError):
    code = "broker_command_idempotency_conflict"


class BrokerCommandNotFoundError(BrokerCommandRepositoryError):
    code = "broker_command_not_found"


class BrokerCommandOutbox:
    def __init__(
        self,
        database: Database,
        cipher: BrokerCommandCipher,
        *,
        max_attempts: int = 8,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("broker command max_attempts must be positive")
        self._database = database
        self._engine = database.engine
        self._cipher = cipher
        self._max_attempts = max_attempts

    @property
    def key_id(self) -> str:
        return self._cipher.key_id

    def enqueue_upsert(
        self,
        session: Session,
        *,
        node: CentralNode,
        credential: CentralNodeCredential,
        secret: str,
        command_key: str,
        actor_subject: str,
        reason: str,
    ) -> CentralNodeBrokerCommand:
        command_type = "upsert_credential"
        desired_enabled = NodeState(node.state) is not NodeState.SUSPENDED
        context = broker_secret_context(
            organization_id=node.organization_id,
            node_record_id=node.id,
            credential_id=credential.id,
            command_type=command_type,
        )
        encrypted = self._cipher.encrypt(secret, context=context)
        command_sha256 = _command_digest(
            command_type=command_type,
            organization_id=node.organization_id,
            node_record_id=node.id,
            credential_id=credential.id,
            credential_generation=credential.generation,
            credential_hash=credential.secret_hash,
            desired_enabled=desired_enabled,
        )
        existing = self._command_by_key(session, node.organization_id, command_key)
        if existing is not None:
            if existing.command_sha256 != command_sha256:
                raise BrokerCommandIdempotencyError(
                    "broker command key is bound to a different command"
                )
            return existing
        now = datetime.now(UTC)
        command = CentralNodeBrokerCommand(
            id=str(uuid4()),
            organization_id=node.organization_id,
            node_record_id=node.id,
            credential_id=credential.id,
            command_type=command_type,
            command_key=_required_text(command_key, "command_key", 160),
            command_sha256=command_sha256,
            username=_node_username(node.organization_id, node.node_id),
            client_id=_node_client_id(node.organization_id, node.node_id),
            credential_generation=credential.generation,
            desired_enabled=desired_enabled,
            secret_ciphertext=encrypted.ciphertext,
            secret_nonce=encrypted.nonce,
            encryption_key_id=encrypted.key_id,
            state="pending",
            attempts=0,
            max_attempts=self._max_attempts,
            available_at=now,
            actor_subject=_required_text(actor_subject, "actor_subject", 255),
            reason=_required_text(reason, "reason", 1024),
            created_at=now,
            updated_at=now,
        )
        session.add(command)
        session.flush()
        return command

    def enqueue_enabled_state(
        self,
        session: Session,
        *,
        node: CentralNode,
        enabled: bool,
        command_key: str,
        actor_subject: str,
        reason: str,
    ) -> CentralNodeBrokerCommand:
        command_type = "enable_client" if enabled else "disable_client"
        command_sha256 = _command_digest(
            command_type=command_type,
            organization_id=node.organization_id,
            node_record_id=node.id,
            credential_id=None,
            credential_generation=None,
            credential_hash=None,
            desired_enabled=enabled,
        )
        existing = self._command_by_key(session, node.organization_id, command_key)
        if existing is not None:
            if existing.command_sha256 != command_sha256:
                raise BrokerCommandIdempotencyError(
                    "broker command key is bound to a different command"
                )
            return existing
        now = datetime.now(UTC)
        command = CentralNodeBrokerCommand(
            id=str(uuid4()),
            organization_id=node.organization_id,
            node_record_id=node.id,
            credential_id=None,
            command_type=command_type,
            command_key=_required_text(command_key, "command_key", 160),
            command_sha256=command_sha256,
            username=_node_username(node.organization_id, node.node_id),
            client_id=_node_client_id(node.organization_id, node.node_id),
            credential_generation=None,
            desired_enabled=enabled,
            state="pending",
            attempts=0,
            max_attempts=self._max_attempts,
            available_at=now,
            actor_subject=_required_text(actor_subject, "actor_subject", 255),
            reason=_required_text(reason, "reason", 1024),
            created_at=now,
            updated_at=now,
        )
        session.add(command)
        session.flush()
        return command

    def latest_for_node(
        self,
        *,
        organization_id: str,
        node_record_id: str,
    ) -> CentralNodeBrokerCommand | None:
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.scalar(
                select(CentralNodeBrokerCommand)
                .where(
                    CentralNodeBrokerCommand.organization_id == organization_id,
                    CentralNodeBrokerCommand.node_record_id == node_record_id,
                )
                .order_by(CentralNodeBrokerCommand.created_at.desc())
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row

    def history_for_node(
        self,
        *,
        organization_id: str,
        node_record_id: str,
        limit: int = 100,
    ) -> list[CentralNodeBrokerCommand]:
        if limit < 1 or limit > 1000:
            raise ValueError("broker command history limit must be between 1 and 1000")
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(CentralNodeBrokerCommand)
                    .where(
                        CentralNodeBrokerCommand.organization_id == organization_id,
                        CentralNodeBrokerCommand.node_record_id == node_record_id,
                    )
                    .order_by(CentralNodeBrokerCommand.created_at.desc())
                    .limit(limit)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def claim_next(
        self,
        *,
        lease_seconds: float,
        observed_at: datetime | None = None,
    ) -> CentralNodeBrokerCommand | None:
        if lease_seconds <= 0:
            raise ValueError("broker command lease must be positive")
        now = _aware_utc(observed_at or datetime.now(UTC))
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    row = session.scalar(
                        select(CentralNodeBrokerCommand)
                        .where(
                            CentralNodeBrokerCommand.state.in_(("pending", "retrying")),
                            CentralNodeBrokerCommand.available_at <= now,
                            or_(
                                CentralNodeBrokerCommand.lease_expires_at.is_(None),
                                CentralNodeBrokerCommand.lease_expires_at <= now,
                            ),
                        )
                        .order_by(
                            CentralNodeBrokerCommand.available_at,
                            CentralNodeBrokerCommand.created_at,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if row is None:
                        return None
                    row.state = "retrying"
                    row.attempts += 1
                    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    row.updated_at = now
                    session.flush()
            except IntegrityError as error:
                raise BrokerCommandRepositoryError(
                    "broker command claim conflicted with persistence"
                ) from error
            session.expunge(row)
            return row

    def decrypt_secret(self, command: CentralNodeBrokerCommand) -> str:
        if (
            command.credential_id is None
            or command.secret_ciphertext is None
            or command.secret_nonce is None
            or command.encryption_key_id is None
        ):
            raise BrokerCommandRepositoryError(
                "broker upsert command does not contain encrypted secret material"
            )
        context = broker_secret_context(
            organization_id=command.organization_id,
            node_record_id=command.node_record_id,
            credential_id=command.credential_id,
            command_type=command.command_type,
        )
        return self._cipher.decrypt(
            ciphertext=command.secret_ciphertext,
            nonce=command.secret_nonce,
            context=context,
            key_id=command.encryption_key_id,
        )

    def mark_applied(
        self,
        command_id: str,
        *,
        observed_at: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        now = _aware_utc(observed_at or datetime.now(UTC))
        return self._finish(
            command_id,
            state="applied",
            observed_at=now,
            available_at=now,
            error_code=None,
            error_summary=None,
        )

    def mark_retry(
        self,
        command_id: str,
        *,
        retry_at: datetime,
        error_code: str,
        error_summary: str,
        observed_at: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        return self._finish(
            command_id,
            state="retrying",
            observed_at=_aware_utc(observed_at or datetime.now(UTC)),
            available_at=_aware_utc(retry_at),
            error_code=error_code,
            error_summary=error_summary,
        )

    def mark_failed(
        self,
        command_id: str,
        *,
        error_code: str,
        error_summary: str,
        observed_at: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        now = _aware_utc(observed_at or datetime.now(UTC))
        return self._finish(
            command_id,
            state="failed",
            observed_at=now,
            available_at=now,
            error_code=error_code,
            error_summary=error_summary,
        )

    def _finish(
        self,
        command_id: str,
        *,
        state: str,
        observed_at: datetime,
        available_at: datetime,
        error_code: str | None,
        error_summary: str | None,
    ) -> CentralNodeBrokerCommand:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.scalar(
                    select(CentralNodeBrokerCommand)
                    .where(CentralNodeBrokerCommand.id == command_id)
                    .with_for_update()
                )
                if row is None:
                    raise BrokerCommandNotFoundError(
                        f"broker command {command_id!r} was not found"
                    )
                row.state = state
                row.available_at = available_at
                row.lease_expires_at = None
                row.applied_at = observed_at if state == "applied" else None
                row.last_error_code = error_code
                row.last_error_summary = error_summary
                row.updated_at = observed_at
                session.flush()
            session.expunge(row)
            return row

    @staticmethod
    def _command_by_key(
        session: Session,
        organization_id: str,
        command_key: str,
    ) -> CentralNodeBrokerCommand | None:
        return session.scalar(
            select(CentralNodeBrokerCommand).where(
                CentralNodeBrokerCommand.organization_id == organization_id,
                CentralNodeBrokerCommand.command_key
                == _required_text(command_key, "command_key", 160),
            )
        )


def _command_digest(
    *,
    command_type: str,
    organization_id: str,
    node_record_id: str,
    credential_id: str | None,
    credential_generation: int | None,
    credential_hash: str | None,
    desired_enabled: bool,
) -> str:
    payload = json.dumps(
        {
            "command_type": command_type,
            "organization_id": organization_id,
            "node_record_id": node_record_id,
            "credential_id": credential_id,
            "credential_generation": credential_generation,
            "credential_hash": credential_hash,
            "desired_enabled": desired_enabled,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _node_username(organization_id: str, node_id: str) -> str:
    return f"node:{organization_id}:{node_id}"


def _node_client_id(organization_id: str, node_id: str) -> str:
    return f"nexolab-{organization_id}-{node_id}"


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
