from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import Instrument, InstrumentAcceptanceRecord, Signal
from app.refrigeration.circuit_models import (
    CIRCUIT_PROCESS_ROLES,
    RefrigerationCircuit,
    RefrigerationCircuitConfigurationRecord,
    RefrigerationCircuitLifecycleRecord,
    RefrigerationCircuitSignalBinding,
)
from app.refrigeration.circuit_schemas import (
    CircuitBindingAppendRequest,
    CircuitConfigurationAppendRequest,
    CircuitCreateRequest,
    CircuitLifecycleAppendRequest,
)
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import AuditEventInput, SecurityRepository


PRESSURE_UNITS = frozenset({"bar", "kPa"})
TEMPERATURE_UNITS = frozenset({"degC"})
HUMIDITY_UNITS = frozenset({"%RH"})


class CircuitDomainError(RuntimeError):
    code = "refrigeration_circuit_error"


class CircuitNotFoundError(CircuitDomainError):
    code = "refrigeration_circuit_not_found"


class CircuitEquipmentNotFoundError(CircuitDomainError):
    code = "refrigeration_circuit_equipment_not_found"


class CircuitConflictError(CircuitDomainError):
    code = "refrigeration_circuit_conflict"


class CircuitHistoryOrderError(CircuitDomainError):
    code = "refrigeration_circuit_history_order_conflict"


class CircuitResolutionError(CircuitDomainError):
    code = "refrigeration_circuit_resolution_unavailable"


class CircuitSignalNotFoundError(CircuitDomainError):
    code = "refrigeration_circuit_signal_not_found"


class CircuitBindingCompatibilityError(CircuitDomainError):
    code = "refrigeration_circuit_binding_incompatible"


class CircuitBindingNotFoundError(CircuitDomainError):
    code = "refrigeration_circuit_binding_not_found"


@dataclass(frozen=True, slots=True)
class ResolvedCircuitBinding:
    binding: RefrigerationCircuitSignalBinding
    signal: Signal
    instrument: Instrument


class RefrigerationCircuitRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_circuits(
        self, *, organization_id: str = DEFAULT_ORGANIZATION_ID
    ) -> list[RefrigerationCircuit]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(RefrigerationCircuit)
                    .where(RefrigerationCircuit.organization_id == organization_id)
                    .order_by(
                        RefrigerationCircuit.display_name.asc(),
                        RefrigerationCircuit.business_key.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def get_circuit(
        self,
        circuit_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationCircuit:
        with Session(self._engine, expire_on_commit=False) as session:
            row = self._circuit(session, organization_id, circuit_id)
            session.expunge(row)
            return row

    def create_circuit(
        self,
        payload: CircuitCreateRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> tuple[RefrigerationCircuit, RefrigerationCircuitLifecycleRecord]:
        now = datetime.now(UTC)
        valid_from = _as_utc(payload.valid_from)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    equipment = session.scalar(
                        select(RefrigerationEquipmentRecord)
                        .where(
                            RefrigerationEquipmentRecord.organization_id == organization_id,
                            RefrigerationEquipmentRecord.id == payload.equipment_id,
                            RefrigerationEquipmentRecord.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                    if equipment is None:
                        raise CircuitEquipmentNotFoundError(
                            f"refrigeration equipment {payload.equipment_id!r} was not found"
                        )
                    circuit = RefrigerationCircuit(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        equipment_id=payload.equipment_id,
                        business_key=payload.business_key,
                        display_name=payload.display_name,
                        created_by=_actor(actor_id),
                        created_at=now,
                    )
                    lifecycle = RefrigerationCircuitLifecycleRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        circuit_id=circuit.id,
                        state=payload.initial_state,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=1,
                        recorded_by=_actor(actor_id),
                        recorded_at=now,
                    )
                    session.add_all([circuit, lifecycle])
                    session.flush()
                    self._audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=circuit.id,
                        before=None,
                        after={
                            **_circuit_snapshot(circuit),
                            "initial_lifecycle": _lifecycle_snapshot(lifecycle),
                        },
                    )
                session.expunge(circuit)
                session.expunge(lifecycle)
                return circuit, lifecycle
        except IntegrityError as error:
            raise CircuitConflictError(
                "refrigeration circuit identity conflicts with existing organization state"
            ) from error

    def list_lifecycle_history(
        self,
        circuit_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[RefrigerationCircuitLifecycleRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitLifecycleRecord)
                    .where(
                        RefrigerationCircuitLifecycleRecord.organization_id == organization_id,
                        RefrigerationCircuitLifecycleRecord.circuit_id == circuit_id,
                    )
                    .order_by(
                        RefrigerationCircuitLifecycleRecord.valid_from.asc(),
                        RefrigerationCircuitLifecycleRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append_lifecycle(
        self,
        circuit_id: str,
        payload: CircuitLifecycleAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationCircuitLifecycleRecord:
        valid_from = _as_utc(payload.valid_from)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._circuit(session, organization_id, circuit_id, for_update=True)
                    latest = self._latest_lifecycle(session, organization_id, circuit_id)
                    previous = _lifecycle_snapshot(latest) if latest else None
                    revision = self._close_interval(latest, valid_from, "lifecycle")
                    if latest is not None:
                        session.flush()
                    row = RefrigerationCircuitLifecycleRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        circuit_id=circuit_id,
                        state=payload.state,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=revision,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    self._audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=circuit_id,
                        before=previous,
                        after=_lifecycle_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise CircuitConflictError("circuit lifecycle history is invalid or overlapping") from error

    def resolve_lifecycle(
        self,
        circuit_id: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationCircuitLifecycleRecord:
        resolved_at = _require_aware(at, "lifecycle resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitLifecycleRecord).where(
                        RefrigerationCircuitLifecycleRecord.organization_id == organization_id,
                        RefrigerationCircuitLifecycleRecord.circuit_id == circuit_id,
                        RefrigerationCircuitLifecycleRecord.valid_from <= resolved_at,
                        or_(
                            RefrigerationCircuitLifecycleRecord.valid_to.is_(None),
                            RefrigerationCircuitLifecycleRecord.valid_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise CircuitResolutionError(
                    "circuit lifecycle must resolve exactly one effective state"
                )
            row = rows[0]
            session.expunge(row)
            return row

    def list_configuration_history(
        self,
        circuit_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[RefrigerationCircuitConfigurationRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitConfigurationRecord)
                    .where(
                        RefrigerationCircuitConfigurationRecord.organization_id == organization_id,
                        RefrigerationCircuitConfigurationRecord.circuit_id == circuit_id,
                    )
                    .order_by(
                        RefrigerationCircuitConfigurationRecord.valid_from.asc(),
                        RefrigerationCircuitConfigurationRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append_configuration(
        self,
        circuit_id: str,
        payload: CircuitConfigurationAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationCircuitConfigurationRecord:
        valid_from = _as_utc(payload.valid_from)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._circuit(session, organization_id, circuit_id, for_update=True)
                    latest = self._latest_configuration(session, organization_id, circuit_id)
                    previous = _configuration_snapshot(latest) if latest else None
                    revision = self._close_interval(latest, valid_from, "configuration")
                    if latest is not None:
                        session.flush()
                    row = RefrigerationCircuitConfigurationRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        circuit_id=circuit_id,
                        schema_version=payload.schema_version,
                        refrigerant_code=payload.refrigerant_code,
                        calculation_policy_version=payload.calculation_policy_version,
                        property_provider_profile=payload.property_provider_profile,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=revision,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    self._audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=circuit_id,
                        before=previous,
                        after=_configuration_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise CircuitConflictError(
                "circuit configuration history is invalid or overlapping"
            ) from error

    def resolve_configuration(
        self,
        circuit_id: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationCircuitConfigurationRecord:
        resolved_at = _require_aware(at, "configuration resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitConfigurationRecord).where(
                        RefrigerationCircuitConfigurationRecord.organization_id == organization_id,
                        RefrigerationCircuitConfigurationRecord.circuit_id == circuit_id,
                        RefrigerationCircuitConfigurationRecord.valid_from <= resolved_at,
                        or_(
                            RefrigerationCircuitConfigurationRecord.valid_to.is_(None),
                            RefrigerationCircuitConfigurationRecord.valid_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise CircuitResolutionError(
                    "circuit configuration must resolve exactly one effective version"
                )
            row = rows[0]
            session.expunge(row)
            return row

    def list_bindings(
        self,
        circuit_id: str,
        *,
        include_history: bool = False,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[ResolvedCircuitBinding]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            statement = select(RefrigerationCircuitSignalBinding).where(
                RefrigerationCircuitSignalBinding.organization_id == organization_id,
                RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
            )
            if not include_history:
                statement = statement.where(RefrigerationCircuitSignalBinding.valid_to.is_(None))
            rows = list(
                session.scalars(
                    statement.order_by(
                        RefrigerationCircuitSignalBinding.role.asc(),
                        RefrigerationCircuitSignalBinding.valid_from.asc(),
                        RefrigerationCircuitSignalBinding.revision.asc(),
                    )
                )
            )
            result = [self._binding_view(session, row, organization_id) for row in rows]
            session.expunge_all()
            return result

    def get_binding(
        self,
        circuit_id: str,
        binding_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> ResolvedCircuitBinding:
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            row = session.scalar(
                select(RefrigerationCircuitSignalBinding).where(
                    RefrigerationCircuitSignalBinding.organization_id == organization_id,
                    RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
                    RefrigerationCircuitSignalBinding.id == binding_id,
                )
            )
            if row is None:
                raise CircuitBindingNotFoundError(
                    f"semantic binding {binding_id!r} was not found"
                )
            result = self._binding_view(session, row, organization_id)
            session.expunge_all()
            return result

    def append_binding(
        self,
        circuit_id: str,
        payload: CircuitBindingAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> ResolvedCircuitBinding:
        valid_from = _as_utc(payload.valid_from)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._circuit(session, organization_id, circuit_id, for_update=True)
                    signal, instrument = self._signal_and_instrument(
                        session, organization_id, payload.signal_id, for_update=True
                    )
                    self._validate_binding_authority(
                        session,
                        organization_id,
                        signal,
                        instrument,
                        payload.role,
                        valid_from,
                    )
                    latest = self._latest_binding(
                        session, organization_id, circuit_id, payload.role
                    )
                    previous = _binding_snapshot(latest) if latest else None
                    revision = self._close_interval(latest, valid_from, "binding")
                    if latest is not None:
                        latest.ended_by = _actor(actor_id)
                        latest.ended_at = datetime.now(UTC)
                        session.flush()
                    row = RefrigerationCircuitSignalBinding(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        circuit_id=circuit_id,
                        signal_id=signal.id,
                        role=payload.role,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=revision,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                        ended_by=None,
                        ended_at=None,
                    )
                    session.add(row)
                    session.flush()
                    self._audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=circuit_id,
                        before=previous,
                        after=_binding_snapshot(row),
                    )
                    result = ResolvedCircuitBinding(row, signal, instrument)
                session.expunge_all()
                return result
        except IntegrityError as error:
            raise CircuitConflictError(
                "circuit semantic binding history is invalid or overlapping"
            ) from error

    def end_binding(
        self,
        circuit_id: str,
        role: str,
        valid_to: datetime,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> ResolvedCircuitBinding:
        if role not in CIRCUIT_PROCESS_ROLES:
            raise CircuitBindingCompatibilityError(f"unsupported circuit role {role!r}")
        resolved_valid_to = _require_aware(valid_to, "binding valid_to")
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._circuit(session, organization_id, circuit_id, for_update=True)
                row = session.scalar(
                    select(RefrigerationCircuitSignalBinding)
                    .where(
                        RefrigerationCircuitSignalBinding.organization_id == organization_id,
                        RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
                        RefrigerationCircuitSignalBinding.role == role,
                        RefrigerationCircuitSignalBinding.valid_to.is_(None),
                    )
                    .with_for_update()
                )
                if row is None:
                    raise CircuitBindingNotFoundError(
                        f"no open semantic binding exists for role {role!r}"
                    )
                if resolved_valid_to <= _as_utc(row.valid_from):
                    raise CircuitHistoryOrderError(
                        "binding valid_to must be strictly later than valid_from"
                    )
                before = _binding_snapshot(row)
                row.valid_to = resolved_valid_to
                row.ended_by = _actor(actor_id)
                row.ended_at = datetime.now(UTC)
                session.flush()
                result = self._binding_view(session, row, organization_id)
                self._audit(
                    session,
                    audit_repository,
                    audit_event,
                    entity_id=circuit_id,
                    before=before,
                    after=_binding_snapshot(row),
                )
            session.expunge_all()
            return result

    def resolve_binding(
        self,
        circuit_id: str,
        role: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> ResolvedCircuitBinding:
        if role not in CIRCUIT_PROCESS_ROLES:
            raise CircuitBindingCompatibilityError(f"unsupported circuit role {role!r}")
        resolved_at = _require_aware(at, "binding resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitSignalBinding).where(
                        RefrigerationCircuitSignalBinding.organization_id == organization_id,
                        RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
                        RefrigerationCircuitSignalBinding.role == role,
                        RefrigerationCircuitSignalBinding.valid_from <= resolved_at,
                        or_(
                            RefrigerationCircuitSignalBinding.valid_to.is_(None),
                            RefrigerationCircuitSignalBinding.valid_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise CircuitResolutionError(
                    f"role {role!r} must resolve exactly one effective Signal binding"
                )
            view = self._binding_view(session, rows[0], organization_id)
            self._validate_binding_authority(
                session,
                organization_id,
                view.signal,
                view.instrument,
                role,
                resolved_at,
                require_current_active=False,
            )
            session.expunge_all()
            return view

    def resolve_binding_identity(
        self,
        circuit_id: str,
        role: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> ResolvedCircuitBinding:
        """Resolve historical binding identity without conflating acceptance gates."""
        if role not in CIRCUIT_PROCESS_ROLES:
            raise CircuitBindingCompatibilityError(f"unsupported circuit role {role!r}")
        resolved_at = _require_aware(at, "binding resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._circuit(session, organization_id, circuit_id)
            rows = list(
                session.scalars(
                    select(RefrigerationCircuitSignalBinding).where(
                        RefrigerationCircuitSignalBinding.organization_id == organization_id,
                        RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
                        RefrigerationCircuitSignalBinding.role == role,
                        RefrigerationCircuitSignalBinding.valid_from <= resolved_at,
                        or_(
                            RefrigerationCircuitSignalBinding.valid_to.is_(None),
                            RefrigerationCircuitSignalBinding.valid_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise CircuitResolutionError(
                    f"role {role!r} must resolve exactly one effective Signal binding"
                )
            view = self._binding_view(session, rows[0], organization_id)
            self._validate_role_shape(view.signal, view.instrument, role)
            session.expunge_all()
            return view

    def _circuit(
        self,
        session: Session,
        organization_id: str,
        circuit_id: str,
        *,
        for_update: bool = False,
    ) -> RefrigerationCircuit:
        statement = select(RefrigerationCircuit).where(
            RefrigerationCircuit.organization_id == organization_id,
            RefrigerationCircuit.id == circuit_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise CircuitNotFoundError(f"refrigeration circuit {circuit_id!r} was not found")
        return row

    def _latest_lifecycle(
        self, session: Session, organization_id: str, circuit_id: str
    ) -> RefrigerationCircuitLifecycleRecord | None:
        return session.scalar(
            select(RefrigerationCircuitLifecycleRecord)
            .where(
                RefrigerationCircuitLifecycleRecord.organization_id == organization_id,
                RefrigerationCircuitLifecycleRecord.circuit_id == circuit_id,
            )
            .order_by(
                RefrigerationCircuitLifecycleRecord.valid_from.desc(),
                RefrigerationCircuitLifecycleRecord.revision.desc(),
            )
            .limit(1)
            .with_for_update()
        )

    def _latest_configuration(
        self, session: Session, organization_id: str, circuit_id: str
    ) -> RefrigerationCircuitConfigurationRecord | None:
        return session.scalar(
            select(RefrigerationCircuitConfigurationRecord)
            .where(
                RefrigerationCircuitConfigurationRecord.organization_id == organization_id,
                RefrigerationCircuitConfigurationRecord.circuit_id == circuit_id,
            )
            .order_by(
                RefrigerationCircuitConfigurationRecord.valid_from.desc(),
                RefrigerationCircuitConfigurationRecord.revision.desc(),
            )
            .limit(1)
            .with_for_update()
        )

    def _latest_binding(
        self, session: Session, organization_id: str, circuit_id: str, role: str
    ) -> RefrigerationCircuitSignalBinding | None:
        return session.scalar(
            select(RefrigerationCircuitSignalBinding)
            .where(
                RefrigerationCircuitSignalBinding.organization_id == organization_id,
                RefrigerationCircuitSignalBinding.circuit_id == circuit_id,
                RefrigerationCircuitSignalBinding.role == role,
            )
            .order_by(
                RefrigerationCircuitSignalBinding.valid_from.desc(),
                RefrigerationCircuitSignalBinding.revision.desc(),
            )
            .limit(1)
            .with_for_update()
        )

    @staticmethod
    def _close_interval(row: Any | None, valid_from: datetime, label: str) -> int:
        if row is None:
            return 1
        if row.valid_to is not None:
            raise CircuitHistoryOrderError(
                f"{label} history has no single open current interval"
            )
        if valid_from <= _as_utc(row.valid_from):
            raise CircuitHistoryOrderError(
                f"{label} states must be appended in strictly increasing effective-time order"
            )
        row.valid_to = valid_from
        return int(row.revision) + 1

    def _signal_and_instrument(
        self,
        session: Session,
        organization_id: str,
        signal_id: str,
        *,
        for_update: bool = False,
    ) -> tuple[Signal, Instrument]:
        statement = select(Signal).where(
            Signal.organization_id == organization_id,
            Signal.id == signal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        signal = session.scalar(statement)
        if signal is None:
            raise CircuitSignalNotFoundError(f"Signal {signal_id!r} was not found")
        instrument_statement = select(Instrument).where(
            Instrument.organization_id == organization_id,
            Instrument.id == signal.instrument_id,
        )
        if for_update:
            instrument_statement = instrument_statement.with_for_update()
        instrument = session.scalar(instrument_statement)
        if instrument is None:
            raise CircuitSignalNotFoundError("owning Instrument was not found")
        return signal, instrument

    def _binding_view(
        self,
        session: Session,
        row: RefrigerationCircuitSignalBinding,
        organization_id: str,
    ) -> ResolvedCircuitBinding:
        signal, instrument = self._signal_and_instrument(
            session, organization_id, row.signal_id
        )
        self._validate_role_shape(signal, instrument, row.role)
        return ResolvedCircuitBinding(row, signal, instrument)

    def _validate_binding_authority(
        self,
        session: Session,
        organization_id: str,
        signal: Signal,
        instrument: Instrument,
        role: str,
        at: datetime,
        *,
        require_current_active: bool = True,
    ) -> None:
        self._validate_role_shape(signal, instrument, role)
        if require_current_active and (
            signal.lifecycle_state != "active" or instrument.lifecycle_state != "active"
        ):
            raise CircuitBindingCompatibilityError(
                "semantic binding requires active Instrument and Signal identities"
            )
        acceptance = list(
            session.scalars(
                select(InstrumentAcceptanceRecord).where(
                    InstrumentAcceptanceRecord.organization_id == organization_id,
                    InstrumentAcceptanceRecord.instrument_id == instrument.id,
                    InstrumentAcceptanceRecord.effective_from <= at,
                    or_(
                        InstrumentAcceptanceRecord.effective_to.is_(None),
                        InstrumentAcceptanceRecord.effective_to > at,
                    ),
                )
            )
        )
        if len(acceptance) != 1 or acceptance[0].accepted_for_calculation is not True:
            raise CircuitBindingCompatibilityError(
                "semantic binding requires exactly one accepted Instrument authority as-of binding time"
            )

    @staticmethod
    def _validate_role_shape(signal: Signal, instrument: Instrument, role: str) -> None:
        if role not in CIRCUIT_PROCESS_ROLES:
            raise CircuitBindingCompatibilityError(f"unsupported circuit role {role!r}")
        quantity = signal.physical_quantity
        unit = signal.engineering_unit
        if role in {"suction_pressure", "condensing_pressure", "atmospheric_pressure"}:
            if quantity != "pressure" or unit not in PRESSURE_UNITS:
                raise CircuitBindingCompatibilityError(
                    f"role {role!r} requires pressure Signal in an accepted explicit pressure unit"
                )
            if instrument.pressure_reference not in {"absolute", "gauge"}:
                raise CircuitBindingCompatibilityError(
                    "pressure semantic binding requires explicit absolute or gauge reference"
                )
            if role == "atmospheric_pressure" and (
                instrument.pressure_reference != "absolute"
                or instrument.instrument_kind != "barometric_pressure_sensor"
            ):
                raise CircuitBindingCompatibilityError(
                    "atmospheric_pressure requires barometric_pressure_sensor with absolute reference"
                )
            return
        if role in {"suction_line_temperature", "liquid_line_temperature"}:
            if quantity != "temperature" or unit not in TEMPERATURE_UNITS:
                raise CircuitBindingCompatibilityError(
                    f"role {role!r} requires temperature Signal in degC"
                )
            return
        if role == "relative_humidity":
            if quantity != "relative_humidity" or unit not in HUMIDITY_UNITS:
                raise CircuitBindingCompatibilityError(
                    "relative_humidity role requires relative_humidity Signal in %RH"
                )
            return
        raise CircuitBindingCompatibilityError(f"unsupported circuit role {role!r}")

    @staticmethod
    def _audit(
        session: Session,
        repository: SecurityRepository | None,
        event: AuditEventInput | None,
        *,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        if repository is None or event is None:
            return
        repository.append_audit_event(
            replace(
                event,
                entity_id=entity_id,
                before_snapshot=before,
                after_snapshot=after,
            ),
            session=session,
        )


def _actor(actor_id: str) -> str:
    normalized = actor_id.strip()
    if not normalized:
        raise ValueError("actor_id must not be blank")
    return normalized


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dt(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value is not None else None


def _circuit_snapshot(row: RefrigerationCircuit) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "equipment_id": row.equipment_id,
        "business_key": row.business_key,
        "display_name": row.display_name,
        "created_by": row.created_by,
        "created_at": _dt(row.created_at),
    }


def _lifecycle_snapshot(row: RefrigerationCircuitLifecycleRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "circuit_id": row.circuit_id,
        "state": row.state,
        "calculation_enabled": row.state == "active",
        "valid_from": _dt(row.valid_from),
        "valid_to": _dt(row.valid_to),
        "revision": row.revision,
        "recorded_by": row.recorded_by,
    }


def _configuration_snapshot(row: RefrigerationCircuitConfigurationRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "circuit_id": row.circuit_id,
        "schema_version": row.schema_version,
        "refrigerant_code": row.refrigerant_code,
        "calculation_policy_version": row.calculation_policy_version,
        "property_provider_profile": row.property_provider_profile,
        "valid_from": _dt(row.valid_from),
        "valid_to": _dt(row.valid_to),
        "revision": row.revision,
        "recorded_by": row.recorded_by,
    }


def _binding_snapshot(row: RefrigerationCircuitSignalBinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "circuit_id": row.circuit_id,
        "signal_id": row.signal_id,
        "role": row.role,
        "valid_from": _dt(row.valid_from),
        "valid_to": _dt(row.valid_to),
        "revision": row.revision,
        "recorded_by": row.recorded_by,
        "ended_by": row.ended_by,
        "ended_at": _dt(row.ended_at),
    }
