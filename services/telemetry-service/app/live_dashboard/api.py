from __future__ import annotations

import re
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

from app.live_dashboard.inventory import list_live_dashboard_inventory
from app.live_dashboard.repository import (
    DEFAULT_ORGANIZATION_ID,
    DashboardRecord,
    LiveDashboardArchivedError,
    LiveDashboardChannelMetricMismatchError,
    LiveDashboardChannelNotFoundError,
    LiveDashboardNotFoundError,
    LiveDashboardRepository,
    LiveDashboardRepositoryError,
    LiveDashboardUnitConversionUnsupportedError,
    LiveDashboardVersionConflictError,
)
from app.live_dashboard.schemas import (
    ApiErrorDetail,
    ApiErrorResponse,
    LiveDashboardCollectionResponse,
    LiveDashboardInventoryCollectionResponse,
    LiveDashboardInventoryItemResponse,
    LiveDashboardInventoryLatestResponse,
    LiveDashboardItemResponse,
    LiveDashboardResponse,
    LiveDashboardWrite,
    MAX_DASHBOARD_OFFSET,
    MAX_DASHBOARD_PAGE_SIZE,
    MAX_INVENTORY_OFFSET,
    MAX_INVENTORY_PAGE_SIZE,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


_ETAG_RE = re.compile(r'^(?:W/)?"live-dashboard-v(?P<version>[1-9][0-9]*)"$')


def create_live_dashboard_router(
    repository: LiveDashboardRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/live-dashboards",
        tags=["live-dashboards"],
    )
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
        default_organization_id,
    )
    write_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_LIVE_DASHBOARDS,
        default_organization_id,
    )

    @router.get(
        "",
        response_model=LiveDashboardCollectionResponse,
    )
    def list_dashboards(
        include_archived: bool = False,
        limit: int = Query(default=50, ge=1, le=MAX_DASHBOARD_PAGE_SIZE),
        offset: int = Query(default=0, ge=0, le=MAX_DASHBOARD_OFFSET),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> LiveDashboardCollectionResponse:
        page = repository.list(
            organization_id=authorized.principal.organization_id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return LiveDashboardCollectionResponse(
            items=[_response(item) for item in page.items],
            total=page.total,
            limit=limit,
            offset=offset,
            has_more=offset + len(page.items) < page.total,
        )

    @router.get(
        "/channel-inventory",
        response_model=LiveDashboardInventoryCollectionResponse,
        responses={403: {"model": ApiErrorResponse}},
    )
    def list_channel_inventory(
        limit: int = Query(default=MAX_INVENTORY_PAGE_SIZE, ge=1, le=MAX_INVENTORY_PAGE_SIZE),
        offset: int = Query(default=0, ge=0, le=MAX_INVENTORY_OFFSET),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> LiveDashboardInventoryCollectionResponse:
        page = list_live_dashboard_inventory(
            repository,
            organization_id=authorized.principal.organization_id,
            limit=limit,
            offset=offset,
        )
        items: list[LiveDashboardInventoryItemResponse] = []
        for item in page.items:
            latest = None
            if item.latest is not None:
                latest = LiveDashboardInventoryLatestResponse(
                    event_id=item.latest.event_id,
                    node_id=item.node_id,
                    equipment_id=item.equipment_id,
                    channel_id=item.channel_id,
                    captured_at=item.latest.captured_at,
                    metric=item.metric,
                    value=item.latest.value,
                    unit=item.latest.unit,
                    quality=item.latest.quality,
                    source=item.latest.source,
                    alarm=item.latest.alarm,
                    received_at=item.latest.received_at,
                )
            items.append(
                LiveDashboardInventoryItemResponse(
                    channel_ref_id=item.channel_ref_id,
                    node_id=item.node_id,
                    equipment_id=item.equipment_id,
                    equipment_name=item.equipment_name,
                    channel_id=item.channel_id,
                    channel_name=item.channel_name,
                    metric=item.metric,
                    native_unit=item.native_unit,
                    source=item.source,
                    quality=item.quality,
                    alarm=item.alarm,
                    latest=latest,
                )
            )
        return LiveDashboardInventoryCollectionResponse(
            items=items,
            total=page.total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < page.total,
        )

    @router.post(
        "",
        response_model=LiveDashboardResponse,
        status_code=status.HTTP_201_CREATED,
        responses={
            403: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
        },
    )
    def create_dashboard(
        payload: LiveDashboardWrite,
        request: Request,
        response: Response,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(write_access),
    ) -> LiveDashboardResponse:
        try:
            dashboard = repository.create(
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="live_dashboard.created",
                    reason=audit_reason,
                ),
            )
        except LiveDashboardRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _etag(dashboard.version)
        response.headers["Location"] = f"/api/v1/live-dashboards/{dashboard.id}"
        return _response(dashboard)

    @router.get(
        "/{dashboard_id}",
        response_model=LiveDashboardResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_dashboard(
        dashboard_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> LiveDashboardResponse:
        try:
            dashboard = repository.get(
                dashboard_id,
                organization_id=authorized.principal.organization_id,
            )
        except LiveDashboardRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _etag(dashboard.version)
        return _response(dashboard)

    @router.put(
        "/{dashboard_id}",
        response_model=LiveDashboardResponse,
        responses={
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def update_dashboard(
        dashboard_id: str,
        payload: LiveDashboardWrite,
        request: Request,
        response: Response,
        if_match: str | None = Header(default=None, alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(write_access),
    ) -> LiveDashboardResponse:
        expected_version = _parse_if_match(if_match)
        try:
            dashboard = repository.update(
                dashboard_id,
                payload,
                expected_version=expected_version,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="live_dashboard.updated",
                    reason=audit_reason,
                ),
            )
        except LiveDashboardRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = _etag(dashboard.version)
        return _response(dashboard)

    @router.delete(
        "/{dashboard_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses={
            403: {"model": ApiErrorResponse},
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def archive_dashboard(
        dashboard_id: str,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(write_access),
    ) -> Response:
        expected_version = _parse_if_match(if_match)
        try:
            dashboard = repository.archive(
                dashboard_id,
                expected_version=expected_version,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="live_dashboard.archived",
                    reason=audit_reason,
                ),
            )
        except LiveDashboardRepositoryError as error:
            raise _repository_http_error(error) from error
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"ETag": _etag(dashboard.version)},
        )

    return router


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
    reason: str | None,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action=action,
        entity_type="live_dashboard",
        entity_id="pending",
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent"),
    )


def _parse_if_match(value: str | None) -> int:
    if value is None:
        raise _api_http_error(
            428,
            "live_dashboard_version_required",
            'If-Match must contain an ETag such as W/"live-dashboard-v3"',
        )
    match = _ETAG_RE.fullmatch(value.strip())
    if match is None:
        raise _api_http_error(
            428,
            "live_dashboard_version_required",
            'If-Match must contain an ETag such as W/"live-dashboard-v3"',
        )
    return int(match.group("version"))


def _etag(version: int) -> str:
    return f'W/"live-dashboard-v{version}"'


def _repository_http_error(error: LiveDashboardRepositoryError) -> HTTPException:
    if isinstance(error, LiveDashboardVersionConflictError):
        return _api_http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(error, LiveDashboardArchivedError):
        return _api_http_error(409, error.code, str(error))
    if isinstance(error, LiveDashboardNotFoundError):
        return _api_http_error(404, error.code, str(error))
    if isinstance(
        error,
        (
            LiveDashboardChannelNotFoundError,
            LiveDashboardChannelMetricMismatchError,
            LiveDashboardUnitConversionUnsupportedError,
        ),
    ):
        return _api_http_error(422, error.code, str(error))
    return _api_http_error(500, error.code, str(error))


def _api_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    expected_version: int | None = None,
    actual_version: int | None = None,
    issues: list[str] | None = None,
) -> HTTPException:
    detail = ApiErrorDetail(
        code=code,
        message=message,
        expected_version=expected_version,
        actual_version=actual_version,
        issues=issues,
    ).model_dump(exclude_none=True)
    return HTTPException(status_code=status_code, detail=detail)


def _response(record: DashboardRecord) -> LiveDashboardResponse:
    return LiveDashboardResponse(
        id=record.id,
        organization_id=record.organization_id,
        name=record.name,
        description=record.description,
        owner_subject=record.owner_subject,
        refresh_seconds=record.refresh_seconds,
        time_window=record.time_window,
        version=record.version,
        status=record.status,
        created_by=record.created_by,
        updated_by=record.updated_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
        archived_by=record.archived_by,
        archived_at=record.archived_at,
        items=[
            LiveDashboardItemResponse(
                id=item.id,
                position=item.position,
                channel_ref_id=item.channel_ref_id,
                channel_id=item.channel_id,
                metric=item.metric,
                native_unit=item.native_unit,
                visualization=item.visualization,
                color=item.color,
                display_unit=item.display_unit,
            )
            for item in record.items
        ],
    )
