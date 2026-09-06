from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import (
    ACCEPTANCE_SCHEMA_VERSION,
    ACQUISITION_SOURCE_SCHEMA_VERSION,
    ANALOG_ELECTRICAL_INPUT_CLASSES,
    ANALOG_EVIDENCE_STATUSES,
    ANALOG_RANGE_POLICIES,
    ANALOG_SCALING_POLICIES,
    ANALOG_SCALING_SCHEMA_VERSION,
    AnalogScalingProfileRecord,
    CALIBRATION_SCHEMA_VERSION,
    CALIBRATION_STATES,
    Instrument,
    InstrumentAcceptanceRecord,
    InstrumentCalibrationRecord,
    Signal,
    SignalAcquisitionSourceRecord,
)
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    AcquisitionSourceAppendRequest,
    AnalogScalingProfileAppendRequest,
    CalibrationAppendRequest,
    InstrumentCreate,
    InstrumentUpdate,
    SignalCreate,
    SignalUpdate,
)
from app.instrumentation.scaling import scale_linear_two_point
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


class PressureReferenceRequiredError(InstrumentationRepositoryError):
    code = "pressure_reference_required"


class InstrumentIdentityConflictError(InstrumentationRepositoryError):
    code = "instrument_identity_immutable"


class SignalIdentityConflictError(InstrumentationRepositoryError):
    code = "signal_identity_immutable"


class HistoryOrderConflictError(InstrumentationRepositoryError):
    code = "history_effective_time_conflict"


class HistoryIntegrityConflictError(InstrumentationRepositoryError):
    code = "history_integrity_conflict"


class HistoryResolutionError(InstrumentationRepositoryError):
    code = "history_resolution_ambiguous"


class AnalogScalingUnitMismatchError(InstrumentationRepositoryError):
    code = "analog_scaling_unit_mismatch"


class AnalogScalingResolutionError(InstrumentationRepositoryError):
    code = "analog_scaling_resolution_unavailable"


class AcquisitionSourceUnitMismatchError(InstrumentationRepositoryError):
    code = "acquisition_source_unit_mismatch"


class AcquisitionSourceResolutionError(InstrumentationRepositoryError):
    code = "acquisition_source_resolution_unavailable"


class HumiditySignalUnsupportedError(InstrumentationRepositoryError):
    code = "humidity_signal_unsupported"


class AnalogScalingSourceMismatchError(AcquisitionSourceResolutionError):
    code = "analog_scaling_source_mismatch"


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
            pressure_reference=payload.pressure_reference,
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
                    self._require_stable_instrument_identity(session, row, payload)
                    row.display_name = payload.display_name
                    row.manufacturer = payload.manufacturer
                    row.model = payload.model
                    row.serial_number = payload.serial_number
                    row.pressure_reference = payload.pressure_reference
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
                    instrument = self._instrument(
                        session,
                        organization_id,
                        instrument_id,
                        for_update=True,
                    )
                    _require_pressure_reference(instrument, payload.physical_quantity)
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
                    instrument = self._instrument(
                        session, organization_id, instrument_id, for_update=True
                    )
                    _require_pressure_reference(instrument, payload.physical_quantity)
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
                    self._require_stable_signal_identity(row, payload)
                    row.display_name = payload.display_name
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

    def list_analog_scaling_history(
        self,
        instrument_id: str,
        signal_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[AnalogScalingProfileRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            self._signal(session, organization_id, instrument_id, signal_id)
            rows = list(
                session.scalars(
                    select(AnalogScalingProfileRecord)
                    .where(
                        AnalogScalingProfileRecord.organization_id == organization_id,
                        AnalogScalingProfileRecord.signal_id == signal_id,
                    )
                    .order_by(
                        AnalogScalingProfileRecord.effective_from.asc(),
                        AnalogScalingProfileRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def list_acquisition_source_history(
        self,
        instrument_id: str,
        signal_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[SignalAcquisitionSourceRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            self._signal(session, organization_id, instrument_id, signal_id)
            rows = list(
                session.scalars(
                    select(SignalAcquisitionSourceRecord)
                    .where(
                        SignalAcquisitionSourceRecord.organization_id
                        == organization_id,
                        SignalAcquisitionSourceRecord.signal_id == signal_id,
                    )
                    .order_by(
                        SignalAcquisitionSourceRecord.valid_from.asc(),
                        SignalAcquisitionSourceRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append_acquisition_source(
        self,
        instrument_id: str,
        signal_id: str,
        payload: AcquisitionSourceAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> SignalAcquisitionSourceRecord:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(session, organization_id, instrument_id)
                    signal = self._signal(
                        session,
                        organization_id,
                        instrument_id,
                        signal_id,
                        for_update=True,
                    )
                    if payload.unit != signal.engineering_unit:
                        raise AcquisitionSourceUnitMismatchError(
                            "acquisition source unit must match the owning Signal"
                        )
                    latest = session.scalar(
                        select(SignalAcquisitionSourceRecord)
                        .where(
                            SignalAcquisitionSourceRecord.organization_id
                            == organization_id,
                            SignalAcquisitionSourceRecord.signal_id == signal_id,
                        )
                        .order_by(
                            SignalAcquisitionSourceRecord.valid_from.desc(),
                            SignalAcquisitionSourceRecord.revision.desc(),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                    valid_from = _as_utc(payload.valid_from)
                    previous = _acquisition_source_snapshot(latest) if latest else None
                    self._close_acquisition_source_interval(latest, valid_from)
                    if latest is not None:
                        session.flush()
                    row = SignalAcquisitionSourceRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        signal_id=signal_id,
                        schema_version=payload.schema_version,
                        node_id=payload.node_id,
                        equipment_id=payload.equipment_id,
                        channel_id=payload.channel_id,
                        metric=payload.metric,
                        unit=payload.unit,
                        evidence_status=payload.evidence_status,
                        evidence_reference=payload.evidence_reference,
                        valid_from=valid_from,
                        valid_to=None,
                        revision=(latest.revision + 1 if latest else 1),
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        entity_id=signal_id,
                        before=previous,
                        after=_acquisition_source_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise HistoryIntegrityConflictError(
                "acquisition source append would create an invalid or overlapping interval"
            ) from error

    def resolve_acquisition_source(
        self,
        instrument_id: str,
        signal_id: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> SignalAcquisitionSourceRecord:
        resolved_at = _require_aware_utc(at, "acquisition source resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            signal = self._signal(session, organization_id, instrument_id, signal_id)
            rows = list(
                session.scalars(
                    select(SignalAcquisitionSourceRecord).where(
                        SignalAcquisitionSourceRecord.organization_id
                        == organization_id,
                        SignalAcquisitionSourceRecord.signal_id == signal_id,
                        SignalAcquisitionSourceRecord.valid_from <= resolved_at,
                        or_(
                            SignalAcquisitionSourceRecord.valid_to.is_(None),
                            SignalAcquisitionSourceRecord.valid_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise AcquisitionSourceResolutionError(
                    "acquisition source history must resolve exactly one effective binding"
                )
            row = rows[0]
            if (
                row.schema_version != ACQUISITION_SOURCE_SCHEMA_VERSION
                or row.evidence_status not in ANALOG_EVIDENCE_STATUSES
                or row.unit != signal.engineering_unit
                or not all((row.node_id, row.equipment_id, row.channel_id, row.metric))
            ):
                raise AcquisitionSourceResolutionError(
                    "acquisition source binding contains unsupported or inconsistent semantics"
                )
            session.expunge(row)
            return row

    def evaluate_humidity_observation(
        self,
        instrument_id: str,
        signal_id: str,
        raw_value: Decimal,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> tuple[SignalAcquisitionSourceRecord, AnalogScalingProfileRecord, Decimal]:
        instrument = self.get_instrument(instrument_id, organization_id=organization_id)
        signal = self.get_signal(
            instrument_id, signal_id, organization_id=organization_id
        )
        if (
            instrument.instrument_kind != "humidity_transmitter"
            or signal.physical_quantity != "relative_humidity"
            or signal.engineering_unit != "%RH"
        ):
            raise HumiditySignalUnsupportedError(
                "humidity evaluation requires humidity_transmitter / relative_humidity / %RH"
            )
        source = self.resolve_acquisition_source(
            instrument_id, signal_id, at, organization_id=organization_id
        )
        profile, value = self.evaluate_analog_scaling(
            instrument_id,
            signal_id,
            raw_value,
            at,
            organization_id=organization_id,
            expected_acquisition_source_id=source.id,
        )
        return source, profile, value

    def append_analog_scaling_profile(
        self,
        instrument_id: str,
        signal_id: str,
        payload: AnalogScalingProfileAppendRequest,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> AnalogScalingProfileRecord:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    self._instrument(session, organization_id, instrument_id)
                    signal = self._signal(
                        session,
                        organization_id,
                        instrument_id,
                        signal_id,
                        for_update=True,
                    )
                    if payload.engineering_unit != signal.engineering_unit:
                        raise AnalogScalingUnitMismatchError(
                            "analog scaling engineering_unit must match the owning Signal"
                        )
                    latest = session.scalar(
                        select(AnalogScalingProfileRecord)
                        .where(
                            AnalogScalingProfileRecord.organization_id == organization_id,
                            AnalogScalingProfileRecord.signal_id == signal_id,
                        )
                        .order_by(
                            AnalogScalingProfileRecord.effective_from.desc(),
                            AnalogScalingProfileRecord.revision.desc(),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                    effective_from = _as_utc(payload.effective_from)
                    if payload.acquisition_source_id is not None:
                        acquisition_source = session.scalar(
                            select(SignalAcquisitionSourceRecord).where(
                                SignalAcquisitionSourceRecord.id
                                == payload.acquisition_source_id,
                                SignalAcquisitionSourceRecord.organization_id
                                == organization_id,
                                SignalAcquisitionSourceRecord.signal_id == signal_id,
                            )
                        )
                        if acquisition_source is None:
                            raise AcquisitionSourceResolutionError(
                                "analog scaling acquisition_source_id must reference "
                                "the owning Signal's acquisition source"
                            )
                        source_valid_from = _as_utc(acquisition_source.valid_from)
                        source_valid_to = (
                            _as_utc(acquisition_source.valid_to)
                            if acquisition_source.valid_to is not None
                            else None
                        )
                        if not (
                            source_valid_from <= effective_from
                            and (
                                source_valid_to is None
                                or source_valid_to > effective_from
                            )
                        ):
                            raise AcquisitionSourceResolutionError(
                                "analog scaling acquisition source must be effective when the profile begins"
                            )
                    previous = (
                        _analog_scaling_snapshot(latest) if latest is not None else None
                    )
                    self._close_analog_scaling_interval(latest, effective_from)
                    if latest is not None:
                        session.flush()
                    revision = latest.revision + 1 if latest is not None else 1
                    row = AnalogScalingProfileRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        signal_id=signal_id,
                        schema_version=payload.schema_version,
                        electrical_input_class=payload.electrical_input_class,
                        raw_unit=payload.raw_unit,
                        raw_min=payload.raw_min,
                        raw_max=payload.raw_max,
                        engineering_min=payload.engineering_min,
                        engineering_max=payload.engineering_max,
                        engineering_unit=payload.engineering_unit,
                        scaling_policy=payload.scaling_policy,
                        under_range_policy=payload.under_range_policy,
                        over_range_policy=payload.over_range_policy,
                        acquisition_device_family=payload.acquisition_device_family,
                        acquisition_profile_id=payload.acquisition_profile_id,
                        acquisition_profile_version=payload.acquisition_profile_version,
                        acquisition_channel_reference=payload.acquisition_channel_reference,
                        acquisition_source_id=payload.acquisition_source_id,
                        evidence_reference=payload.evidence_reference,
                        calibration_scope=payload.calibration_scope,
                        evidence_status=payload.evidence_status,
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
                        entity_id=signal_id,
                        before=previous,
                        after=_analog_scaling_snapshot(row),
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise HistoryIntegrityConflictError(
                "analog scaling profile append would create an invalid or overlapping interval"
            ) from error

    def resolve_analog_scaling_profile(
        self,
        instrument_id: str,
        signal_id: str,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> AnalogScalingProfileRecord:
        resolved_at = _require_aware_utc(at, "analog scaling resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            signal = self._signal(session, organization_id, instrument_id, signal_id)
            rows = list(
                session.scalars(
                    select(AnalogScalingProfileRecord).where(
                        AnalogScalingProfileRecord.organization_id == organization_id,
                        AnalogScalingProfileRecord.signal_id == signal_id,
                        AnalogScalingProfileRecord.effective_from <= resolved_at,
                        or_(
                            AnalogScalingProfileRecord.effective_to.is_(None),
                            AnalogScalingProfileRecord.effective_to > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise AnalogScalingResolutionError(
                    "analog scaling history must resolve exactly one effective profile"
                )
            row = rows[0]
            _validate_analog_scaling_profile(row, signal)
            session.expunge(row)
            return row

    def evaluate_analog_scaling(
        self,
        instrument_id: str,
        signal_id: str,
        raw_value: Decimal,
        at: datetime,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        expected_acquisition_source_id: str | None = None,
    ) -> tuple[AnalogScalingProfileRecord, Decimal]:
        profile = self.resolve_analog_scaling_profile(
            instrument_id, signal_id, at, organization_id=organization_id
        )
        effective_acquisition_source_id = expected_acquisition_source_id
        if (
            profile.acquisition_source_id is not None
            and effective_acquisition_source_id is None
        ):
            effective_acquisition_source_id = self.resolve_acquisition_source(
                instrument_id,
                signal_id,
                at,
                organization_id=organization_id,
            ).id
        if (
            effective_acquisition_source_id is not None
            and profile.acquisition_source_id != effective_acquisition_source_id
        ):
            raise AnalogScalingSourceMismatchError(
                "analog scaling profile is not explicitly linked to the effective acquisition source"
            )
        value = scale_linear_two_point(
            raw_value,
            raw_min=profile.raw_min,
            raw_max=profile.raw_max,
            engineering_min=profile.engineering_min,
            engineering_max=profile.engineering_max,
        )
        return profile, value

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
        resolved_at = _require_aware_utc(at, "acceptance resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(InstrumentAcceptanceRecord).where(
                        InstrumentAcceptanceRecord.organization_id
                        == organization_id,
                        InstrumentAcceptanceRecord.instrument_id == instrument_id,
                        InstrumentAcceptanceRecord.effective_from <= resolved_at,
                        or_(
                            InstrumentAcceptanceRecord.effective_to.is_(None),
                            InstrumentAcceptanceRecord.effective_to > resolved_at,
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
        resolved_at = _require_aware_utc(at, "calibration resolution timestamp")
        with Session(self._engine, expire_on_commit=False) as session:
            self._instrument(session, organization_id, instrument_id)
            rows = list(
                session.scalars(
                    select(InstrumentCalibrationRecord).where(
                        InstrumentCalibrationRecord.organization_id == organization_id,
                        InstrumentCalibrationRecord.instrument_id == instrument_id,
                        InstrumentCalibrationRecord.calibration_scope
                        == calibration_scope,
                        InstrumentCalibrationRecord.valid_from <= resolved_at,
                        or_(
                            InstrumentCalibrationRecord.valid_to.is_(None),
                            InstrumentCalibrationRecord.valid_to > resolved_at,
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
    def _require_stable_instrument_identity(
        session: Session,
        row: Instrument,
        payload: InstrumentUpdate,
    ) -> None:
        if (
            row.inventory_key != payload.inventory_key
            or row.instrument_kind != payload.instrument_kind
        ):
            raise InstrumentIdentityConflictError(
                "instrument inventory_key and instrument_kind are stable identity fields"
            )
        if payload.pressure_reference != row.pressure_reference:
            has_pressure_signal = session.scalar(
                select(Signal.id)
                .where(
                    Signal.organization_id == row.organization_id,
                    Signal.instrument_id == row.id,
                    Signal.physical_quantity == "pressure",
                )
                .limit(1)
            )
            if has_pressure_signal is not None:
                raise PressureReferenceRequiredError(
                    "pressure_reference cannot change while the instrument owns a pressure signal"
                )
            if row.pressure_reference is not None:
                raise InstrumentIdentityConflictError(
                    "instrument pressure_reference cannot change after it is established"
                )

    @staticmethod
    def _require_stable_signal_identity(row: Signal, payload: SignalUpdate) -> None:
        if (
            row.business_key != payload.business_key
            or row.physical_quantity != payload.physical_quantity
            or row.engineering_unit != payload.engineering_unit
        ):
            raise SignalIdentityConflictError(
                "signal business_key, physical_quantity and engineering_unit are stable identity fields"
            )

    @staticmethod
    def _close_analog_scaling_interval(
        latest: AnalogScalingProfileRecord | None,
        effective_from: datetime,
    ) -> None:
        if latest is None:
            return
        if latest.effective_to is not None:
            raise HistoryIntegrityConflictError(
                "analog scaling history has no single open current interval"
            )
        if effective_from < _as_utc(latest.effective_from):
            raise HistoryOrderConflictError(
                "analog scaling profiles must be appended in non-decreasing effective-time order"
            )
        latest.effective_to = effective_from

    @staticmethod
    def _close_acquisition_source_interval(
        latest: SignalAcquisitionSourceRecord | None,
        valid_from: datetime,
    ) -> None:
        if latest is None:
            return
        if latest.valid_to is not None:
            raise HistoryIntegrityConflictError(
                "acquisition source history has no single open current interval"
            )
        if valid_from < _as_utc(latest.valid_from):
            raise HistoryOrderConflictError(
                "acquisition source bindings must be appended in non-decreasing validity-time order"
            )
        latest.valid_to = valid_from

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


def _require_aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryResolutionError(f"{field_name} must include a timezone offset")
    return value.astimezone(UTC)


def _validate_analog_scaling_profile(
    row: AnalogScalingProfileRecord, signal: Signal
) -> None:
    if (
        row.schema_version != ANALOG_SCALING_SCHEMA_VERSION
        or row.electrical_input_class not in ANALOG_ELECTRICAL_INPUT_CLASSES
        or row.scaling_policy not in ANALOG_SCALING_POLICIES
        or row.under_range_policy not in ANALOG_RANGE_POLICIES
        or row.over_range_policy not in ANALOG_RANGE_POLICIES
        or row.evidence_status not in ANALOG_EVIDENCE_STATUSES
    ):
        raise AnalogScalingResolutionError(
            "analog scaling profile contains unsupported contract semantics"
        )
    if row.engineering_unit != signal.engineering_unit:
        raise AnalogScalingResolutionError(
            "analog scaling profile engineering unit does not match the owning Signal"
        )
    numeric_values = (
        row.raw_min,
        row.raw_max,
        row.engineering_min,
        row.engineering_max,
    )
    if any(not value.is_finite() for value in numeric_values):
        raise AnalogScalingResolutionError(
            "analog scaling profile contains a non-finite numeric value"
        )
    if row.raw_min >= row.raw_max:
        raise AnalogScalingResolutionError(
            "analog scaling profile raw domain is invalid"
        )
    if row.evidence_status == "hardware_verified" and any(
        not value
        for value in (
            row.acquisition_device_family,
            row.acquisition_profile_id,
            row.acquisition_profile_version,
            row.acquisition_channel_reference,
            row.evidence_reference,
        )
    ):
        raise AnalogScalingResolutionError(
            "hardware-verified analog scaling profile lacks complete acquisition provenance"
        )


def _require_pressure_reference(instrument: Instrument, physical_quantity: str) -> None:
    if physical_quantity == "pressure" and instrument.pressure_reference is None:
        raise PressureReferenceRequiredError(
            "pressure signals require an Instrument pressure_reference of absolute or gauge"
        )


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
        "pressure_reference": row.pressure_reference,
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


def _analog_scaling_snapshot(row: AnalogScalingProfileRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "signal_id": row.signal_id,
        "schema_version": row.schema_version,
        "electrical_input_class": row.electrical_input_class,
        "raw_unit": row.raw_unit,
        "raw_min": str(row.raw_min),
        "raw_max": str(row.raw_max),
        "engineering_min": str(row.engineering_min),
        "engineering_max": str(row.engineering_max),
        "engineering_unit": row.engineering_unit,
        "scaling_policy": row.scaling_policy,
        "under_range_policy": row.under_range_policy,
        "over_range_policy": row.over_range_policy,
        "acquisition_device_family": row.acquisition_device_family,
        "acquisition_profile_id": row.acquisition_profile_id,
        "acquisition_profile_version": row.acquisition_profile_version,
        "acquisition_channel_reference": row.acquisition_channel_reference,
        "acquisition_source_id": row.acquisition_source_id,
        "evidence_reference": row.evidence_reference,
        "calibration_scope": row.calibration_scope,
        "evidence_status": row.evidence_status,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "revision": row.revision,
        "recorded_by": row.recorded_by,
        "recorded_at": row.recorded_at.isoformat(),
    }


def _acquisition_source_snapshot(
    row: SignalAcquisitionSourceRecord,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "signal_id": row.signal_id,
        "schema_version": row.schema_version,
        "node_id": row.node_id,
        "equipment_id": row.equipment_id,
        "channel_id": row.channel_id,
        "metric": row.metric,
        "unit": row.unit,
        "evidence_status": row.evidence_status,
        "evidence_reference": row.evidence_reference,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "revision": row.revision,
        "recorded_by": row.recorded_by,
        "recorded_at": row.recorded_at.isoformat(),
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
