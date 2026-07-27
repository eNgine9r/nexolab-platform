from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.broker_control import (
    BrokerControlCryptoError,
    BrokerControlEnvelope,
    BrokerControlOperation,
    BrokerControlSecretCipher,
    BrokerControlState,
    broker_control_associated_data,
)
from app.nodes.broker_models import CentralNodeBrokerCommand


class BrokerControlRepositoryError(RuntimeError):
    code = "broker_control_repository_error"


class BrokerControlConflictError(BrokerControlRepositoryError):
    code = "broker_control_conflict"


class BrokerControlStateError(BrokerControlRepositoryError):
    code = "broker_control_state_error"


class BrokerControlEnvelopeError(BrokerControlRepositoryError):
    code = "broker_control_envelope_invalid"


@dataclass(frozen=True, slots=True)
class EnqueuedBrokerCommand:
    command: CentralNodeBrokerCommand
    replayed: bool


@dataclass(frozen=True, slots=True)
class ClaimedBrokerCommand:
    command: CentralNodeBrokerCommand
    secret: str | None = field(repr=False)


class BrokerControlRepository:
    def __init__(
        self,
        database: Database,
        cipher: BrokerControlSecretCipher,
    ) -> None:
        self._database = database
        self._engine = database.engine
        self._cipher = cipher

    def enqueue(
        self,
        *,
        organization_id: str,
        node_record_id: str,
        node_id: str,
        operation: BrokerControlOperation | str,
        deduplication_key: str,
        command_sha256: str,
        credential_id: str | None = None,
        secret: str | None = None,
        available_at: datetime | None = None,
    ) -> EnqueuedBrokerCommand:
        normalized_organization = _required_text(
            organization_id,
            "organization_id",
            36,
        )
        normalized_node_record = _required_text(
            node_record_id,
            "node_record_id",
            36,
        )
        normalized_node = _required_text(node_id, "node_id", 64)
        normalized_operation = BrokerControlOperation(operation)
        normalized_deduplication = _required_text(
            deduplication_key,
            "deduplication_key",
            128,
        )
        normalized_digest = _sha256(command_sha256)
        normalized_credential = (
            None
            if credential_id is None
            else _required_text(credential_id, "credential_id", 36)
        )
        _validate_operation_secret(normalized_operation, secret)
        ready_at = _aware_utc(available_at or datetime.now(UTC))

        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    existing = session.scalar(
                        select(CentralNodeBrokerCommand).where(
                            CentralNodeBrokerCommand.organization_id
                            == normalized_organization,
                            CentralNodeBrokerCommand.deduplication_key
                            == normalized_deduplication,
                        )
                    )
                    if existing is not None:
                        if existing.command_sha256 != normalized_digest:
                            raise BrokerControlConflictError(
                                "broker-control deduplication key is bound to another command"
                            )
                        session.expunge(existing)
                        return EnqueuedBrokerCommand(existing, True)

                    command_id = str(uuid4())
                    envelope = (
                        None
                        if secret is None
                        else self._cipher.encrypt(
                            secret,
                            associated_data=broker_control_associated_data(
                                command_id=command_id,
                                organization_id=normalized_organization,
                                node_id=normalized_node,
                                operation=normalized_operation,
                            ),
                        )
                    )
                    row = CentralNodeBrokerCommand(
                        id=command_id,
                        organization_id=normalized_organization,
                        node_record_id=normalized_node_record,
                        node_id=normalized_node,
                        credential_id=normalized_credential,
                        operation=normalized_operation.value,
                        state=BrokerControlState.PENDING.value,
                        deduplication_key=normalized_deduplication,
                        command_sha256=normalized_digest,
                        secret_ciphertext=(
                            None if envelope is None else envelope.ciphertext_b64
                        ),
                        secret_nonce=None if envelope is None else envelope.nonce_b64,
                        secret_key_id=None if envelope is None else envelope.key_id,
                        attempts=0,
                        available_at=ready_at,
                        created_at=ready_at,
                        updated_at=ready_at,
                    )
                    session.add(row)
                    session.flush()
            except IntegrityError as error:
                raise BrokerControlConflictError(
                    "broker-control command conflicts with existing state"
                ) from error
            session.expunge(row)
            return EnqueuedBrokerCommand(row, False)

    def claim_next(
        self,
        *,
        now: datetime | None = None,
    ) -> ClaimedBrokerCommand | None:
        claimed_at = _aware_utc(now or datetime.now(UTC))
        envelope_error: BrokerControlCryptoError | None = None
        row: CentralNodeBrokerCommand | None = None
        secret: str | None = None

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                statement = (
                    select(CentralNodeBrokerCommand)
                    .where(
                        CentralNodeBrokerCommand.state.in_(
                            (
                                BrokerControlState.PENDING.value,
                                BrokerControlState.RETRYING.value,
                            )
                        ),
                        CentralNodeBrokerCommand.available_at <= claimed_at,
                    )
                    .order_by(
                        CentralNodeBrokerCommand.available_at,
                        CentralNodeBrokerCommand.created_at,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                row = session.scalar(statement)
                if row is None:
                    return None

                row.state = BrokerControlState.PROCESSING.value
                row.attempts += 1
                row.locked_at = claimed_at
                row.last_attempt_at = claimed_at
                row.updated_at = claimed_at
                row.error_code = None
                row.error_detail = None
                session.flush()

                if row.secret_ciphertext is not None:
                    try:
                        secret = self._cipher.decrypt(
                            BrokerControlEnvelope(
                                key_id=row.secret_key_id or "",
                                nonce_b64=row.secret_nonce or "",
                                ciphertext_b64=row.secret_ciphertext,
                            ),
                            associated_data=broker_control_associated_data(
                                command_id=row.id,
                                organization_id=row.organization_id,
                                node_id=row.node_id,
                                operation=row.operation,
                            ),
                        )
                    except BrokerControlCryptoError as error:
                        envelope_error = error
                        row.state = BrokerControlState.FAILED.value
                        row.failed_at = claimed_at
                        row.locked_at = None
                        row.error_code = BrokerControlEnvelopeError.code
                        row.error_detail = (
                            "encrypted broker-control secret could not be authenticated"
                        )
                        row.updated_at = claimed_at
                        session.flush()

            if row is not None:
                session.expunge(row)

        if envelope_error is not None:
            raise BrokerControlEnvelopeError(
                "encrypted broker-control command failed authentication"
            ) from envelope_error
        if row is None:
            return None
        return ClaimedBrokerCommand(row, secret)

    def mark_applied(
        self,
        command_id: str,
        *,
        now: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        completed_at = _aware_utc(now or datetime.now(UTC))
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = self._processing_for_update(session, command_id)
                row.state = BrokerControlState.APPLIED.value
                row.applied_at = completed_at
                row.locked_at = None
                row.error_code = None
                row.error_detail = None
                row.updated_at = completed_at
                session.flush()
            session.expunge(row)
            return row

    def mark_retry(
        self,
        command_id: str,
        *,
        delay: timedelta,
        error_code: str,
        error_detail: str,
        now: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        if delay.total_seconds() < 0:
            raise ValueError("retry delay cannot be negative")
        attempted_at = _aware_utc(now or datetime.now(UTC))
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = self._processing_for_update(session, command_id)
                row.state = BrokerControlState.RETRYING.value
                row.available_at = attempted_at + delay
                row.locked_at = None
                row.error_code = _required_text(error_code, "error_code", 64)
                row.error_detail = _safe_detail(error_detail)
                row.updated_at = attempted_at
                session.flush()
            session.expunge(row)
            return row

    def mark_failed(
        self,
        command_id: str,
        *,
        error_code: str,
        error_detail: str,
        now: datetime | None = None,
    ) -> CentralNodeBrokerCommand:
        failed_at = _aware_utc(now or datetime.now(UTC))
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = self._processing_for_update(session, command_id)
                row.state = BrokerControlState.FAILED.value
                row.failed_at = failed_at
                row.locked_at = None
                row.error_code = _required_text(error_code, "error_code", 64)
                row.error_detail = _safe_detail(error_detail)
                row.updated_at = failed_at
                session.flush()
            session.expunge(row)
            return row

    def history(
        self,
        *,
        organization_id: str,
        node_id: str,
        limit: int = 100,
    ) -> list[CentralNodeBrokerCommand]:
        if limit < 1 or limit > 1000:
            raise ValueError("history limit must be between 1 and 1000")
        organization = _required_text(organization_id, "organization_id", 36)
        node = _required_text(node_id, "node_id", 64)
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(CentralNodeBrokerCommand)
                    .where(
                        CentralNodeBrokerCommand.organization_id == organization,
                        CentralNodeBrokerCommand.node_id == node,
                    )
                    .order_by(CentralNodeBrokerCommand.created_at.desc())
                    .limit(limit)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def _processing_for_update(
        self,
        session: Session,
        command_id: str,
    ) -> CentralNodeBrokerCommand:
        normalized_id = _required_text(command_id, "command_id", 36)
        row = session.scalar(
            select(CentralNodeBrokerCommand)
            .where(CentralNodeBrokerCommand.id == normalized_id)
            .with_for_update()
        )
        if row is None:
            raise BrokerControlStateError("broker-control command was not found")
        if row.state != BrokerControlState.PROCESSING.value:
            raise BrokerControlStateError(
                "broker-control command is not in processing state"
            )
        return row


def _validate_operation_secret(
    operation: BrokerControlOperation,
    secret: str | None,
) -> None:
    needs_secret = operation in {
        BrokerControlOperation.PROVISION,
        BrokerControlOperation.ROTATE,
    }
    if needs_secret and secret is None:
        raise ValueError(f"{operation.value} command requires a secret")
    if not needs_secret and secret is not None:
        raise ValueError(f"{operation.value} command cannot contain a secret")


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain 1..{maximum} characters")
    return normalized


def _sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("command_sha256 must be a lowercase SHA-256 digest")
    return normalized


def _safe_detail(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("error_detail is required")
    return normalized[:1024]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
