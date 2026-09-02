from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.commissioning.catalog import supported_profile
from app.commissioning.models import (
    EquipmentCommissioningActivationAttempt,
    EquipmentCommissioningPreflightAttempt,
    EquipmentCommissioningSession,
)
from app.commissioning.repository import (
    CommissioningEquipmentReferenceError,
    CommissioningIdempotencyConflictError,
    CommissioningLifecycleConflictError,
    CommissioningNotFoundError,
    CommissioningVersionConflictError,
)
from app.db import Database, TelemetryLatest
from app.refrigeration.models import RefrigerationControllerBinding, RefrigerationEquipmentRecord
from app.security.repository import AuditEventInput, SecurityRepository

class CommissioningActivationNotFoundError(CommissioningNotFoundError):
    code = "commissioning_activation_not_found"


class CommissioningActivationConflictError(CommissioningLifecycleConflictError):
    code = "commissioning_activation_conflict"


class CommissioningPreflightStaleError(CommissioningLifecycleConflictError):
    code = "commissioning_preflight_stale"


@dataclass(frozen=True, slots=True)
class CommissioningActivationPreparation:
    attempt: EquipmentCommissioningActivationAttempt
    command: dict[str, object]
    replayed: bool


class CommissioningActivationRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository or SecurityRepository(database)
    def plan(
        self,
        session_id: str,
        *,
        organization_id: str,
        freshness_seconds: float,
    ) -> dict[str, object]:
        with Session(self._engine) as db:
            row = self._commissioning(db, session_id, organization_id)
            preflight = self._current_preflight(
                db,
                row,
                organization_id=organization_id,
                freshness_seconds=freshness_seconds,
            )
            return self._plan(db, row, preflight, organization_id)

    def prepare(
        self,
        session_id: str,
        *,
        organization_id: str,
        expected_version: int,
        idempotency_key: str,
        actor_subject: str,
        freshness_seconds: float,
        audit_event: AuditEventInput,
    ) -> CommissioningActivationPreparation:
        normalized_key = _idempotency_key(idempotency_key)
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as db, db.begin():
            commissioning = self._locked_commissioning(
                db, session_id, organization_id
            )
            if commissioning.version != expected_version:
                raise CommissioningVersionConflictError(
                    expected_version=expected_version,
                    actual_version=commissioning.version,
                )
            preflight = self._current_preflight(
                db,
                commissioning,
                organization_id=organization_id,
                freshness_seconds=freshness_seconds,
            )
            plan = self._plan(db, commissioning, preflight, organization_id)
            command_identity = {
                "session_id": commissioning.id,
                "session_version": commissioning.version,
                "preflight_attempt_id": preflight.id,
                "node_id": plan["node_id"],
                "bus_id": plan["bus_id"],
                "stable_transport_identifier": plan["stable_transport_identifier"],
                "unit_id": plan["unit_id"],
                "profile_id": plan["profile_id"],
                "profile_version": plan["profile_version"],
            }
            command_sha256 = _digest(command_identity)
            existing = db.scalar(
                select(EquipmentCommissioningActivationAttempt)
                .where(
                    EquipmentCommissioningActivationAttempt.organization_id
                    == organization_id,
                    EquipmentCommissioningActivationAttempt.session_id == session_id,
                    EquipmentCommissioningActivationAttempt.idempotency_key
                    == normalized_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.command_sha256 != command_sha256:
                    raise CommissioningIdempotencyConflictError(
                        "Idempotency-Key was already used for a different activation plan"
                    )
                if existing.state in {"active", "rolled_back"}:
                    db.expunge(existing)
                    return CommissioningActivationPreparation(
                        existing,
                        self._command(existing, plan, action="activate"),
                        True,
                    )
                commissioning.lifecycle = "pending_activation"
                commissioning.updated_by = actor_subject
                commissioning.updated_at = now
                db.expunge(existing)
                return CommissioningActivationPreparation(
                    existing,
                    self._command(existing, plan, action="activate"),
                    False,
                )
            competing = db.scalar(
                select(EquipmentCommissioningActivationAttempt.id).where(
                    EquipmentCommissioningActivationAttempt.organization_id
                    == organization_id,
                    EquipmentCommissioningActivationAttempt.session_id == session_id,
                    EquipmentCommissioningActivationAttempt.state.in_(
                        ("pending_activation", "active", "recovery_required")
                    ),
                )
            )
            if competing is not None:
                raise CommissioningActivationConflictError(
                    "Another activation attempt already owns this commissioning session"
                )
            attempt = EquipmentCommissioningActivationAttempt(
                id=str(uuid4()),
                organization_id=organization_id,
                session_id=session_id,
                preflight_attempt_id=preflight.id,
                idempotency_key=normalized_key,
                command_sha256=command_sha256,
                session_version=commissioning.version,
                state="pending_activation",
                plan=plan,
                evidence=None,
                actor_subject=actor_subject,
                started_at=now,
                completed_at=None,
            )
            db.add(attempt)
            commissioning.lifecycle = "pending_activation"
            commissioning.updated_by = actor_subject
            commissioning.updated_at = now
            db.flush()
            self._security_repository.append_audit_event(
                replace(
                    audit_event,
                    entity_id=session_id,
                    after_snapshot={
                        "activation_attempt_id": attempt.id,
                        "preflight_attempt_id": preflight.id,
                        "session_version": commissioning.version,
                        "state": "pending_activation",
                        "profile_id": plan["profile_id"],
                        "polling_mode": "read_only_fc03",
                        "modbus_writes": "none",
                        "hardware_writes": "none",
                    },
                ),
                session=db,
            )
            command = self._command(attempt, plan, action="activate")
            db.expunge(attempt)
            return CommissioningActivationPreparation(attempt, command, False)

    def complete(
        self,
        attempt_id: str,
        *,
        organization_id: str,
        state: str,
        evidence: dict[str, object],
        audit_event: AuditEventInput,
    ) -> EquipmentCommissioningActivationAttempt:
        if state not in {
            "active", "activation_failed", "rolled_back", "recovery_required"
        }:
            raise ValueError("unsupported activation completion state")
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as db, db.begin():
            attempt = db.scalar(
                select(EquipmentCommissioningActivationAttempt)
                .where(
                    EquipmentCommissioningActivationAttempt.id == attempt_id,
                    EquipmentCommissioningActivationAttempt.organization_id
                    == organization_id,
                )
                .with_for_update()
            )
            if attempt is None:
                raise CommissioningActivationNotFoundError(attempt_id)
            commissioning = self._locked_commissioning(
                db, attempt.session_id, organization_id
            )
            attempt.state = state
            attempt.evidence = evidence
            attempt.completed_at = now
            if state == "active":
                commissioning.lifecycle = "active"
            elif state == "rolled_back":
                commissioning.lifecycle = "rolled_back"
            else:
                commissioning.lifecycle = "activation_failed"
            commissioning.updated_by = attempt.actor_subject
            commissioning.updated_at = now
            db.flush()
            self._security_repository.append_audit_event(
                replace(
                    audit_event,
                    entity_id=attempt.session_id,
                    after_snapshot={
                        "activation_attempt_id": attempt.id,
                        "state": state,
                        "session_version": attempt.session_version,
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
    ) -> EquipmentCommissioningActivationAttempt:
        with Session(self._engine, expire_on_commit=False) as db:
            self._commissioning(db, session_id, organization_id)
            attempt = db.scalar(
                select(EquipmentCommissioningActivationAttempt)
                .where(
                    EquipmentCommissioningActivationAttempt.organization_id
                    == organization_id,
                    EquipmentCommissioningActivationAttempt.session_id == session_id,
                )
                .order_by(
                    EquipmentCommissioningActivationAttempt.started_at.desc(),
                    EquipmentCommissioningActivationAttempt.id.desc(),
                )
            )
            if attempt is None:
                raise CommissioningActivationNotFoundError(session_id)
            db.expunge(attempt)
            return attempt

    def telemetry_evidence(
        self,
        *,
        node_id: str,
        source: str,
        equipment_id: str,
        received_after: datetime,
    ) -> dict[str, object] | None:
        with Session(self._engine) as db:
            row = db.scalar(
                select(TelemetryLatest)
                .where(
                    TelemetryLatest.node_id == node_id,
                    TelemetryLatest.source == source,
                    TelemetryLatest.equipment_id == equipment_id,
                    TelemetryLatest.received_at >= received_after,
                )
                .order_by(
                    TelemetryLatest.received_at.desc(),
                    TelemetryLatest.id.desc(),
                )
                .limit(1)
            )
            if row is None:
                return None
            return {
                "event_id": row.event_id,
                "metric": row.metric,
                "quality": row.quality,
                "captured_at": _aware(row.captured_at).isoformat(),
                "received_at": _aware(row.received_at).isoformat(),
                "source": row.source,
                "equipment_id": row.equipment_id,
            }

    @staticmethod
    def _command(
        attempt: EquipmentCommissioningActivationAttempt,
        plan: dict[str, object],
        *,
        action: str,
    ) -> dict[str, object]:
        return {
            "activation_id": attempt.id,
            "action": action,
            "node_id": plan["node_id"],
            "bus_id": plan["bus_id"],
            "stable_transport_identifier": plan["stable_transport_identifier"],
            "unit_id": plan["unit_id"],
            "profile_id": plan["profile_id"],
            "profile_version": plan["profile_version"],
        }

    def _current_preflight(
        self,
        db: Session,
        row: EquipmentCommissioningSession,
        *,
        organization_id: str,
        freshness_seconds: float,
    ) -> EquipmentCommissioningPreflightAttempt:
        attempt = db.scalar(
            select(EquipmentCommissioningPreflightAttempt)
            .where(
                EquipmentCommissioningPreflightAttempt.organization_id
                == organization_id,
                EquipmentCommissioningPreflightAttempt.session_id == row.id,
                EquipmentCommissioningPreflightAttempt.state == "completed",
            )
            .order_by(
                EquipmentCommissioningPreflightAttempt.completed_at.desc(),
                EquipmentCommissioningPreflightAttempt.id.desc(),
            )
            .limit(1)
        )
        if (
            attempt is None
            or attempt.result != "passed"
            or attempt.session_version != row.version
            or attempt.completed_at is None
        ):
            raise CommissioningPreflightStaleError(
                "Activation requires a successful preflight for the current commissioning version"
            )
        completed_at = _aware(attempt.completed_at)
        if completed_at + timedelta(seconds=freshness_seconds) < datetime.now(UTC):
            raise CommissioningPreflightStaleError(
                "The successful commissioning preflight is no longer fresh"
            )
        evidence = attempt.evidence
        exact = {
            "node_id": row.node_id,
            "bus_id": row.bus_id,
            "stable_transport_identifier": row.stable_transport_identifier,
            "unit_id": row.unit_id,
            "profile_id": row.profile_id,
            "profile_version": row.profile_version,
            "modbus_writes": "none",
            "hardware_writes": "none",
        }
        if not isinstance(evidence, dict) or any(
            evidence.get(key) != value for key, value in exact.items()
        ):
            raise CommissioningPreflightStaleError(
                "Preflight evidence does not match the current commissioning intent"
            )
        return attempt

    @staticmethod
    def _plan(
        db: Session,
        row: EquipmentCommissioningSession,
        preflight: EquipmentCommissioningPreflightAttempt,
        organization_id: str,
    ) -> dict[str, object]:
        if row.lifecycle not in {
            "ready_for_preflight",
            "verified",
            "pending_activation",
            "active",
            "activation_failed",
            "rolled_back",
        }:
            raise CommissioningLifecycleConflictError(
                "Commissioning session is not eligible for activation"
            )
        profile = supported_profile(row.profile_id)
        if profile is None or row.profile_version != profile.version:
            raise CommissioningLifecycleConflictError(
                "Commissioning profile is unavailable or stale"
            )
        required = (
            row.node_id,
            row.bus_id,
            row.stable_transport_identifier,
            row.unit_id,
            row.target_equipment_key,
        )
        if any(value is None or value == "" for value in required):
            raise CommissioningLifecycleConflictError(
                "Commissioning activation intent is incomplete"
            )
        equipment = db.scalar(
            select(RefrigerationEquipmentRecord).where(
                RefrigerationEquipmentRecord.id == row.target_equipment_key,
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
                RefrigerationEquipmentRecord.lifecycle_status != "retired",
            )
        )
        if equipment is None:
            raise CommissioningEquipmentReferenceError(
                "Target equipment is unavailable in the active organization"
            )
        conflict = db.scalar(
            select(EquipmentCommissioningSession.id)
            .where(
                EquipmentCommissioningSession.organization_id == organization_id,
                EquipmentCommissioningSession.id != row.id,
                EquipmentCommissioningSession.lifecycle == "active",
                or_(
                    EquipmentCommissioningSession.target_equipment_key
                    == row.target_equipment_key,
                    (
                        (EquipmentCommissioningSession.node_id == row.node_id)
                        & (EquipmentCommissioningSession.bus_id == row.bus_id)
                        & (EquipmentCommissioningSession.unit_id == row.unit_id)
                    ),
                ),
            )
            .limit(1)
        )
        if conflict is not None:
            raise CommissioningActivationConflictError(
                "Another active commissioning session already owns this equipment or Modbus identity"
            )
        if profile.device_class == "temperature-controller":
            active_binding = db.scalar(
                select(RefrigerationControllerBinding).where(
                    RefrigerationControllerBinding.organization_id == organization_id,
                    RefrigerationControllerBinding.equipment_id == row.target_equipment_key,
                    RefrigerationControllerBinding.unbound_at.is_(None),
                )
            )
            if active_binding is not None:
                matching_replay = (
                    profile.device_family == "embraco"
                    and active_binding.node_id == row.node_id
                    and active_binding.unit_id == row.unit_id
                    and active_binding.profile_version == row.profile_version
                    and active_binding.controller_equipment_id == f"EMBRACO-{row.unit_id}"
                )
                if not matching_replay:
                    raise CommissioningEquipmentReferenceError(
                        "Target equipment already has a different active controller binding"
                    )
        family = profile.device_family
        source = {
            "xjp60d": "dixell-xjp60d",
            "le01mp": "f-and-f-le-01mp",
            "embraco": "embraco-sync",
        }[family]
        equipment_id = {
            "xjp60d": f"K{row.unit_id}",
            "le01mp": f"LE01MP-{row.unit_id}",
            "embraco": f"EMBRACO-{row.unit_id}",
        }[family]
        evidence = preflight.evidence if isinstance(preflight.evidence, dict) else {}
        warnings = list(evidence.get("warnings", [])) if isinstance(evidence.get("warnings"), list) else []
        if preflight.evidence_level != "hardware_verified":
            warnings.append(
                "Preflight passed with partial evidence; engineering values remain at their existing verification level."
            )
        return {
            "schema_version": 1,
            "session_id": row.id,
            "session_version": row.version,
            "preflight_attempt_id": preflight.id,
            "preflight_completed_at": _aware(preflight.completed_at).isoformat(),
            "preflight_evidence_level": preflight.evidence_level,
            "device_class": row.device_class,
            "manufacturer": row.manufacturer,
            "model": row.model,
            "profile_id": profile.id,
            "profile_version": profile.version,
            "device_family": family,
            "node_id": str(row.node_id),
            "bus_id": str(row.bus_id),
            "stable_transport_identifier": str(row.stable_transport_identifier),
            "unit_id": int(row.unit_id),
            "target_equipment_key": str(row.target_equipment_key),
            "telemetry_source": source,
            "telemetry_equipment_id": equipment_id,
            "polling_mode": "read_only_fc03",
            "binding_kind": (
                "refrigeration_controller" if family == "embraco" else "commissioning_target"
            ),
            "warnings": warnings,
            "will_not_perform": [
                "Modbus FC05/06/15/16 writes",
                "controller parameter changes",
                "generic RS-485 scanning",
                "public cloud dependency",
                "production deployment or site cutover",
            ],
        }

    @staticmethod
    def _locked_commissioning(
        db: Session,
        session_id: str,
        organization_id: str,
    ) -> EquipmentCommissioningSession:
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
    def _commissioning(
        db: Session,
        session_id: str,
        organization_id: str,
    ) -> EquipmentCommissioningSession:
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
        raise CommissioningLifecycleConflictError(
            "Idempotency-Key must be 1..128 characters"
        )
    return normalized


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware(value: datetime | None) -> datetime:
    if value is None:
        raise CommissioningPreflightStaleError(
            "Successful preflight completion timestamp is missing"
        )
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
