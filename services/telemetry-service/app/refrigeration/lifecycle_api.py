from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.refrigeration.api import _draft_response, _image_response
from app.refrigeration.equipment_api import (
    equipment_etag,
    equipment_response,
    parse_equipment_if_match,
)
from app.refrigeration.equipment_repository import (
    DEFAULT_ORGANIZATION_ID,
    EquipmentNotFoundError,
    EquipmentVersionConflictError,
)
from app.refrigeration.lifecycle_repository import (
    EquipmentImageConflictError,
    EquipmentImageNotFoundError,
    EquipmentLifecycleRepositoryError,
    EquipmentNodeRequiredError,
    EquipmentRetiredError,
    PostgresEquipmentLifecycleRepository,
    SensorBindingConflictError,
    SensorBindingNotFoundError,
    SensorChannelNotFoundError,
)
from app.refrigeration.models import EquipmentSensorBinding
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.schemas import (
    ApiErrorDetail,
    ApiErrorResponse,
    AvailableSensorListResponse,
    AvailableSensorResponse,
    EquipmentImageListResponse,
    EquipmentImageResponse,
    EquipmentNodeOptionResponse,
    EquipmentNodeOptionsResponse,
    SensorBindingListResponse,
    SensorBindingMutationResponse,
    SensorBindingResponse,
    SensorBindingWrite,
)
from app.refrigeration.storage import ObjectStorage
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_equipment_lifecycle_router(
    repository: PostgresEquipmentLifecycleRepository,
    layout_repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    *,
    signed_url_seconds: int,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment", tags=["refrigeration-equipment-lifecycle"])
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

    @router.get("/options/nodes", response_model=EquipmentNodeOptionsResponse)
    def list_node_options(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> EquipmentNodeOptionsResponse:
        return EquipmentNodeOptionsResponse(
            items=[
                EquipmentNodeOptionResponse(
                    node_id=node.node_id,
                    display_name=node.display_name,
                    state=node.state,
                    last_seen_at=node.last_seen_at,
                )
                for node in repository.list_node_options(
                    organization_id=authorized.principal.organization_id
                )
            ]
        )

    @router.get(
        "/{equipment_id}/images",
        response_model=EquipmentImageListResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def list_images(
        equipment_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> EquipmentImageListResponse:
        try:
            images = repository.list_images(
                equipment_id,
                organization_id=authorized.principal.organization_id,
            )
        except (EquipmentLifecycleRepositoryError, EquipmentNotFoundError) as error:
            raise _repository_http_error(error) from error
        return EquipmentImageListResponse(
            items=[_image_response(storage, image, signed_url_seconds) for image in images]
        )

    @router.delete(
        "/{equipment_id}/images/{image_id}",
        response_model=EquipmentImageResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def retire_image(
        equipment_id: str,
        image_id: str,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> EquipmentImageResponse:
        try:
            equipment, image = repository.retire_image(
                equipment_id,
                image_id,
                expected_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.image.retired",
                    entity_type="equipment_image",
                    entity_id=image_id,
                    reason=audit_reason,
                ),
            )
        except (
            EquipmentLifecycleRepositoryError,
            EquipmentNotFoundError,
            EquipmentVersionConflictError,
        ) as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(equipment.version)
        return _image_response(storage, image, signed_url_seconds)

    @router.get(
        "/{equipment_id}/sensor-bindings",
        response_model=SensorBindingListResponse,
        responses={404: {"model": ApiErrorResponse}},
    )
    def list_bindings(
        equipment_id: str,
        include_history: bool = Query(default=False),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> SensorBindingListResponse:
        try:
            bindings = repository.list_bindings(
                equipment_id,
                include_history=include_history,
                organization_id=authorized.principal.organization_id,
            )
        except (EquipmentLifecycleRepositoryError, EquipmentNotFoundError) as error:
            raise _repository_http_error(error) from error
        return SensorBindingListResponse(items=[_binding_response(item) for item in bindings])

    @router.get(
        "/{equipment_id}/available-sensors",
        response_model=AvailableSensorListResponse,
        responses={404: {"model": ApiErrorResponse}, 409: {"model": ApiErrorResponse}},
    )
    def list_available_sensors(
        equipment_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> AvailableSensorListResponse:
        try:
            node_id, sensors = repository.list_available_sensors(
                equipment_id,
                organization_id=authorized.principal.organization_id,
            )
        except (EquipmentLifecycleRepositoryError, EquipmentNotFoundError) as error:
            raise _repository_http_error(error) from error
        return AvailableSensorListResponse(
            node_id=node_id,
            items=[
                AvailableSensorResponse(
                    channel_id=item.channel_id,
                    metric=item.metric,
                    unit=item.unit,
                    latest_value=item.latest_value,
                    quality=item.quality,
                    captured_at=item.captured_at,
                    is_bound=item.binding is not None,
                    bound_equipment_id=item.binding.equipment_id if item.binding else None,
                    bound_slot_key=item.binding.slot_key if item.binding else None,
                )
                for item in sensors
            ],
        )

    @router.put(
        "/{equipment_id}/sensor-bindings/{slot_key}",
        response_model=SensorBindingMutationResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            422: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def bind_sensor(
        equipment_id: str,
        slot_key: str,
        payload: SensorBindingWrite,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SensorBindingMutationResponse:
        try:
            result = repository.bind_sensor(
                equipment_id,
                slot_key,
                payload,
                expected_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.sensor.bound",
                    entity_type="refrigeration_sensor_binding",
                    entity_id=f"{equipment_id}:{slot_key}",
                    reason=audit_reason,
                ),
            )
        except (
            EquipmentLifecycleRepositoryError,
            EquipmentNotFoundError,
            EquipmentVersionConflictError,
        ) as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(result.equipment.version)
        return SensorBindingMutationResponse(
            equipment=equipment_response(result.equipment),
            binding=_binding_response(result.binding) if result.binding else None,
            draft=_draft_response(
                layout_repository,
                storage,
                result.draft,
                signed_url_seconds,
            ),
        )

    @router.delete(
        "/{equipment_id}/sensor-bindings/{slot_key}",
        response_model=SensorBindingMutationResponse,
        responses={
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
            428: {"model": ApiErrorResponse},
        },
    )
    def unbind_sensor(
        equipment_id: str,
        slot_key: str,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(default=None, alias="X-Audit-Reason", max_length=1024),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SensorBindingMutationResponse:
        try:
            result = repository.unbind_sensor(
                equipment_id,
                slot_key,
                expected_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="equipment.sensor.unbound",
                    entity_type="refrigeration_sensor_binding",
                    entity_id=f"{equipment_id}:{slot_key}",
                    reason=audit_reason,
                ),
            )
        except (
            EquipmentLifecycleRepositoryError,
            EquipmentNotFoundError,
            EquipmentVersionConflictError,
        ) as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(result.equipment.version)
        return SensorBindingMutationResponse(
            equipment=equipment_response(result.equipment),
            binding=None,
            draft=_draft_response(
                layout_repository,
                storage,
                result.draft,
                signed_url_seconds,
            ),
        )

    return router


def _binding_response(item: EquipmentSensorBinding) -> SensorBindingResponse:
    return SensorBindingResponse(
        id=item.id,
        equipment_id=item.equipment_id,
        node_id=item.node_id,
        channel_id=item.channel_id,
        slot_key=item.slot_key,
        label=item.label,
        side=item.side,
        shelf=item.shelf,
        position=item.position,
        version=item.version,
        bound_by=item.bound_by,
        bound_at=item.bound_at,
        unbound_by=item.unbound_by,
        unbound_at=item.unbound_at,
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


def _repository_http_error(error: Exception) -> HTTPException:
    if isinstance(error, EquipmentVersionConflictError):
        return _api_http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(error, (EquipmentNotFoundError, EquipmentImageNotFoundError, SensorBindingNotFoundError)):
        return _api_http_error(404, error.code, str(error))
    if isinstance(error, SensorChannelNotFoundError):
        return _api_http_error(422, error.code, str(error))
    if isinstance(
        error,
        (
            EquipmentRetiredError,
            EquipmentNodeRequiredError,
            EquipmentImageConflictError,
            SensorBindingConflictError,
        ),
    ):
        return _api_http_error(409, error.code, str(error))
    if isinstance(error, EquipmentLifecycleRepositoryError):
        return _api_http_error(500, error.code, str(error))
    return _api_http_error(500, "equipment_lifecycle_error", str(error))


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
