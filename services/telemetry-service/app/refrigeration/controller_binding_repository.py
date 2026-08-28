from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database, TelemetryLatest
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.refrigeration.models import RefrigerationControllerBinding, RefrigerationEquipmentRecord
from app.refrigeration.schemas import RefrigerationControllerBindingWrite
from app.security.repository import AuditEventInput, SecurityRepository


class ControllerBindingError(RuntimeError):
    code = "controller_binding_error"


class ControllerBindingNotFoundError(ControllerBindingError):
    code = "controller_binding_not_found"


class ControllerBindingConflictError(ControllerBindingError):
    code = "controller_binding_conflict"


class ControllerBindingUnverifiedError(ControllerBindingError):
    code = "controller_binding_unverified"


class ControllerBindingEquipmentNotFoundError(ControllerBindingError):
    code = "equipment_not_found"


class ControllerSummary:
    def __init__(
        self,
        *,
        binding: RefrigerationControllerBinding,
        control_state: int | None,
        compressor_speed_rpm: float | None,
        last_seen_at: datetime | None,
    ) -> None:
        self.binding = binding
        self.control_state = control_state
        self.compressor_speed_rpm = compressor_speed_rpm
        self.last_seen_at = last_seen_at


class PostgresRefrigerationControllerBindingRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_summaries(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[ControllerSummary]:
        with Session(self._engine, expire_on_commit=False) as session:
            bindings = list(
                session.scalars(
                    select(RefrigerationControllerBinding)
                    .where(
                        RefrigerationControllerBinding.organization_id == organization_id,
                        RefrigerationControllerBinding.unbound_at.is_(None),
                    )
                    .order_by(RefrigerationControllerBinding.equipment_id.asc())
                )
            )
            if not bindings:
                return []
            identities = [(item.node_id, item.controller_equipment_id) for item in bindings]
            rows = list(
                session.scalars(
                    select(TelemetryLatest).where(
                        TelemetryLatest.source == "embraco-sync",
                        tuple_(TelemetryLatest.node_id, TelemetryLatest.equipment_id).in_(identities),
                        TelemetryLatest.metric.in_(("refrigeration.control_state", "compressor.speed")),
                    )
                )
            )
            latest: dict[tuple[str, str, str], TelemetryLatest] = {}
            for row in rows:
                key = (row.node_id, row.equipment_id, row.metric)
                current = latest.get(key)
                if current is None or row.captured_at > current.captured_at:
                    latest[key] = row
            result: list[ControllerSummary] = []
            for binding in bindings:
                state = latest.get((binding.node_id, binding.controller_equipment_id, "refrigeration.control_state"))
                speed = latest.get((binding.node_id, binding.controller_equipment_id, "compressor.speed"))
                seen = max(
                    (item.captured_at for item in (state, speed) if item is not None),
                    default=None,
                )
                result.append(
                    ControllerSummary(
                        binding=binding,
                        control_state=(
                            int(state.value)
                            if state is not None and state.quality == "valid" and state.value is not None
                            else None
                        ),
                        compressor_speed_rpm=(
                            float(speed.value)
                            if speed is not None and speed.quality == "valid" and speed.value is not None
                            else None
                        ),
                        last_seen_at=seen,
                    )
                )
            for binding in bindings:
                session.expunge(binding)
            return result

    def get_active(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationControllerBinding:
        with Session(self._engine, expire_on_commit=False) as session:
            binding = session.scalar(
                select(RefrigerationControllerBinding).where(
                    RefrigerationControllerBinding.organization_id == organization_id,
                    RefrigerationControllerBinding.equipment_id == equipment_id,
                    RefrigerationControllerBinding.unbound_at.is_(None),
                )
            )
            if binding is None:
                raise ControllerBindingNotFoundError(
                    f"controller binding for equipment {equipment_id!r} was not found"
                )
            session.expunge(binding)
            return binding

    def replace_active(
        self,
        equipment_id: str,
        payload: RefrigerationControllerBindingWrite,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationControllerBinding:
        now = datetime.now(UTC)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    equipment = session.scalar(
                        select(RefrigerationEquipmentRecord)
                        .where(
                            RefrigerationEquipmentRecord.organization_id == organization_id,
                            RefrigerationEquipmentRecord.id == equipment_id,
                            RefrigerationEquipmentRecord.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                    if equipment is None:
                        raise ControllerBindingEquipmentNotFoundError(
                            f"equipment {equipment_id!r} was not found"
                        )
                    if equipment.lifecycle_status == "retired":
                        raise ControllerBindingConflictError(
                            "retired refrigeration equipment cannot receive a controller binding"
                        )
                    if equipment.node_id and equipment.node_id != payload.node_id:
                        raise ControllerBindingConflictError(
                            "controller node does not match the refrigeration equipment node"
                        )

                    self._require_verified_telemetry(session, payload)
                    current = session.scalar(
                        select(RefrigerationControllerBinding)
                        .where(
                            RefrigerationControllerBinding.organization_id == organization_id,
                            RefrigerationControllerBinding.equipment_id == equipment_id,
                            RefrigerationControllerBinding.unbound_at.is_(None),
                        )
                        .with_for_update()
                    )
                    if current is not None and self._matches(current, payload):
                        session.expunge(current)
                        return current

                    before = self._snapshot(current) if current is not None else None
                    if current is not None:
                        current.unbound_by = actor_id.strip()
                        current.unbound_at = now
                        session.flush()

                    binding = RefrigerationControllerBinding(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        equipment_id=equipment_id,
                        node_id=payload.node_id,
                        controller_family=payload.controller_family,
                        controller_equipment_id=payload.controller_equipment_id,
                        unit_id=payload.unit_id,
                        profile_version=payload.profile_version,
                        bound_by=actor_id.strip(),
                        bound_at=now,
                        unbound_by=None,
                        unbound_at=None,
                    )
                    session.add(binding)
                    session.flush()
                    if audit_repository is not None and audit_event is not None:
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=binding.id,
                                before_snapshot=before,
                                after_snapshot=self._snapshot(binding),
                            ),
                            session=session,
                        )
                session.expunge(binding)
                return binding
        except IntegrityError as error:
            raise ControllerBindingConflictError(
                "controller identity is already bound to another refrigeration asset"
            ) from error

    @staticmethod
    def _require_verified_telemetry(
        session: Session,
        payload: RefrigerationControllerBindingWrite,
    ) -> None:
        observed = session.scalar(
            select(TelemetryLatest.id)
            .where(
                TelemetryLatest.node_id == payload.node_id,
                TelemetryLatest.equipment_id == payload.controller_equipment_id,
                TelemetryLatest.source == "embraco-sync",
            )
            .limit(1)
        )
        if observed is None:
            raise ControllerBindingUnverifiedError(
                "controller identity has no verified Embraco telemetry on the requested node"
            )

    @staticmethod
    def _matches(
        current: RefrigerationControllerBinding,
        payload: RefrigerationControllerBindingWrite,
    ) -> bool:
        return (
            current.node_id == payload.node_id
            and current.controller_family == payload.controller_family
            and current.controller_equipment_id == payload.controller_equipment_id
            and current.unit_id == payload.unit_id
            and current.profile_version == payload.profile_version
        )

    @staticmethod
    def _snapshot(binding: RefrigerationControllerBinding | None) -> dict[str, object] | None:
        if binding is None:
            return None
        return {
            "id": binding.id,
            "equipment_id": binding.equipment_id,
            "node_id": binding.node_id,
            "controller_family": binding.controller_family,
            "controller_equipment_id": binding.controller_equipment_id,
            "unit_id": binding.unit_id,
            "profile_version": binding.profile_version,
            "bound_at": binding.bound_at.isoformat(),
            "unbound_at": binding.unbound_at.isoformat() if binding.unbound_at else None,
        }
