from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import (
    ACCEPTANCE_SCHEMA_VERSION,
    CALIBRATION_SCHEMA_VERSION,
    CALIBRATION_STATES,
    Instrument,
    InstrumentAcceptanceRecord,
    InstrumentCalibrationRecord,
    Signal,
)
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    CalibrationAppendRequest,
    InstrumentCreate,
    InstrumentUpdate,
    SignalCreate,
    SignalUpdate,
)
from app.security.repository import AuditEventInput, SecurityRepository


DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class InstrumentationRepositoryError(RuntimeError):
    code = "instrumentation_repository_error"


class InstrumentNotFoundError(InstrumentationRepositoryError):
    code = "instrument_not_found"


class SignalNotFoundError(InstrumentationRepositoryError):
    code = "signal_not_found"


class InstrumentKeyConflictError(InstrumentationRepositoryError):
    code = "instrument_inventory_key_conflict"


class SignalKeyConflictError(InstrumentationRepositoryError):
    code = "signal_business_key_conflict"


class HistoryOrderConflictError(InstrumentationRepositoryError):
    code = "history_effective_time_conflict"


class HistoryIntegrityConflictError(InstrumentationRepositoryError):
    code = "history_integrity_conflict"


class HistoryResolutionError(InstrumentationRepositoryError):
    code = "history_resolution_ambiguous"


class InstrumentVersionConflictError(InstrumentationRepositoryError):
    code = "instrument_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"instrument version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class SignalVersionConflictError(InstrumentationRepositoryError):
    code = "signal_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"signal version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


HistoryRecord = TypeVar(
    "HistoryRecord", InstrumentAcceptanceRecord, InstrumentCalibrationRecord
)


class InstrumentationRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_instruments(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[Instrument]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(Instrument)
                    .where(Instrument.organization_id == organization_id)
                    .order_by(Instrument.display_name.asc(), Instrument.id.asc())
                )
            )
            session.expunge_all()
            return rows

    def get_instrument(
        self,
        instrument_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> Instrument:
        with Session(self._engine, expire_on_commit=False) as session:
            row = self._instrument(session, organization_id, instrument_id)
            session.expunge(row)
            return row

    def create_instrument(
        self,
        payload: InstrumentCreate,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> Instrument:
        now = datetime.now(UTC)
        row = Instrument(
            id=str(uuid4()),
            organization_id=organization_id,
            inventory_key=payload.inventory_key,
            display_name=payload.display_name,
            instrument_kind=payload.instrument_kind,
            manufacturer=payload.manufacturer,
            model=payload.model,
            serial_number=payload.serial_number,
            lifecycle_state=payload.lifecycle_state,
            attributes=dict(payload.metadata),
            version=1,
            created_by=_actor(actor_id),
            updated_by=_actor(actor_id),
            created_at=now,
            updated_at=now,
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    session.add(row)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=row.id,
                        before=None,
                        after=_instrument_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise InstrumentKeyConflictError(
                f"instrument inventory key {payload.inventory_key!r} already exists "
                "in this organization"
            ) from error

    def update_instrument(
        self,
        instrument_id: str,
        payload: InstrumentUpdate,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> Instrument:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    row = self._instrument(
                        session,
                        organization_id,
                        instrument_id,
                        for_update=True,
                    )
                    if row.version != expected_version:
                        raise InstrumentVersionConflictError(
                            expected_version=expected_version,
                            actual_version=row.version,
                        )
                    before = _instrument_snapshot(row)
                    row.inventory_key = payload.inventory_key
                    row.display_name = payload.display_name
                    row.instrument_kind = payload.instrument_kind
                    row.manufacturer = payload.manufacturer
                    row.model = payload.model
                    row.serial_number = payload.serial_number
                    row.lifecycle_state = payload.lifecycle_state
                    row.attributes = dict(payload.metadata)
                    row.version += 1
                    row.updated_by = _actor(actor_id)
                    row.updated_at = datetime.now(UTC)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=row.id,
                        before=before,
                        after=_instrument_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise InstrumentKeyConflictError(
                f"instrument inventory key {payload.inventory_key!r} already exists "
                "in this organization"
            ) from error

    def list_signals(
        self,
        instrument_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[Signal]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(Signal)
                    .where(
                        Signal.organization_id == organization_id,
                        Signal.instrument_id == instrument_id,
                    )
                    .order_by(Signal.display_name.asc(), Signal.id.asc())
                )
            )
            session.expunge_all()
            return rows

    def get_signal(
        self,
        instrument_id: str,
        signal_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> Signal:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            row = self._signal(session, organization_id, instrument_id, signal_id)
            session.expunge(row)
            return row

    def create_signal(
        self,
        instrument_id: str,
        payload: SignalCreate,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> Signal:
        now = datetime.now(UTC)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(
                        session,
                        organization_id,
                        instrument_id,
                        for_update=True,
                    )
                    row = Signal(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        instrument_id=instrument_id,
                        business_key=payload.business_key,
                        display_name=payload.display_name,
                        physical_quantity=payload.physical_quantity,
                        engineering_unit=payload.engineering_unit,
                        lifecycle_state=payload.lifecycle_state,
                        attributes=dict(payload.metadata),
                        version=1,
                        created_by=_actor(actor_id),
                        updated_by=_actor(actor_id),
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=row.id,
                        before=None,
                        after=_signal_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise SignalKeyConflictError(
                f"signal business key {payload.business_key!r} already exists "
                "in this organization"
            ) from error

    def update_signal(
        self,
        instrument_id: str,
        signal_id: str,
        payload: SignalUpdate,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> Signal:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(session, organization_id, instrument_id)
                    row = self._signal(
                        session,
                        organization_id,
                        instrument_id,
                        signal_id,
                        for_update=True,
                    )
                    if row.version != expected_version:
                        raise SignalVersionConflictError(
                            expected_version=expected_version,
                            actual_version=row.version,
                        )
                    before = _signal_snapshot(row)
                    row.business_key = payload.business_key
                    row.display_name = payload.display_name
                    row.physical_quantity = payload.physical_quantity
                    row.engineering_unit = payload.engineering_unit
                    row.lifecycle_state = payload.lifecycle_state
                    row.attributes = dict(payload.metadata)
                    row.version += 1
                    row.updated_by = _actor(actor_id)
                    row.updated_at = datetime.now(UTC)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=row.id,
                        before=before,
                        after=_signal_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise SignalKeyConflictError(
                f"signal business key {payload.business_key!r} already exists "
                "in this organization"
            ) from error

    def list_acceptance_history(
        self,
        instrument_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[InstrumentAcceptanceRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(InstrumentAcceptanceRecord)
                    .where(
                        InstrumentAcceptanceRecord.organization_id
                        == organization_id,
                        InstrumentAcceptanceRecord.instrument_id == instrument_id,
                    )
                    .order_by(
                        InstrumentAcceptanceRecord.effective_from.asc(),
                        InstrumentAcceptanceRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append_acceptance(
        self,
        instrument_id: str,
        payload: AcceptanceAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> InstrumentAcceptanceRecord:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(
                        session,
                        organization_id,
                        instrument_id,
                        for_update=True,
                    )
                    latest = session.scalar(
                        select(InstrumentAcceptanceRecord)
                        .where(
                            InstrumentAcceptanceRecord.organization_id
                            == organization_id,
                            InstrumentAcceptanceRecord.instrument_id == instrument_id,
                        )
                        .order_by(
                            InstrumentAcceptanceRecord.effective_from.desc(),
                            InstrumentAcceptanceRecord.revision.desc(),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                    effective_from = _as_utc(payload.effective_from)
                    previous = (
                        _acceptance_snapshot(latest) if latest is not None else None
                    )
                    self._close_acceptance_interval(latest, effective_from)
                    if latest is not None:
                        session.flush()
                    revision = latest.revision + 1 if latest is not None else 1
                    row = InstrumentAcceptanceRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        instrument_id=instrument_id,
                        schema_version=ACCEPTANCE_SCHEMA_VERSION,
                        accepted_for_calculation=payload.accepted_for_calculation,
                        state_label=payload.state_label,
                        effective_from=effective_from,
                        effective_to=None,
                        revision=revision,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=instrument_id,
                        before=previous,
                        after=_acceptance_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise HistoryIntegrityConflictError(
                "acceptance history append would create an invalid or overlapping interval"
            ) from error

    def resolve_acceptance(
        self,
        instrument_id: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> InstrumentAcceptanceRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(InstrumentAcceptanceRecord).where(
                        InstrumentAcceptanceRecord.organization_id
                        == organization_id,
                        InstrumentAcceptanceRecord.instrument_id == instrument_id,
                        InstrumentAcceptanceRecord.effective_from <= _as_utc(at),
                        or_(
                            InstrumentAcceptanceRecord.effective_to.is_(None),
                            InstrumentAcceptanceRecord.effective_to > _as_utc(at),
                        ),
                    )
                )
            )
            if len(rows) != 1 or rows[0].schema_version != ACCEPTANCE_SCHEMA_VERSION:
                raise HistoryResolutionError(
                    "acceptance history must resolve exactly one supported state"
                )
            row = rows[0]
            if not isinstance(row.accepted_for_calculation, bool):
                raise HistoryResolutionError(
                    "acceptance history contains a non-boolean authority value"
                )
            session.expunge(row)
            return row

    def list_calibration_history(
        self,
        instrument_id: str,
        *,
        calibration_scope: str | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[InstrumentCalibrationRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            statement = select(InstrumentCalibrationRecord).where(
                InstrumentCalibrationRecord.organization_id == organization_id,
                InstrumentCalibrationRecord.instrument_id == instrument_id,
            )
            if calibration_scope is not None:
                statement = statement.where(
                    InstrumentCalibrationRecord.calibration_scope
                    == calibration_scope
                )
            rows = list(
                session.scalars(
                    statement.order_by(
                        InstrumentCalibrationRecord.calibration_scope.asc(),
                        InstrumentCalibrationRecord.valid_from.asc(),
                        InstrumentCalibrationRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append_calibration(
        self,
        instrument_id: str,
        payload: CalibrationAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> InstrumentCalibrationRecord:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(
                        session,
                        organization_id,
                        instrument_id,
                        for_update=True,
                    )
                    latest = session.scalar(
                        select(InstrumentCalibrationRecord)
                        .where(
                            InstrumentCalibrationRecord.organization_id
                            == organization_id,
                            InstrumentCalibrationRecord.instrument_id == instrument_id,
                            InstrumentCalibrationRecord.calibration_scope
                            == payload.calibration_scope,
                        )
                        .order_by(
                            InstrumentCalibrationRecord.valid_from.desc(),
                            InstrumentCalibrationRecord.revision.desc(),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                    valid_from = _as_utc(payload.valid_from)
                    previous = (
                        _calibration_snapshot(latest) if latest is not None else None
                    )
                    self._close_calibration_interval(latest, valid_from)
                    if latest is not None:
                        session.flush()
                    revision = latest.revision + 1 if latest is not None else 1
                    row = InstrumentCalibrationRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        instrument_id=instrument_id,
                        calibration_scope=payload.calibration_scope,
                        schema_version=CALIBRATION_SCHEMA_VERSION,
                        state=payload.state,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=revision,
                        certificate_reference=payload.certificate_reference,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=instrument_id,
                        before=previous,
                        after=_calibration_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise HistoryIntegrityConflictError(
                "calibration history append would create an invalid or overlapping interval"
            ) from error

    def resolve_calibration(
        self,
        instrument_id: str,
        at: datetime,
        *,
        calibration_scope: str = "instrument",
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> InstrumentCalibrationRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(InstrumentCalibrationRecord).where(
                        InstrumentCalibrationRecord.organization_id == organization_id,
                        InstrumentCalibrationRecord.instrument_id == instrument_id,
                        InstrumentCalibrationRecord.calibration_scope
                        == calibration_scope,
                        InstrumentCalibrationRecord.valid_from <= _as_utc(at),
                        or_(
                            InstrumentCalibrationRecord.valid_to.is_(None),
                            InstrumentCalibrationRecord.valid_to > _as_utc(at),
                        ),
                    )
                )
            )
            if (
                len(rows) != 1
                or rows[0].schema_version != CALIBRATION_SCHEMA_VERSION
                or rows[0].state not in CALIBRATION_STATES
            ):
                raise HistoryResolutionError(
                    "calibration history must resolve exactly one supported state"
                )
            row = rows[0]
            session.expunge(row)
            return row

    @staticmethod
    def _instrument(
        session: Session,
        organization_id: str,
        instrument_id: str,
        *,
        for_update: bool = False,
    ) -> Instrument:
        statement = select(Instrument).where(
            Instrument.organization_id == organization_id,
            Instrument.id == instrument_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise InstrumentNotFoundError(
                f"instrument {instrument_id!r} was not found"
            )
        return row

    @staticmethod
    def _signal(
        session: Session,
        organization_id: str,
        instrument_id: str,
        signal_id: str,
        *,
        for_update: bool = False,
    ) -> Signal:
        statement = select(Signal).where(
            Signal.organization_id == organization_id,
            Signal.instrument_id == instrument_id,
            Signal.id == signal_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise SignalNotFoundError(f"signal {signal_id!r} was not found")
        return row

    @staticmethod
    def _close_acceptance_interval(
        latest: InstrumentAcceptanceRecord | None,
        effective_from: datetime,
    ) -> None:
        if latest is None:
            return
        if latest.effective_to is not None:
            raise HistoryIntegrityConflictError(
                "acceptance history has no single open current interval"
            )
        if effective_from < _as_utc(latest.effective_from):
            raise HistoryOrderConflictError(
                "acceptance states must be appended in non-decreasing effective-time order"
            )
        latest.effective_to = effective_from

    @staticmethod
    def _close_calibration_interval(
        latest: InstrumentCalibrationRecord | None,
        valid_from: datetime,
    ) -> None:
        if latest is None:
            return
        if latest.valid_to is not None:
            raise HistoryIntegrityConflictError(
                "calibration history has no single open current interval"
            )
        if valid_from < _as_utc(latest.valid_from):
            raise HistoryOrderConflictError(
                "calibration states must be appended in non-decreasing validity-time order"
            )
        latest.valid_to = valid_from

    @staticmethod
    def _append_audit(
        session: Session,
        audit_repository: SecurityRepository | None,
        audit_event: AuditEventInput | None,
        *,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        if audit_repository is None or audit_event is None:
            return
        audit_repository.append_audit_event(
            replace(
                audit_event,
                entity_id=entity_id,
                before_snapshot=before,
                after_snapshot=after,
            ),
            session=session,
        )


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("actor_id must not be blank")
    return normalized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _instrument_snapshot(row: Instrument) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "inventory_key": row.inventory_key,
        "display_name": row.display_name,
        "instrument_kind": row.instrument_kind,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "serial_number": row.serial_number,
        "lifecycle_state": row.lifecycle_state,
        "metadata": dict(row.attributes),
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _signal_snapshot(row: Signal) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "instrument_id": row.instrument_id,
        "business_key": row.business_key,
        "display_name": row.display_name,
        "physical_quantity": row.physical_quantity,
        "engineering_unit": row.engineering_unit,
        "lifecycle_state": row.lifecycle_state,
        "metadata": dict(row.attributes),
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _acceptance_snapshot(row: InstrumentAcceptanceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "instrument_id": row.instrument_id,
        "schema_version": row.schema_version,
        "accepted_for_calculation": row.accepted_for_calculation,
        "state_label": row.state_label,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "revision": row.revision,
        "recorded_by": row.recorded_by,
        "recorded_at": row.recorded_at.isoformat(),
    }


def _calibration_snapshot(row: InstrumentCalibrationRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "instrument_id": row.instrument_id,
        "calibration_scope": row.calibration_scope,
        "schema_version": row.schema_version,
        "state": row.state,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "revision": row.revision,
        "certificate_reference": row.certificate_reference,
        "recorded_by": row.recorded_by,
        "recorded_at": row.recorded_at.isoformat(),
    }
