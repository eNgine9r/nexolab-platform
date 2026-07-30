from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from app.refrigeration.equipment_repository import (
    DEFAULT_ORGANIZATION_ID,
    EquipmentBindingConflictError,
    EquipmentCodeConflictError,
    EquipmentLifecycleConflictError,
    EquipmentNodeNotFoundError,
    EquipmentNotFoundError,
    EquipmentRepositoryError,
    EquipmentVersionConflictError,
    PostgresRefrigerationEquipmentRepository,
)
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.refrigeration.schemas import (
    ApiErrorDetail,
    ApiErrorResponse,
    RefrigerationEquipmentCreate,
    RefrigerationEquipmentListResponse,
    RefrigerationEquipmentResponse,
    RefrigerationEquipmentUpdate,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


_EQUIPMENT_ETAG_RE = re.compile(r'^(?:W/)?"equipment-v(?P<version>[1-9][0-9]*)"$')


def create_refrigeration_equipment_router(
    repository: PostgresRefrigerationEquipmentRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment", tags=["refrigeration-equipment"])
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

    @router.get("", response_model=RefrigerationEquipmentListResponse)
    def list_equipment(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> RefrigerationEquipmentListResponse:
        return RefrigerationEquipmentListResponse(
            items=[
                equipment_response(item)
                for item in repository.list_active(
                    organization_id=authorized.principal.organization_id
                )
            ]
        )

    @router.post(
        "",
        response_model=RefrigerationEquipmentResponse,
        status_code=status.HTTP_201_CREATED,
        responses={409: {"model": ApiErrorResponse}, 422: {"model": ApiErrorResponse}},
    )
    def create_equipment(
        payload: RefrigerationEquipmentCreate,
        request: Request,
        response: Response,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> RefrigerationEquipmentResponse:
        try:
            item = repository.create(
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.created",
                    entity_type="refrigeration_equipment",
                    entity_id="pending",
                    reason=audit_reason,
                ),
            )
        except EquipmentRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(item.version)
        response.headers["Location"] = f"/api/v1/equipment/{item.id}"
        return equipment_response(item)

    @router.get(
        "/{equipment_id}",
        response_model=RefrigerationEquipmentResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def get_equipment(
        equipment_id: str,
        response: Response,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> RefrigerationEquipmentResponse:
        try:
            item = repository.get_active(
                equipment_id,
                organization_id=authorized.principal.organization_id,
            )
        except EquipmentRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(item.version)
        return equipment_response(item)

    @router.put(
        "/{equipment_id}",
        response_model=RefrigerationEquipmentResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def update_equipment(
        equipment_id: str,
        payload: RefrigerationEquipmentUpdate,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> RefrigerationEquipmentResponse:
        try:
            item = repository.update(
                equipment_id,
                payload,
                expected_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.updated",
                    entity_type="refrigeration_equipment",
                    entity_id=equipment_id,
                    reason=audit_reason,
                ),
            )
        except EquipmentRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(item.version)
        return equipment_response(item)

    @router.delete(
        "/{equipment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def delete_equipment(
        equipment_id: str,
        request: Request,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> Response:
        try:
            deleted = repository.soft_delete(
                equipment_id,
                expected_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.deleted",
                    entity_type="refrigeration_equipment",
                    entity_id=equipment_id,
                    reason=audit_reason,
                ),
            )
        except EquipmentRepositoryError as error:
            raise _repository_http_error(error) from error
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"ETag": equipment_etag(deleted.version)},
        )

    return router


def equipment_response(
    item: RefrigerationEquipmentRecord,
) -> RefrigerationEquipmentResponse:
    return RefrigerationEquipmentResponse(
        id=item.id,
        code=item.code,
        name=item.name,
        location=item.location,
        laboratory=item.laboratory,
        zone=item.zone,
        climate_chamber_id=item.climate_chamber_id,
        node_id=item.node_id,
        equipment_type=item.equipment_type,
        manufacturer=item.manufacturer,
        model=item.model,
        serial_number=item.serial_number,
        temperature_class=item.temperature_class,
        installed_at=item.installed_at,
        serviced_at=item.serviced_at,
        lifecycle_status=item.lifecycle_status,
        status=item.status,
        average_temperature_c=item.average_temperature_c,
        min_temperature_c=item.min_temperature_c,
        max_temperature_c=item.max_temperature_c,
        online_sensors=item.online_sensors,
        total_sensors=item.total_sensors,
        active_alarms=item.active_alarms,
        last_seen_at=item.last_seen_at,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


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


def parse_equipment_if_match(value: str) -> int:
    match = _EQUIPMENT_ETAG_RE.fullmatch(value.strip())
    if match is None:
        raise _api_http_error(
            428,
            "equipment_version_required",
            'If-Match must contain an equipment ETag such as W/"equipment-v3"',
        )
    return int(match.group("version"))


def equipment_etag(version: int) -> str:
    return f'W/"equipment-v{version}"'


def _repository_http_error(error: EquipmentRepositoryError) -> HTTPException:
    if isinstance(error, EquipmentVersionConflictError):
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
            EquipmentCodeConflictError,
            EquipmentLifecycleConflictError,
            EquipmentBindingConflictError,
        ),
    ):
        return _api_http_error(409, error.code, str(error))
    if isinstance(error, EquipmentNodeNotFoundError):
        return _api_http_error(422, error.code, str(error))
    if isinstance(error, EquipmentNotFoundError):
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
