from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.commissioning.catalog import profile_matches_identity, resolve_supported_profile
from app.commissioning.models import EquipmentCommissioningSession
from app.commissioning.schemas import CommissioningSessionPatch, CommissioningSessionWrite
from app.db import Database
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import AuditEventInput, SecurityRepository


class CommissioningRepositoryError(RuntimeError):
    code = "commissioning_repository_error"


class CommissioningNotFoundError(CommissioningRepositoryError):
    code = "commissioning_session_not_found"


class CommissioningVersionConflictError(CommissioningRepositoryError):
    code = "commissioning_session_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"commissioning session version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class CommissioningIdempotencyConflictError(CommissioningRepositoryError):
    code = "commissioning_idempotency_key_reused"


class CommissioningLifecycleConflictError(CommissioningRepositoryError):
    code = "commissioning_lifecycle_conflict"


class CommissioningEquipmentReferenceError(CommissioningRepositoryError):
    code = "commissioning_equipment_reference_invalid"


@dataclass(frozen=True, slots=True)
class CommissioningCreateResult:
    session: EquipmentCommissioningSession
    replayed: bool


class CommissioningRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository or SecurityRepository(database)

    def list_sessions(self, *, organization_id: str) -> tuple[EquipmentCommissioningSession, ...]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(EquipmentCommissioningSession)
                    .where(EquipmentCommissioningSession.organization_id == organization_id)
                    .order_by(
                        EquipmentCommissioningSession.updated_at.desc(),
                        EquipmentCommissioningSession.id.desc(),
                    )
                )
            )
            self._apply_current_target_availability(
                session,
                rows,
                organization_id=organization_id,
            )
            session.expunge_all()
            return tuple(rows)

    def get_session(
        self,
        session_id: str,
        *,
        organization_id: str,
    ) -> EquipmentCommissioningSession:
        with Session(self._engine, expire_on_commit=False) as session:
            row = self._row(session, session_id, organization_id=organization_id)
            self._apply_current_target_availability(
                session,
                [row],
                organization_id=organization_id,
            )
            session.expunge(row)
            return row

    def create_session(
        self,
        payload: CommissioningSessionWrite,
        *,
        organization_id: str,
        idempotency_key: str,
        actor_subject: str,
        audit_event: AuditEventInput,
    ) -> CommissioningCreateResult:
        normalized_key = _normalize_idempotency_key(idempotency_key)
        values = payload.model_dump()
        fingerprint = _fingerprint(values)
        now = datetime.now(UTC)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    existing = session.scalar(
                        select(EquipmentCommissioningSession).where(
                            EquipmentCommissioningSession.organization_id == organization_id,
                            EquipmentCommissioningSession.create_idempotency_key == normalized_key,
                        )
                    )
                    if existing is not None:
                        return self._replay(existing, fingerprint)
                    self._validate_target_equipment(
                        session,
                        values.get("target_equipment_key"),
                        organization_id=organization_id,
                    )
                    resolved = _resolve_values(values)
                    row = EquipmentCommissioningSession(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        create_idempotency_key=normalized_key,
                        create_fingerprint_sha256=fingerprint,
                        version=1,
                        created_by=actor_subject,
                        updated_by=actor_subject,
                        created_at=now,
                        updated_at=now,
                        cancelled_at=None,
                        **resolved,
                    )
                    session.add(row)
                    session.flush()
                    self._security_repository.append_audit_event(
                        replace(
                            audit_event,
                            entity_id=row.id,
                            after_snapshot=_snapshot(row),
                        ),
                        session=session,
                    )
                session.expunge(row)
                return CommissioningCreateResult(session=row, replayed=False)
        except IntegrityError as error:
            with Session(self._engine, expire_on_commit=False) as session:
                existing = session.scalar(
                    select(EquipmentCommissioningSession).where(
                        EquipmentCommissioningSession.organization_id == organization_id,
                        EquipmentCommissioningSession.create_idempotency_key == normalized_key,
                    )
                )
                if existing is not None:
                    return self._replay(existing, fingerprint)
            raise CommissioningRepositoryError("commissioning draft could not be persisted") from error

    def update_session(
        self,
        session_id: str,
        payload: CommissioningSessionPatch,
        *,
        organization_id: str,
        expected_version: int,
        actor_subject: str,
        audit_event: AuditEventInput,
    ) -> EquipmentCommissioningSession:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise CommissioningLifecycleConflictError("commissioning update must change at least one field")
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = self._locked_row(session, session_id, organization_id=organization_id)
                self._check_version(row, expected_version)
                if row.lifecycle == "cancelled":
                    raise CommissioningLifecycleConflictError("cancelled commissioning sessions are read-only")
                merged = _editable_values(row)
                merged.update(changes)
                if not merged.get("device_class") or not merged.get("manufacturer") or not merged.get("model"):
                    raise CommissioningLifecycleConflictError(
                        "device_class, manufacturer and model are required"
                    )
                before = _snapshot(row)
                self._validate_target_equipment(
                    session,
                    merged.get("target_equipment_key"),
                    organization_id=organization_id,
                )
                resolved = _resolve_values(merged)
                for key, value in resolved.items():
                    setattr(row, key, value)
                row.version += 1
                row.updated_by = actor_subject
                row.updated_at = datetime.now(UTC)
                session.flush()
                self._security_repository.append_audit_event(
                    replace(
                        audit_event,
                        entity_id=row.id,
                        before_snapshot=before,
                        after_snapshot=_snapshot(row),
                    ),
                    session=session,
                )
            session.expunge(row)
            return row

    def cancel_session(
        self,
        session_id: str,
        *,
        organization_id: str,
        expected_version: int,
        actor_subject: str,
        audit_event: AuditEventInput,
    ) -> EquipmentCommissioningSession:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = self._locked_row(session, session_id, organization_id=organization_id)
                self._check_version(row, expected_version)
                if row.lifecycle == "cancelled":
                    return row
                before = _snapshot(row)
                now = datetime.now(UTC)
                row.lifecycle = "cancelled"
                row.version += 1
                row.updated_by = actor_subject
                row.updated_at = now
                row.cancelled_at = now
                session.flush()
                self._security_repository.append_audit_event(
                    replace(
                        audit_event,
                        entity_id=row.id,
                        before_snapshot=before,
                        after_snapshot=_snapshot(row),
                    ),
                    session=session,
                )
            session.expunge(row)
            return row

    @staticmethod
    def _validate_target_equipment(
        session: Session,
        target_equipment_key: object,
        *,
        organization_id: str,
    ) -> None:
        if target_equipment_key is None or target_equipment_key == "":
            return
        exists = session.scalar(
            select(RefrigerationEquipmentRecord.id).where(
                RefrigerationEquipmentRecord.id == str(target_equipment_key),
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
                RefrigerationEquipmentRecord.lifecycle_status != "retired",
            )
        )
        if exists is None:
            raise CommissioningEquipmentReferenceError(
                "Target equipment is unavailable in the active organization"
            )

    @staticmethod
    def _apply_current_target_availability(
        session: Session,
        rows: list[EquipmentCommissioningSession],
        *,
        organization_id: str,
    ) -> None:
        ready_targets = {
            row.target_equipment_key
            for row in rows
            if row.lifecycle == "ready_for_preflight" and row.target_equipment_key
        }
        if not ready_targets:
            return
        available_targets = set(
            session.scalars(
                select(RefrigerationEquipmentRecord.id).where(
                    RefrigerationEquipmentRecord.id.in_(ready_targets),
                    RefrigerationEquipmentRecord.organization_id == organization_id,
                    RefrigerationEquipmentRecord.deleted_at.is_(None),
                    RefrigerationEquipmentRecord.lifecycle_status != "retired",
                )
            )
        )
        for row in rows:
            if row.lifecycle == "ready_for_preflight" and row.target_equipment_key not in available_targets:
                row.lifecycle = "blocked"
                row.blocked_reason = "Target equipment is unavailable in the active organization"

    @staticmethod
    def _replay(row: EquipmentCommissioningSession, fingerprint: str) -> CommissioningCreateResult:
        if row.create_fingerprint_sha256 != fingerprint:
            raise CommissioningIdempotencyConflictError(
                "Idempotency-Key was already used for a different commissioning draft"
            )
        return CommissioningCreateResult(session=row, replayed=True)

    @staticmethod
    def _check_version(row: EquipmentCommissioningSession, expected_version: int) -> None:
        if row.version != expected_version:
            raise CommissioningVersionConflictError(
                expected_version=expected_version,
                actual_version=row.version,
            )

    @staticmethod
    def _row(
        session: Session,
        session_id: str,
        *,
        organization_id: str,
    ) -> EquipmentCommissioningSession:
        row = session.scalar(
            select(EquipmentCommissioningSession).where(
                EquipmentCommissioningSession.id == session_id,
                EquipmentCommissioningSession.organization_id == organization_id,
            )
        )
        if row is None:
            raise CommissioningNotFoundError(session_id)
        return row

    @classmethod
    def _locked_row(
        cls,
        session: Session,
        session_id: str,
        *,
        organization_id: str,
    ) -> EquipmentCommissioningSession:
        row = session.scalar(
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


def _resolve_values(values: dict[str, Any]) -> dict[str, Any]:
    device_class = str(values["device_class"]).strip()
    manufacturer = str(values["manufacturer"]).strip()
    model = str(values["model"]).strip()
    requested_profile_id = values.get("profile_id")
    profile = resolve_supported_profile(
        profile_id=requested_profile_id,
        manufacturer=manufacturer,
        model=model,
    )
    resolved = {
        "device_class": device_class,
        "manufacturer": manufacturer,
        "model": model,
        "profile_id": profile.id if profile is not None else requested_profile_id,
        "profile_version": profile.version if profile is not None else None,
        "transport_kind": profile.transport_kind if profile is not None else None,
        "node_id": values.get("node_id"),
        "bus_id": values.get("bus_id"),
        "stable_transport_identifier": values.get("stable_transport_identifier"),
        "unit_id": values.get("unit_id"),
        "ip_address": values.get("ip_address"),
        "target_equipment_key": values.get("target_equipment_key"),
        "blocked_reason": None,
        "unsupported_reason": None,
    }
    if profile is None:
        resolved["lifecycle"] = "unsupported"
        resolved["unsupported_reason"] = "Unsupported / Profile required"
        return resolved
    if not profile_matches_identity(
        profile,
        device_class=device_class,
        manufacturer=manufacturer,
        model=model,
    ):
        resolved["lifecycle"] = "blocked"
        resolved["blocked_reason"] = "Selected profile does not match device identity"
        return resolved
    if profile.transport_kind == "modbus_rtu":
        stable_identifier = resolved["stable_transport_identifier"]
        if stable_identifier and not _is_stable_serial_identifier(str(stable_identifier)):
            resolved["lifecycle"] = "blocked"
            resolved["blocked_reason"] = (
                "Stable serial device path must use /dev/serial/by-id/<device-id>"
            )
            return resolved
        required = (
            resolved["node_id"],
            resolved["bus_id"],
            resolved["stable_transport_identifier"],
            resolved["unit_id"],
            resolved["target_equipment_key"],
        )
        resolved["lifecycle"] = "ready_for_preflight" if all(item is not None and item != "" for item in required) else "draft"
        return resolved
    resolved["lifecycle"] = "draft"
    return resolved


def _is_stable_serial_identifier(value: str) -> bool:
    prefix = "/dev/serial/by-id/"
    identifier = value.strip()
    device_id = identifier.removeprefix(prefix)
    return (
        identifier.startswith(prefix)
        and bool(device_id)
        and device_id not in {".", ".."}
        and "/" not in device_id
        and not any(character.isspace() for character in device_id)
    )


def _editable_values(row: EquipmentCommissioningSession) -> dict[str, Any]:
    return {
        "device_class": row.device_class,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "profile_id": row.profile_id,
        "node_id": row.node_id,
        "bus_id": row.bus_id,
        "stable_transport_identifier": row.stable_transport_identifier,
        "unit_id": row.unit_id,
        "ip_address": row.ip_address,
        "target_equipment_key": row.target_equipment_key,
    }


def _snapshot(row: EquipmentCommissioningSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "lifecycle": row.lifecycle,
        "device_class": row.device_class,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "profile_id": row.profile_id,
        "profile_version": row.profile_version,
        "transport_kind": row.transport_kind,
        "node_id": row.node_id,
        "bus_id": row.bus_id,
        "stable_transport_identifier": row.stable_transport_identifier,
        "unit_id": row.unit_id,
        "ip_address": row.ip_address,
        "target_equipment_key": row.target_equipment_key,
        "blocked_reason": row.blocked_reason,
        "unsupported_reason": row.unsupported_reason,
        "version": row.version,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
    }


def _normalize_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise CommissioningLifecycleConflictError("Idempotency-Key must be 1..128 characters")
    return normalized


def _fingerprint(values: dict[str, Any]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
