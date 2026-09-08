from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.refrigeration.circuit_models import (
    CALCULATION_POLICY_SCHEMA_VERSION,
    CALIBRATION_VOCABULARY_VERSION,
    RefrigerationCalculationPolicyRecord,
)
from app.refrigeration.derived_thermodynamics import CalculationPolicy
from app.security.repository import AuditEventInput, SecurityRepository


_ACCEPTED_CALIBRATION_STATES = frozenset({"valid", "due"})
_CALIBRATION_SOURCE_ROLES = frozenset(
    {
        "suction_pressure",
        "condensing_pressure",
        "suction_line_temperature",
        "liquid_line_temperature",
        "atmospheric_pressure",
    }
)


class CalculationPolicyRepositoryError(RuntimeError):
    code = "refrigeration_calculation_policy_error"


class CalculationPolicyNotFoundError(CalculationPolicyRepositoryError):
    code = "refrigeration_calculation_policy_unresolved"


class CalculationPolicyConflictError(CalculationPolicyRepositoryError):
    code = "refrigeration_calculation_policy_conflict"


class CalculationPolicyCreateRequest(BaseModel):
    schema_version: str = CALCULATION_POLICY_SCHEMA_VERSION
    version: str = Field(min_length=1, max_length=128)
    maximum_age_ms: int = Field(ge=0)
    maximum_future_clock_skew_ms: int = Field(ge=0)
    maximum_cross_input_skew_ms: int = Field(ge=0)
    calibration_vocabulary_version: str = CALIBRATION_VOCABULARY_VERSION
    accepted_calibration_states: list[str] = Field(min_length=1)
    require_calibration_at_observation: bool
    calibration_required_roles: list[str] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("version is required")
        return normalized

    @model_validator(mode="after")
    def validate_authority(self) -> "CalculationPolicyCreateRequest":
        if self.schema_version != CALCULATION_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported calculation-policy schema_version")
        if self.calibration_vocabulary_version != CALIBRATION_VOCABULARY_VERSION:
            raise ValueError("unsupported calibration vocabulary")
        states = set(self.accepted_calibration_states)
        if not states or not states <= _ACCEPTED_CALIBRATION_STATES:
            raise ValueError(
                "accepted_calibration_states must be a non-empty subset of valid/due"
            )
        if len(states) != len(self.accepted_calibration_states):
            raise ValueError("accepted_calibration_states must not contain duplicates")
        roles = set(self.calibration_required_roles)
        if not roles <= _CALIBRATION_SOURCE_ROLES:
            raise ValueError(
                "calibration_required_roles contains an unsupported source role"
            )
        if len(roles) != len(self.calibration_required_roles):
            raise ValueError("calibration_required_roles must not contain duplicates")
        return self


class CalculationPolicyResponse(BaseModel):
    id: str
    schema_version: str
    version: str
    maximum_age_ms: int
    maximum_future_clock_skew_ms: int
    maximum_cross_input_skew_ms: int
    calibration_vocabulary_version: str
    accepted_calibration_states: list[str]
    require_calibration_at_observation: bool
    calibration_required_roles: list[str]
    created_by: str
    created_at: datetime


class CalculationPolicyListResponse(BaseModel):
    items: list[CalculationPolicyResponse]


class CalculationPolicyRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list(
        self, *, organization_id: str
    ) -> list[RefrigerationCalculationPolicyRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(RefrigerationCalculationPolicyRecord)
                    .where(
                        RefrigerationCalculationPolicyRecord.organization_id
                        == organization_id
                    )
                    .order_by(RefrigerationCalculationPolicyRecord.version.asc())
                )
            )
            session.expunge_all()
            return rows

    def get(
        self, version: str, *, organization_id: str
    ) -> RefrigerationCalculationPolicyRecord:
        normalized = version.strip()
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.scalar(
                select(RefrigerationCalculationPolicyRecord).where(
                    RefrigerationCalculationPolicyRecord.organization_id
                    == organization_id,
                    RefrigerationCalculationPolicyRecord.version == normalized,
                )
            )
            if row is None:
                raise CalculationPolicyNotFoundError(
                    f"calculation policy {normalized!r} is not defined for the organization"
                )
            session.expunge(row)
            return row

    def create(
        self,
        payload: CalculationPolicyCreateRequest,
        *,
        actor_id: str,
        organization_id: str,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationCalculationPolicyRecord:
        row = RefrigerationCalculationPolicyRecord(
            id=str(uuid4()),
            organization_id=organization_id,
            schema_version=payload.schema_version,
            version=payload.version,
            maximum_age_ms=payload.maximum_age_ms,
            maximum_future_clock_skew_ms=payload.maximum_future_clock_skew_ms,
            maximum_cross_input_skew_ms=payload.maximum_cross_input_skew_ms,
            calibration_vocabulary_version=payload.calibration_vocabulary_version,
            accepted_calibration_states=sorted(payload.accepted_calibration_states),
            require_calibration_at_observation=payload.require_calibration_at_observation,
            calibration_required_roles=sorted(payload.calibration_required_roles),
            created_by=_actor(actor_id),
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    session.add(row)
                    session.flush()
                    if audit_repository is not None and audit_event is not None:
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=row.id,
                                before_snapshot=None,
                                after_snapshot=calculation_policy_response(
                                    row
                                ).model_dump(mode="json"),
                            ),
                            session=session,
                        )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise CalculationPolicyConflictError(
                "calculation policy version already exists or violates organization constraints"
            ) from error

    def as_kernel_policy(
        self, version: str, *, organization_id: str
    ) -> CalculationPolicy:
        row = self.get(version, organization_id=organization_id)
        if (
            row.schema_version != CALCULATION_POLICY_SCHEMA_VERSION
            or row.calibration_vocabulary_version != CALIBRATION_VOCABULARY_VERSION
        ):
            raise CalculationPolicyNotFoundError(
                "calculation policy uses an unsupported schema or calibration vocabulary"
            )
        states = frozenset(row.accepted_calibration_states)
        roles = frozenset(row.calibration_required_roles)
        if not states or not states <= _ACCEPTED_CALIBRATION_STATES:
            raise CalculationPolicyNotFoundError(
                "calculation policy contains unsupported calibration states"
            )
        if not roles <= _CALIBRATION_SOURCE_ROLES:
            raise CalculationPolicyNotFoundError(
                "calculation policy contains unsupported calibration roles"
            )
        return CalculationPolicy(
            version=row.version,
            maximum_age=timedelta(milliseconds=row.maximum_age_ms),
            maximum_future_clock_skew=timedelta(
                milliseconds=row.maximum_future_clock_skew_ms
            ),
            maximum_cross_input_skew=timedelta(
                milliseconds=row.maximum_cross_input_skew_ms
            ),
            accepted_calibration_states=states,
            require_calibration_at_observation=row.require_calibration_at_observation,
            calibration_required_roles=roles,
        )


def calculation_policy_response(
    row: RefrigerationCalculationPolicyRecord,
) -> CalculationPolicyResponse:
    return CalculationPolicyResponse(
        id=row.id,
        schema_version=row.schema_version,
        version=row.version,
        maximum_age_ms=row.maximum_age_ms,
        maximum_future_clock_skew_ms=row.maximum_future_clock_skew_ms,
        maximum_cross_input_skew_ms=row.maximum_cross_input_skew_ms,
        calibration_vocabulary_version=row.calibration_vocabulary_version,
        accepted_calibration_states=list(row.accepted_calibration_states),
        require_calibration_at_observation=row.require_calibration_at_observation,
        calibration_required_roles=list(row.calibration_required_roles),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("actor_id is required")
    return normalized
