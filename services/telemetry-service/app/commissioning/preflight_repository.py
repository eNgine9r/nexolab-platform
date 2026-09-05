from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commissioning.catalog import profile_matches_identity, supported_profile
from app.commissioning.models import EquipmentCommissioningPreflightAttempt, EquipmentCommissioningSession
from app.commissioning.repository import (
    CommissioningEquipmentReferenceError,
    CommissioningIdempotencyConflictError,
    CommissioningLifecycleConflictError,
    CommissioningNotFoundError,
    CommissioningVersionConflictError,
)
from app.db import Database
from app.refrigeration.models import RefrigerationControllerBinding, RefrigerationEquipmentRecord
from app.security.repository import AuditEventInput, SecurityRepository


class CommissioningPreflightNotFoundError(CommissioningNotFoundError):
    code = "commissioning_preflight_not_found"


class CommissioningPreflightInProgressError(CommissioningLifecycleConflictError):
    code = "commissioning_preflight_in_progress"


@dataclass(frozen=True, slots=True)
class CommissioningPreflightPreparation:
    attempt: EquipmentCommissioningPreflightAttempt
    command: dict[str, object]
    replayed: bool


class CommissioningPreflightRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository or SecurityRepository(database)

    def prepare(
        self,
        session_id: str,
        *,
        organization_id: str,
        expected_version: int,
        idempotency_key: str,
        actor_subject: str,
        deadline_seconds: float,
        audit_event: AuditEventInput,
    ) -> CommissioningPreflightPreparation:
        normalized_key = _idempotency_key(idempotency_key)
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as db, db.begin():
            commissioning = self._locked_commissioning(db, session_id, organization_id)
            if commissioning.version != expected_version:
                raise CommissioningVersionConflictError(
                    expected_version=expected_version,
                    actual_version=commissioning.version,
                )
            command = self._command(db, commissioning, organization_id, deadline_seconds)
            command_sha256 = _digest(command)
            existing = db.scalar(
                select(EquipmentCommissioningPreflightAttempt)
                .where(
                    EquipmentCommissioningPreflightAttempt.organization_id == organization_id,
                    EquipmentCommissioningPreflightAttempt.session_id == session_id,
                    EquipmentCommissioningPreflightAttempt.idempotency_key == normalized_key,
                )
                .with_for_update()
            )
            stale_after = timedelta(seconds=max(15.0, deadline_seconds + 5.0))
            if existing is not None:
                if existing.command_sha256 != command_sha256:
                    raise CommissioningIdempotencyConflictError(
                        "Idempotency-Key was already used for a different preflight command"
                    )
                if existing.state == "completed":
                    db.expunge(existing)
                    return CommissioningPreflightPreparation(existing, command, True)
                if _aware(existing.started_at) + stale_after > now:
                    raise CommissioningPreflightInProgressError(
                        "A bounded commissioning preflight with this key is already running"
                    )
                existing.started_at = now
                existing.actor_subject = actor_subject
                attempt = existing
            else:
                other_running = db.scalar(
                    select(EquipmentCommissioningPreflightAttempt)
                    .where(
                        EquipmentCommissioningPreflightAttempt.organization_id == organization_id,
                        EquipmentCommissioningPreflightAttempt.session_id == session_id,
                        EquipmentCommissioningPreflightAttempt.state == "running",
                    )
                    .order_by(EquipmentCommissioningPreflightAttempt.started_at.desc())
                    .limit(1)
                )
                if other_running is not None and _aware(other_running.started_at) + stale_after > now:
                    raise CommissioningPreflightInProgressError(
                        "Another bounded commissioning preflight is already running for this session"
                    )
                attempt = EquipmentCommissioningPreflightAttempt(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    session_id=session_id,
                    idempotency_key=normalized_key,
                    command_sha256=command_sha256,
                    session_version=commissioning.version,
                    state="running",
                    result=None,
                    code=None,
                    evidence_level=None,
                    evidence=None,
                    actor_subject=actor_subject,
                    started_at=now,
                    completed_at=None,
                )
                db.add(attempt)
            db.flush()
            self._security_repository.append_audit_event(
                replace(
                    audit_event,
                    entity_id=session_id,
                    after_snapshot={
                        "preflight_attempt_id": attempt.id,
                        "session_version": commissioning.version,
                        "state": "running",
                        "profile_id": command["profile_id"],
                        "profile_version": command["profile_version"],
                        "read_method": "modbus_rtu_fc03",
                        "modbus_writes": "none",
                        "hardware_writes": "none",
                    },
                ),
                session=db,
            )
            db.expunge(attempt)
            return CommissioningPreflightPreparation(attempt, command, False)

    def complete(
        self,
        attempt_id: str,
        *,
        organization_id: str,
        evidence: dict[str, Any],
        audit_event: AuditEventInput,
    ) -> EquipmentCommissioningPreflightAttempt:
        with Session(self._engine, expire_on_commit=False) as db, db.begin():
            attempt = db.scalar(
                select(EquipmentCommissioningPreflightAttempt)
                .where(
                    EquipmentCommissioningPreflightAttempt.id == attempt_id,
                    EquipmentCommissioningPreflightAttempt.organization_id == organization_id,
                )
                .with_for_update()
            )
            if attempt is None:
                raise CommissioningPreflightNotFoundError(attempt_id)
            if attempt.state == "completed":
                db.expunge(attempt)
                return attempt
            now = datetime.now(UTC)
            attempt.state = "completed"
            attempt.result = str(evidence["result"])
            attempt.code = str(evidence["code"])
            attempt.evidence_level = str(evidence["evidence_level"])
            attempt.evidence = evidence
            attempt.completed_at = now
            commissioning = db.scalar(
                select(EquipmentCommissioningSession)
                .where(
                    EquipmentCommissioningSession.id == attempt.session_id,
                    EquipmentCommissioningSession.organization_id == organization_id,
                )
                .with_for_update()
            )
            if commissioning is not None and commissioning.version == attempt.session_version:
                if attempt.result == "passed":
                    commissioning.lifecycle = "verified"
                elif commissioning.lifecycle in {"verified", "activation_failed", "rolled_back"}:
                    commissioning.lifecycle = "ready_for_preflight"
                commissioning.updated_by = attempt.actor_subject
                commissioning.updated_at = now
            db.flush()
            self._security_repository.append_audit_event(
                replace(
                    audit_event,
                    entity_id=attempt.session_id,
                    after_snapshot={
                        "preflight_attempt_id": attempt.id,
                        "session_version": attempt.session_version,
                        "state": "completed",
                        "result": attempt.result,
                        "code": attempt.code,
                        "evidence_level": attempt.evidence_level,
                        "read_method": "modbus_rtu_fc03",
                        "modbus_writes": "none",
                        "hardware_writes": "none",
                    },
                ),
                session=db,
            )
            db.expunge(attempt)
            return attempt

    def latest(
        self,
        session_id: str,
        *,
        organization_id: str,
    ) -> EquipmentCommissioningPreflightAttempt:
        with Session(self._engine, expire_on_commit=False) as db:
            self._commissioning(db, session_id, organization_id)
            attempt = db.scalar(
                select(EquipmentCommissioningPreflightAttempt)
                .where(
                    EquipmentCommissioningPreflightAttempt.organization_id == organization_id,
                    EquipmentCommissioningPreflightAttempt.session_id == session_id,
                )
                .order_by(
                    EquipmentCommissioningPreflightAttempt.started_at.desc(),
                    EquipmentCommissioningPreflightAttempt.id.desc(),
                )
            )
            if attempt is None:
                raise CommissioningPreflightNotFoundError(session_id)
            db.expunge(attempt)
            return attempt

    @staticmethod
    def _command(
        db: Session,
        row: EquipmentCommissioningSession,
        organization_id: str,
        deadline_seconds: float,
    ) -> dict[str, object]:
        if row.lifecycle not in {
            "ready_for_preflight", "verified", "activation_failed", "rolled_back"
        }:
            raise CommissioningLifecycleConflictError(
                "Commissioning session is not eligible for read-only preflight verification"
            )
        profile = supported_profile(row.profile_id)
        if profile is None or row.profile_version != profile.version:
            raise CommissioningLifecycleConflictError("Commissioning profile is unavailable or stale")
        if not profile_matches_identity(
            profile,
            device_class=row.device_class,
            manufacturer=row.manufacturer,
            model=row.model,
        ):
            raise CommissioningLifecycleConflictError("Commissioning profile no longer matches device identity")
        required = (row.node_id, row.bus_id, row.stable_transport_identifier, row.unit_id, row.target_equipment_key)
        if any(value is None or value == "" for value in required):
            raise CommissioningLifecycleConflictError("Commissioning transport and equipment intent is incomplete")
        target = db.scalar(
            select(RefrigerationEquipmentRecord.id).where(
                RefrigerationEquipmentRecord.id == row.target_equipment_key,
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
                RefrigerationEquipmentRecord.lifecycle_status != "retired",
            )
        )
        if target is None:
            raise CommissioningEquipmentReferenceError(
                "Target equipment is unavailable in the active organization"
            )
        if profile.device_class == "temperature-controller":
            active_binding = db.scalar(
                select(RefrigerationControllerBinding.id).where(
                    RefrigerationControllerBinding.organization_id == organization_id,
                    RefrigerationControllerBinding.equipment_id == row.target_equipment_key,
                    RefrigerationControllerBinding.unbound_at.is_(None),
                )
            )
            if active_binding is not None:
                raise CommissioningEquipmentReferenceError(
                    "Target equipment already has an active controller binding"
                )
        return {
            "node_id": str(row.node_id),
            "bus_id": str(row.bus_id),
            "stable_transport_identifier": str(row.stable_transport_identifier),
            "unit_id": int(row.unit_id),
            "profile_id": profile.id,
            "profile_version": profile.version,
            "deadline_seconds": float(deadline_seconds),
        }

    @staticmethod
    def _locked_commissioning(db: Session, session_id: str, organization_id: str) -> EquipmentCommissioningSession:
        row = db.scalar(
            select(EquipmentCommissioningSession)
            .where(
                EquipmentCommissioningSession.id == session_id,
                EquipmentCommissioningSession.organization_id == organization_id,
            )
            .with_for_update()
        )
        if row is None:
            raise CommissioningNotFoundError(session_id)
        return row

    @staticmethod
    def _commissioning(db: Session, session_id: str, organization_id: str) -> EquipmentCommissioningSession:
        row = db.scalar(
            select(EquipmentCommissioningSession).where(
                EquipmentCommissioningSession.id == session_id,
                EquipmentCommissioningSession.organization_id == organization_id,
            )
        )
        if row is None:
            raise CommissioningNotFoundError(session_id)
        return row


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise CommissioningLifecycleConflictError("Idempotency-Key must be 1..128 characters")
    return normalized


def _digest(command: dict[str, object]) -> str:
    encoded = json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
