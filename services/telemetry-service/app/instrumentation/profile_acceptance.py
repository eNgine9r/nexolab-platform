from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import (
    ACCEPTANCE_SCHEMA_VERSION,
    AcquisitionProfileAcceptanceRecord,
    AnalogScalingProfileRecord,
    Instrument,
    Signal,
    SignalAcquisitionSourceRecord,
)
from app.security.repository import AuditEventInput, SecurityRepository


class AcquisitionProfileAcceptanceError(RuntimeError):
    code = "acquisition_profile_acceptance_error"


class AcquisitionProfileNotFoundError(AcquisitionProfileAcceptanceError):
    code = "acquisition_profile_not_found"


class AcquisitionProfileIdentityUnavailableError(AcquisitionProfileAcceptanceError):
    code = "acquisition_profile_identity_unavailable"


class AcquisitionProfileAcceptanceOrderError(AcquisitionProfileAcceptanceError):
    code = "acquisition_profile_acceptance_order_conflict"


class AcquisitionProfileAcceptanceIntegrityError(AcquisitionProfileAcceptanceError):
    code = "acquisition_profile_acceptance_integrity_conflict"


class AcquisitionProfileAcceptanceResolutionError(AcquisitionProfileAcceptanceError):
    code = "acquisition_profile_acceptance_unavailable"


class ProfileAcceptanceAppendRequest(BaseModel):
    scaling_profile_id: str | None = Field(default=None, max_length=36)
    accepted_for_calculation: bool
    state_label: str | None = Field(default=None, max_length=64)
    effective_from: AwareDatetime

    @field_validator("scaling_profile_id", "state_label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProfileAcceptanceResponse(BaseModel):
    id: str
    signal_id: str
    acquisition_source_id: str
    scaling_profile_id: str | None
    profile_target_key: str
    schema_version: str
    acquisition_profile_id: str
    acquisition_profile_version: str
    accepted_for_calculation: bool
    state_label: str | None
    effective_from: datetime
    effective_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class ProfileAcceptanceHistoryResponse(BaseModel):
    items: list[ProfileAcceptanceResponse]


@dataclass(frozen=True, slots=True)
class AcquisitionProfileTarget:
    source: SignalAcquisitionSourceRecord
    scaling_profile: AnalogScalingProfileRecord | None
    target_key: str
    profile_id: str
    profile_version: str


class AcquisitionProfileAcceptanceRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_history(
        self,
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        *,
        scaling_profile_id: str | None = None,
        organization_id: str,
    ) -> list[AcquisitionProfileAcceptanceRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            target = self._target(
                session,
                organization_id,
                instrument_id,
                signal_id,
                acquisition_source_id,
                scaling_profile_id,
            )
            rows = list(
                session.scalars(
                    select(AcquisitionProfileAcceptanceRecord)
                    .where(
                        AcquisitionProfileAcceptanceRecord.organization_id
                        == organization_id,
                        AcquisitionProfileAcceptanceRecord.signal_id == signal_id,
                        AcquisitionProfileAcceptanceRecord.profile_target_key
                        == target.target_key,
                    )
                    .order_by(
                        AcquisitionProfileAcceptanceRecord.effective_from.asc(),
                        AcquisitionProfileAcceptanceRecord.revision.asc(),
                    )
                )
            )
            session.expunge_all()
            return rows

    def append(
        self,
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        payload: ProfileAcceptanceAppendRequest,
        *,
        actor_id: str,
        organization_id: str,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> AcquisitionProfileAcceptanceRecord:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    target = self._target(
                        session,
                        organization_id,
                        instrument_id,
                        signal_id,
                        acquisition_source_id,
                        payload.scaling_profile_id,
                        for_update=True,
                    )
                    latest = session.scalar(
                        select(AcquisitionProfileAcceptanceRecord)
                        .where(
                            AcquisitionProfileAcceptanceRecord.organization_id
                            == organization_id,
                            AcquisitionProfileAcceptanceRecord.signal_id == signal_id,
                            AcquisitionProfileAcceptanceRecord.profile_target_key
                            == target.target_key,
                        )
                        .order_by(
                            AcquisitionProfileAcceptanceRecord.effective_from.desc(),
                            AcquisitionProfileAcceptanceRecord.revision.desc(),
                        )
                        .limit(1)
                        .with_for_update()
                    )
                    effective_from = _as_utc(payload.effective_from)
                    previous = _snapshot(latest) if latest is not None else None
                    self._close_interval(latest, effective_from)
                    if latest is not None:
                        session.flush()
                    row = AcquisitionProfileAcceptanceRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        signal_id=signal_id,
                        acquisition_source_id=target.source.id,
                        scaling_profile_id=(
                            target.scaling_profile.id
                            if target.scaling_profile is not None
                            else None
                        ),
                        profile_target_key=target.target_key,
                        schema_version=ACCEPTANCE_SCHEMA_VERSION,
                        acquisition_profile_id=target.profile_id,
                        acquisition_profile_version=target.profile_version,
                        accepted_for_calculation=payload.accepted_for_calculation,
                        state_label=payload.state_label,
                        effective_from=effective_from,
                        effective_to=None,
                        revision=latest.revision + 1 if latest is not None else 1,
                        recorded_by=_actor(actor_id),
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    if audit_repository is not None and audit_event is not None:
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=target.target_key,
                                before_snapshot=previous,
                                after_snapshot=_snapshot(row),
                            ),
                            session=session,
                        )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise AcquisitionProfileAcceptanceIntegrityError(
                "acquisition profile acceptance append would create invalid history"
            ) from error

    def resolve(
        self,
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        at: datetime,
        *,
        scaling_profile_id: str | None = None,
        organization_id: str,
    ) -> AcquisitionProfileAcceptanceRecord:
        resolved_at = _require_aware(at)
        with Session(self._engine, expire_on_commit=False) as session:
            target = self._target(
                session,
                organization_id,
                instrument_id,
                signal_id,
                acquisition_source_id,
                scaling_profile_id,
            )
            rows = list(
                session.scalars(
                    select(AcquisitionProfileAcceptanceRecord).where(
                        AcquisitionProfileAcceptanceRecord.organization_id
                        == organization_id,
                        AcquisitionProfileAcceptanceRecord.signal_id == signal_id,
                        AcquisitionProfileAcceptanceRecord.profile_target_key
                        == target.target_key,
                        AcquisitionProfileAcceptanceRecord.effective_from
                        <= resolved_at,
                        or_(
                            AcquisitionProfileAcceptanceRecord.effective_to.is_(None),
                            AcquisitionProfileAcceptanceRecord.effective_to
                            > resolved_at,
                        ),
                    )
                )
            )
            if len(rows) != 1:
                raise AcquisitionProfileAcceptanceResolutionError(
                    "acquisition profile acceptance must resolve exactly one state"
                )
            row = rows[0]
            if (
                row.schema_version != ACCEPTANCE_SCHEMA_VERSION
                or row.acquisition_source_id != target.source.id
                or row.scaling_profile_id
                != (
                    target.scaling_profile.id
                    if target.scaling_profile is not None
                    else None
                )
                or row.acquisition_profile_id != target.profile_id
                or row.acquisition_profile_version != target.profile_version
                or not isinstance(row.accepted_for_calculation, bool)
            ):
                raise AcquisitionProfileAcceptanceResolutionError(
                    "acquisition profile acceptance contains unsupported authority"
                )
            session.expunge(row)
            return row

    @staticmethod
    def _target(
        session: Session,
        organization_id: str,
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        scaling_profile_id: str | None,
        *,
        for_update: bool = False,
    ) -> AcquisitionProfileTarget:
        instrument = session.scalar(
            select(Instrument).where(
                Instrument.organization_id == organization_id,
                Instrument.id == instrument_id,
            )
        )
        signal = session.scalar(
            select(Signal).where(
                Signal.organization_id == organization_id,
                Signal.instrument_id == instrument_id,
                Signal.id == signal_id,
            )
        )
        if instrument is None or signal is None:
            raise AcquisitionProfileNotFoundError(
                "instrument or Signal for acquisition profile was not found"
            )
        source_statement = select(SignalAcquisitionSourceRecord).where(
            SignalAcquisitionSourceRecord.organization_id == organization_id,
            SignalAcquisitionSourceRecord.signal_id == signal_id,
            SignalAcquisitionSourceRecord.id == acquisition_source_id,
        )
        if for_update:
            source_statement = source_statement.with_for_update()
        source = session.scalar(source_statement)
        if source is None:
            raise AcquisitionProfileNotFoundError(
                "acquisition source for profile acceptance was not found"
            )
        profile_id = _optional(source.acquisition_profile_id)
        profile_version = _optional(source.acquisition_profile_version)
        if profile_id is None or profile_version is None:
            raise AcquisitionProfileIdentityUnavailableError(
                "acquisition source has no explicit profile id/version"
            )
        scaling: AnalogScalingProfileRecord | None = None
        if scaling_profile_id is not None:
            scaling_statement = select(AnalogScalingProfileRecord).where(
                AnalogScalingProfileRecord.organization_id == organization_id,
                AnalogScalingProfileRecord.signal_id == signal_id,
                AnalogScalingProfileRecord.id == scaling_profile_id,
            )
            if for_update:
                scaling_statement = scaling_statement.with_for_update()
            scaling = session.scalar(scaling_statement)
            if scaling is None:
                raise AcquisitionProfileNotFoundError(
                    "analog scaling profile for acquisition acceptance was not found"
                )
            if (
                scaling.acquisition_source_id != source.id
                or _optional(scaling.acquisition_profile_id) != profile_id
                or _optional(scaling.acquisition_profile_version) != profile_version
            ):
                raise AcquisitionProfileIdentityUnavailableError(
                    "analog scaling profile identity does not match acquisition source profile identity"
                )
        target_key = f"source:{source.id}"
        if scaling is not None:
            target_key += f"/scaling:{scaling.id}"
        return AcquisitionProfileTarget(
            source=source,
            scaling_profile=scaling,
            target_key=target_key,
            profile_id=profile_id,
            profile_version=profile_version,
        )

    @staticmethod
    def _close_interval(
        latest: AcquisitionProfileAcceptanceRecord | None,
        effective_from: datetime,
    ) -> None:
        if latest is None:
            return
        latest_from = _as_utc(latest.effective_from)
        if effective_from < latest_from:
            raise AcquisitionProfileAcceptanceOrderError(
                "acquisition profile acceptance must be appended in non-decreasing effective-time order"
            )
        if latest.effective_to is not None:
            raise AcquisitionProfileAcceptanceIntegrityError(
                "acquisition profile acceptance history has no single open current interval"
            )
        latest.effective_to = effective_from


def profile_acceptance_response(
    row: AcquisitionProfileAcceptanceRecord,
) -> ProfileAcceptanceResponse:
    return ProfileAcceptanceResponse(
        id=row.id,
        signal_id=row.signal_id,
        acquisition_source_id=row.acquisition_source_id,
        scaling_profile_id=row.scaling_profile_id,
        profile_target_key=row.profile_target_key,
        schema_version=row.schema_version,
        acquisition_profile_id=row.acquisition_profile_id,
        acquisition_profile_version=row.acquisition_profile_version,
        accepted_for_calculation=row.accepted_for_calculation,
        state_label=row.state_label,
        effective_from=_as_utc(row.effective_from),
        effective_to=_as_utc(row.effective_to)
        if row.effective_to is not None
        else None,
        revision=row.revision,
        recorded_by=row.recorded_by,
        recorded_at=_as_utc(row.recorded_at),
    )


def _snapshot(row: AcquisitionProfileAcceptanceRecord) -> dict[str, object]:
    return profile_acceptance_response(row).model_dump(mode="json")


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("actor_id is required")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AcquisitionProfileAcceptanceResolutionError(
            "acquisition profile acceptance timestamp must include timezone offset"
        )
    return value.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
