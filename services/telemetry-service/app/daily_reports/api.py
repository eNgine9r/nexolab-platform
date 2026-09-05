from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.daily_reports.domain import latest_due_report_date
from app.daily_reports.repository import (
    DailyReportGenerationError,
    DailyReportNotFoundError,
    DailyReportProfileConflictError,
    DailyReportProfileNotFoundError,
    DailyReportProfileVersionConflictError,
    DailyReportRepository,
    DailyReportRepositoryError,
)
from app.daily_reports.schemas import (
    DailyReportGenerateRequest,
    DailyReportGenerationResponse,
    DailyReportMiniAppReadRequest,
    DailyReportProfilePage,
    DailyReportProfileRead,
    DailyReportProfileWrite,
    DailyReportSnapshotPage,
    DailyReportSnapshotRead,
    DailyReportSchedulerStatus,
)
from app.daily_reports.service import DailyReportSchedulerService
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies

_ETAG_RE = re.compile(r'^(?:W/)?"daily-report-profile-v(?P<version>[1-9][0-9]*)"$')


def create_daily_report_router(
    repository: DailyReportRepository,
    security_dependencies: SecurityDependencies | None = None,
    *,
    scheduler_service: DailyReportSchedulerService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/daily-reports", tags=["daily-reports"])
    read_access = _access_dependency(security_dependencies, Permission.READ_REPORTS)
    manage_access = _access_dependency(security_dependencies, Permission.MANAGE_EQUIPMENT)
    generate_access = _access_dependency(security_dependencies, Permission.GENERATE_REPORTS)

    @router.post(
        "/profiles",
        response_model=DailyReportProfileRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile(
        payload: DailyReportProfileWrite,
        response: Response,
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> DailyReportProfileRead:
        try:
            profile = repository.for_organization(
                authorized.principal.organization_id
            ).create_profile(
                payload,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=audit_reason,
            )
            response.headers["ETag"] = _profile_etag(profile.version)
            return DailyReportProfileRead.model_validate(profile)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/profiles", response_model=DailyReportProfilePage)
    def list_profiles(
        enabled_only: bool = False,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DailyReportProfilePage:
        try:
            items = repository.for_organization(
                authorized.principal.organization_id
            ).list_profiles(enabled_only=enabled_only)
            return DailyReportProfilePage(
                items=[DailyReportProfileRead.model_validate(item) for item in items],
                count=len(items),
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/profiles/{profile_id}", response_model=DailyReportProfileRead)
    def get_profile(
        profile_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DailyReportProfileRead:
        try:
            profile = repository.for_organization(
                authorized.principal.organization_id
            ).get_profile(profile_id)
            response.headers["ETag"] = _profile_etag(profile.version)
            return DailyReportProfileRead.model_validate(profile)
        except Exception as error:
            raise _http_error(error) from error

    @router.put("/profiles/{profile_id}", response_model=DailyReportProfileRead)
    def update_profile(
        profile_id: str,
        payload: DailyReportProfileWrite,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> DailyReportProfileRead:
        try:
            profile = repository.for_organization(
                authorized.principal.organization_id
            ).update_profile(
                profile_id,
                payload,
                expected_version=_parse_if_match(if_match),
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=audit_reason,
            )
            response.headers["ETag"] = _profile_etag(profile.version)
            return DailyReportProfileRead.model_validate(profile)
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/profiles/{profile_id}/generate",
        response_model=DailyReportGenerationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_report(
        profile_id: str,
        payload: DailyReportGenerateRequest,
        authorized: AuthorizedRequest = Depends(generate_access),
    ) -> DailyReportGenerationResponse | JSONResponse:
        try:
            scoped = repository.for_organization(authorized.principal.organization_id)
            profile = scoped.get_profile(profile_id)
            report_date = payload.local_report_date
            if report_date is None:
                report_date = latest_due_report_date(
                    datetime.now(UTC),
                    timezone=profile.timezone,
                    report_hour=profile.report_hour,
                    report_minute=profile.report_minute,
                    weekdays=profile.weekdays,
                )
            if report_date is None:
                raise DailyReportGenerationError("profile has no due report date")
            result = scoped.generate(
                profile_id,
                local_report_date=report_date,
                generated_by=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            response = DailyReportGenerationResponse(
                **DailyReportSnapshotRead.model_validate(result.snapshot).model_dump(),
                replayed=result.replayed,
            )
            if result.replayed:
                return JSONResponse(
                    content=response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                    headers={"Idempotent-Replay": "true"},
                )
            return response
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/scheduler", response_model=DailyReportSchedulerStatus)
    def scheduler_status(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DailyReportSchedulerStatus:
        scoped = repository.for_organization(authorized.principal.organization_id)
        service = scheduler_service
        return DailyReportSchedulerStatus(
            enabled=service.enabled if service is not None else False,
            running=service.running if service is not None else False,
            last_run_at=service.last_run_at if service is not None else None,
            last_generated_count=(
                service.last_generated_count if service is not None else 0
            ),
            next_scheduled_for=scoped.next_scheduled_for(datetime.now(UTC)),
        )

    @router.get("/snapshots", response_model=DailyReportSnapshotPage)
    def list_snapshots(
        authorized: AuthorizedRequest = Depends(read_access),
        profile_id: Annotated[str | None, Query(max_length=36)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> DailyReportSnapshotPage:
        try:
            page = repository.for_organization(
                authorized.principal.organization_id
            ).list_snapshots(profile_id=profile_id, limit=limit, offset=offset)
            return DailyReportSnapshotPage(
                items=[DailyReportSnapshotRead.model_validate(item) for item in page.items],
                count=page.count,
                limit=page.limit,
                offset=page.offset,
                next_offset=page.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/miniapp/snapshots/{snapshot_id}",
        response_model=DailyReportSnapshotRead,
    )
    def get_miniapp_snapshot(
        snapshot_id: str,
        payload: DailyReportMiniAppReadRequest,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DailyReportSnapshotRead:
        if security_dependencies is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "miniapp_identity_authorization_unavailable",
                    "message": "Mini App identity authorization is unavailable",
                },
            )
        security_dependencies.authorize_identity(
            str(payload.identity_id),
            authorized.principal.organization_id,
            Permission.READ_REPORTS,
        )
        try:
            snapshot = repository.for_organization(
                authorized.principal.organization_id
            ).get_snapshot(snapshot_id)
            return DailyReportSnapshotRead.model_validate(snapshot)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/snapshots/{snapshot_id}", response_model=DailyReportSnapshotRead)
    def get_snapshot(
        snapshot_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DailyReportSnapshotRead:
        try:
            snapshot = repository.for_organization(
                authorized.principal.organization_id
            ).get_snapshot(snapshot_id)
            return DailyReportSnapshotRead.model_validate(snapshot)
        except Exception as error:
            raise _http_error(error) from error

    return router


def _profile_etag(version: int) -> str:
    return f'W/"daily-report-profile-v{version}"'


def _parse_if_match(value: str) -> int:
    match = _ETAG_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(
            'If-Match must contain a profile ETag such as W/"daily-report-profile-v3"'
        )
    return int(match.group("version"))


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, (DailyReportNotFoundError, DailyReportProfileNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(
        error,
        (
            DailyReportProfileConflictError,
            DailyReportProfileVersionConflictError,
            DailyReportGenerationError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, ValueError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "daily_report_validation_error", "message": str(error)},
        )
    if isinstance(error, DailyReportRepositoryError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": str(error)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "daily_report_internal_error", "message": "daily report operation failed"},
    )


def _access_dependency(
    security_dependencies: SecurityDependencies | None,
    permission: Permission,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(permission)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id="00000000-0000-0000-0000-000000000001",
                roles=frozenset({Role.ADMINISTRATOR}),
                provider="disabled",
            ),
        )

    return development_access
