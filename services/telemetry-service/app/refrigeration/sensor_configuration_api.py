from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.refrigeration.api import _draft_response
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
    EquipmentLifecycleRepositoryError,
    EquipmentRetiredError,
    SensorBindingConflictError,
    SensorChannelNotFoundError,
)
from app.refrigeration.models import EquipmentSensorBinding
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.schemas import (
    ApiErrorDetail,
    AvailableSensorListResponse,
    AvailableSensorResponse,
    SensorBindingResponse,
    SensorConfigurationMutationResponse,
    SensorConfigurationWrite,
)
from app.refrigeration.sensor_configuration_repository import (
    ClimateChamberNotFoundError,
    PostgresSensorConfigurationRepository,
    SensorConfigurationCapacityError,
    SensorConfigurationDraftVersionConflictError,
)
from app.refrigeration.storage import ObjectStorage
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_sensor_configuration_router(
    repository: PostgresSensorConfigurationRepository,
    layout_repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    *,
    signed_url_seconds: int,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/equipment",
        tags=["refrigeration-sensor-configuration"],
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

    def list_climate_chamber_channels(
        chamber_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> AvailableSensorListResponse:
        try:
            node_id, channels = repository.list_climate_chamber_channels(
                chamber_id,
                organization_id=authorized.principal.organization_id,
            )
        except EquipmentLifecycleRepositoryError as error:
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
                    bound_equipment_id=(
                        item.binding.equipment_id if item.binding else None
                    ),
                    bound_slot_key=(
                        item.binding.slot_key if item.binding else None
                    ),
                )
                for item in channels
            ],
        )

    router.add_api_route(
        "/options/climate-chambers/{chamber_id}/channels",
        list_climate_chamber_channels,
        methods=["GET"],
        response_model=AvailableSensorListResponse,
    )
    router.add_api_route(
        "/options/nodes/{chamber_id}/channels",
        list_climate_chamber_channels,
        methods=["GET"],
        response_model=AvailableSensorListResponse,
        include_in_schema=False,
    )

    @router.put(
        "/{equipment_id}/sensor-configuration",
        response_model=SensorConfigurationMutationResponse,
    )
    def replace_sensor_configuration(
        equipment_id: str,
        payload: SensorConfigurationWrite,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> SensorConfigurationMutationResponse:
        try:
            result = repository.replace_configuration(
                equipment_id,
                payload,
                expected_equipment_version=parse_equipment_if_match(if_match),
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    reason=audit_reason,
                    equipment_id=equipment_id,
                ),
            )
        except (
            EquipmentLifecycleRepositoryError,
            EquipmentNotFoundError,
            EquipmentVersionConflictError,
        ) as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = equipment_etag(result.equipment.version)
        return SensorConfigurationMutationResponse(
            equipment=equipment_response(result.equipment),
            bindings=[_binding_response(item) for item in result.bindings],
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
    reason: str | None,
    equipment_id: str,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action="equipment.sensor_configuration.updated",
        entity_type="refrigeration_sensor_configuration",
        entity_id=equipment_id,
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
    if isinstance(error, SensorConfigurationDraftVersionConflictError):
        return _api_http_error(
            409,
            error.code,
            str(error),
            expected_version=error.expected_version,
            actual_version=error.actual_version,
        )
    if isinstance(error, (EquipmentNotFoundError, ClimateChamberNotFoundError)):
        return _api_http_error(404, error.code, str(error))
    if isinstance(error, SensorChannelNotFoundError):
        return _api_http_error(422, error.code, str(error))
    if isinstance(
        error,
        (
            EquipmentRetiredError,
            SensorBindingConflictError,
            SensorConfigurationCapacityError,
        ),
    ):
        return _api_http_error(409, error.code, str(error))
    return _api_http_error(
        500,
        "sensor_configuration_repository_error",
        str(error),
    )


def _api_http_error(
    status_code: int,
    code: str,
    message: str,
    *,
    expected_version: int | None = None,
    actual_version: int | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ApiErrorDetail(
            code=code,
            message=message,
            expected_version=expected_version,
            actual_version=actual_version,
        ).model_dump(exclude_none=True),
    )
