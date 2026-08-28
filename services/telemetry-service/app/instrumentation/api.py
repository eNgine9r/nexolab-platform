from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Callable

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.instrumentation.models import (
    Instrument,
    InstrumentAcceptanceRecord,
    InstrumentCalibrationRecord,
    Signal,
)
from app.instrumentation.repository import (
    DEFAULT_ORGANIZATION_ID,
    HistoryIntegrityConflictError,
    HistoryOrderConflictError,
    InstrumentationRepository,
    InstrumentationRepositoryError,
    InstrumentKeyConflictError,
    InstrumentNotFoundError,
    InstrumentVersionConflictError,
    SignalKeyConflictError,
    SignalNotFoundError,
    SignalVersionConflictError,
)
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    AcceptanceHistoryResponse,
    AcceptanceRecordResponse,
    ApiErrorDetail,
    ApiErrorResponse,
    CalibrationAppendRequest,
    CalibrationHistoryResponse,
    CalibrationRecordResponse,
    InstrumentCreate,
    InstrumentListResponse,
    InstrumentResponse,
    InstrumentUpdate,
    SignalCreate,
    SignalListResponse,
    SignalResponse,
    SignalUpdate,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


_INSTRUMENT_ETAG_RE = re.compile(
    r'^(?:W/)?"instrument-v(?P<version>[1-9][0-9]*)"$'
)
_SIGNAL_ETAG_RE = re.compile(r'^(?:W/)?"signal-v(?P<version>[1-9][0-9]*)"$')
_CANONICAL_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")


def create_instrumentation_router(
    repository: InstrumentationRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/instrumentation",
        tags=["instrumentation-registry"],
    )
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
        default_organization_id,
    )
    manage_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_EQUIPMENT,
        default_organization_id,
    )

    @router.get("/instruments", response_model=InstrumentListResponse)
    def list_instruments(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> InstrumentListResponse:
        return InstrumentListResponse(
            items=[
                _instrument_response(row)
                for row in repository.list_instruments(
                    organization_id=authorized.principal.organization_id
                )
            ]
        )

    @router.post(
        "/instruments",
        response_model=InstrumentResponse,
        status_code=status.HTTP_201_CREATED,
        responses={409: {"model": ApiErrorResponse}},
    )
    def create_instrument(
        payload: InstrumentCreate,
        request: Request,
        response: Response,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> InstrumentResponse:
        try:
            row = repository.create_instrument(
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument.created",
                    entity_type="instrument",
                    entity_id="pending",
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = instrument_etag(row.version)
        response.headers["Location"] = (
            f"/api/v1/instrumentation/instruments/{row.id}"
        )
        return _instrument_response(row)

    @router.get(
        "/instruments/{instrument_id}",
        response_model=InstrumentResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_instrument(
        instrument_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> InstrumentResponse:
        try:
            row = repository.get_instrument(
                instrument_id,
                organization_id=authorized.principal.organization_id,
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = instrument_etag(row.version)
        return _instrument_response(row)

    @router.put(
        "/instruments/{instrument_id}",
        response_model=InstrumentResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def update_instrument(
        instrument_id: str,
        payload: InstrumentUpdate,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> InstrumentResponse:
        try:
            row = repository.update_instrument(
                instrument_id,
                payload,
                expected_version=parse_instrument_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument.updated",
                    entity_type="instrument",
                    entity_id=instrument_id,
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = instrument_etag(row.version)
        return _instrument_response(row)

    @router.get(
        "/instruments/{instrument_id}/signals",
        response_model=SignalListResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def list_signals(
        instrument_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> SignalListResponse:
        try:
            rows = repository.list_signals(
                instrument_id,
                organization_id=authorized.principal.organization_id,
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        return SignalListResponse(items=[_signal_response(row) for row in rows])

    @router.post(
        "/instruments/{instrument_id}/signals",
        response_model=SignalResponse,
        status_code=status.HTTP_201_CREATED,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def create_signal(
        instrument_id: str,
        payload: SignalCreate,
        request: Request,
        response: Response,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SignalResponse:
        try:
            row = repository.create_signal(
                instrument_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument_signal.created",
                    entity_type="instrument_signal",
                    entity_id="pending",
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = signal_etag(row.version)
        response.headers["Location"] = (
            f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{row.id}"
        )
        return _signal_response(row)

    @router.get(
        "/instruments/{instrument_id}/signals/{signal_id}",
        response_model=SignalResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_signal(
        instrument_id: str,
        signal_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> SignalResponse:
        try:
            row = repository.get_signal(
                instrument_id,
                signal_id,
                organization_id=authorized.principal.organization_id,
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = signal_etag(row.version)
        return _signal_response(row)

    @router.put(
        "/instruments/{instrument_id}/signals/{signal_id}",
        response_model=SignalResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def update_signal(
        instrument_id: str,
        signal_id: str,
        payload: SignalUpdate,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SignalResponse:
        try:
            row = repository.update_signal(
                instrument_id,
                signal_id,
                payload,
                expected_version=parse_signal_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument_signal.updated",
                    entity_type="instrument_signal",
                    entity_id=signal_id,
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = signal_etag(row.version)
        return _signal_response(row)

    @router.get(
        "/instruments/{instrument_id}/acceptance-history",
        response_model=AcceptanceHistoryResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def list_acceptance_history(
        instrument_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> AcceptanceHistoryResponse:
        try:
            rows = repository.list_acceptance_history(
                instrument_id,
                organization_id=authorized.principal.organization_id,
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        return AcceptanceHistoryResponse(
            items=[_acceptance_response(row) for row in rows]
        )

    @router.post(
        "/instruments/{instrument_id}/acceptance-history",
        response_model=AcceptanceRecordResponse,
        status_code=status.HTTP_201_CREATED,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def append_acceptance(
        instrument_id: str,
        payload: AcceptanceAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> AcceptanceRecordResponse:
        try:
            row = repository.append_acceptance(
                instrument_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument.acceptance_appended",
                    entity_type="instrument_acceptance",
                    entity_id=instrument_id,
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        return _acceptance_response(row)

    @router.get(
        "/instruments/{instrument_id}/calibration-history",
        response_model=CalibrationHistoryResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def list_calibration_history(
        instrument_id: str,
        calibration_scope: str | None = Query(default=None, max_length=64),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CalibrationHistoryResponse:
        if calibration_scope is not None and not _CANONICAL_IDENTIFIER_RE.fullmatch(
            calibration_scope
        ):
            raise _api_http_error(
                422,
                "calibration_scope_invalid",
                "calibration_scope must be a lowercase canonical identifier",
            )
        try:
            rows = repository.list_calibration_history(
                instrument_id,
                calibration_scope=calibration_scope,
                organization_id=authorized.principal.organization_id,
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        return CalibrationHistoryResponse(
            items=[_calibration_response(row) for row in rows]
        )

    @router.post(
        "/instruments/{instrument_id}/calibration-history",
        response_model=CalibrationRecordResponse,
        status_code=status.HTTP_201_CREATED,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def append_calibration(
        instrument_id: str,
        payload: CalibrationAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CalibrationRecordResponse:
        try:
            row = repository.append_calibration(
                instrument_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="instrument.calibration_appended",
                    entity_type="instrument_calibration",
                    entity_id=instrument_id,
                    reason=audit_reason,
                ),
            )
        except InstrumentationRepositoryError as error:
            raise _repository_http_error(error) from error
        return _calibration_response(row)

    return router


def instrument_etag(version: int) -> str:
    return f'W/"instrument-v{version}"'


def signal_etag(version: int) -> str:
    return f'W/"signal-v{version}"'


def parse_instrument_if_match(value: str) -> int:
    return _parse_if_match(
        value,
        _INSTRUMENT_ETAG_RE,
        code="instrument_version_required",
        example='W/"instrument-v3"',
    )


def parse_signal_if_match(value: str) -> int:
    return _parse_if_match(
        value,
        _SIGNAL_ETAG_RE,
        code="signal_version_required",
        example='W/"signal-v3"',
    )


def _parse_if_match(value: str, pattern: re.Pattern[str], *, code: str, example: str) -> int:
    match = pattern.fullmatch(value.strip())
    if match is None:
        raise _api_http_error(
            428,
            code,
            f"If-Match must contain an ETag such as {example}",
        )
    return int(match.group("version"))


def _instrument_response(row: Instrument) -> InstrumentResponse:
    return InstrumentResponse(
        id=row.id,
        inventory_key=row.inventory_key,
        display_name=row.display_name,
        instrument_kind=row.instrument_kind,
        manufacturer=row.manufacturer,
        model=row.model,
        serial_number=row.serial_number,
        lifecycle_state=row.lifecycle_state,
        metadata=dict(row.attributes),
        version=row.version,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
    )


def _signal_response(row: Signal) -> SignalResponse:
    return SignalResponse(
        id=row.id,
        instrument_id=row.instrument_id,
        business_key=row.business_key,
        display_name=row.display_name,
        physical_quantity=row.physical_quantity,
        engineering_unit=row.engineering_unit,
        lifecycle_state=row.lifecycle_state,
        metadata=dict(row.attributes),
        version=row.version,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
    )


def _acceptance_response(
    row: InstrumentAcceptanceRecord,
) -> AcceptanceRecordResponse:
    return AcceptanceRecordResponse(
        id=row.id,
        instrument_id=row.instrument_id,
        schema_version=row.schema_version,
        accepted_for_calculation=row.accepted_for_calculation,
        state_label=row.state_label,
        effective_from=_utc_datetime(row.effective_from),
        effective_to=(
            _utc_datetime(row.effective_to) if row.effective_to is not None else None
        ),
        revision=row.revision,
        recorded_by=row.recorded_by,
        recorded_at=_utc_datetime(row.recorded_at),
    )


def _calibration_response(
    row: InstrumentCalibrationRecord,
) -> CalibrationRecordResponse:
    return CalibrationRecordResponse(
        id=row.id,
        instrument_id=row.instrument_id,
        calibration_scope=row.calibration_scope,
        schema_version=row.schema_version,
        state=row.state,
        valid_from=_utc_datetime(row.valid_from),
        valid_to=_utc_datetime(row.valid_to) if row.valid_to is not None else None,
        revision=row.revision,
        certificate_reference=row.certificate_reference,
        recorded_by=row.recorded_by,
        recorded_at=_utc_datetime(row.recorded_at),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _access_dependency(
    security_dependencies: SecurityDependencies | None,
    permission: Permission,
    default_organization_id: str,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(permission)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id=default_organization_id,
                roles=frozenset({Role.ADMINISTRATOR}),
                display_name="Development system",
                provider="disabled",
            ),
        )

    return development_access


def _audit_event(
    authorized: AuthorizedRequest,
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    reason: str | None,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent"),
    )


def _repository_http_error(error: InstrumentationRepositoryError) -> HTTPException:
    if isinstance(error, (InstrumentVersionConflictError, SignalVersionConflictError)):
        return _api_http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(
        error,
        (
            InstrumentKeyConflictError,
            SignalKeyConflictError,
            HistoryOrderConflictError,
            HistoryIntegrityConflictError,
        ),
    ):
        return _api_http_error(409, error.code, str(error))
    if isinstance(error, (InstrumentNotFoundError, SignalNotFoundError)):
        return _api_http_error(404, error.code, str(error))
    return _api_http_error(500, error.code, str(error))


def _api_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    expected_version: int | None = None,
    actual_version: int | None = None,
) -> HTTPException:
    detail = ApiErrorDetail(
        code=code,
        message=message,
        expected_version=expected_version,
        actual_version=actual_version,
    ).model_dump(exclude_none=True)
    return HTTPException(status_code=status_code, detail=detail)
