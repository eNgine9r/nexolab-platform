from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.climate_catalog.repository import (
    ClimateCatalogRepositoryError,
    ClimateChamberEquipmentCatalog,
    ClimateChamberNotFoundError,
    ClimateChamberVersionConflictError,
    PostgresClimateCatalogRepository,
)
from app.climate_catalog.schemas import (
    ClimateChamberEquipmentResponse,
    ClimateChamberListResponse,
    ClimateChamberResponse,
    ClimateChamberUpdateRequest,
    MeasurementChannelResponse,
    MeasurementDeviceResponse,
    PhysicalSensorResponse,
)
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput


_CHAMBER_ETAG_PATTERN = re.compile(r'^W/"climate-chamber-v(?P<version>[1-9][0-9]*)"$')
_KK2_ENERGY_EMPTY_MESSAGE = (
    "До цієї кліматичної камери лічильники електроенергії ще не підключені."
)


def create_climate_catalog_router(
    repository: PostgresClimateCatalogRepository,
    security_dependencies: SecurityDependencies | None = None,
    *,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    root = APIRouter()
    versioned = APIRouter(prefix="/api/v1/climate-chambers", tags=["climate-catalog"])
    compatibility = APIRouter(
        prefix="/api/climate-chambers",
        tags=["climate-catalog"],
        include_in_schema=False,
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

    def list_chambers(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ClimateChamberListResponse:
        rows = repository.list_chambers(
            organization_id=authorized.principal.organization_id
        )
        return ClimateChamberListResponse(
            items=[ClimateChamberResponse.model_validate(item) for item in rows]
        )

    def get_equipment(
        chamber_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ClimateChamberEquipmentResponse:
        try:
            catalog = repository.get_equipment_catalog(
                chamber_id,
                organization_id=authorized.principal.organization_id,
            )
        except ClimateCatalogRepositoryError as error:
            raise _repository_http_error(error) from error
        return _catalog_response(catalog)

    def update_chamber(
        chamber_id: str,
        payload: ClimateChamberUpdateRequest,
        request: Request,
        response: Response,
        if_match: str = Header(alias="If-Match"),
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> ClimateChamberResponse:
        try:
            chamber = repository.update_chamber(
                chamber_id,
                name=payload.name,
                status=payload.status,
                expected_version=parse_climate_chamber_if_match(if_match),
                actor_subject=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_event=AuditEventInput(
                    organization_id=authorized.principal.organization_id,
                    actor_identity_id=authorized.identity_id,
                    actor_subject=authorized.principal.subject,
                    actor_roles=authorized.principal.roles,
                    action="climate_chamber.updated",
                    entity_type="climate_chamber",
                    entity_id=chamber_id,
                    reason=audit_reason,
                    request_id=request.headers.get("X-Request-ID"),
                    source_ip=request.client.host if request.client is not None else None,
                    user_agent=request.headers.get("User-Agent"),
                ),
            )
        except ClimateCatalogRepositoryError as error:
            raise _repository_http_error(error) from error
        response.headers["ETag"] = climate_chamber_etag(chamber.version)
        return ClimateChamberResponse.model_validate(chamber)

    for router in (versioned, compatibility):
        router.add_api_route(
            "",
            list_chambers,
            methods=["GET"],
            response_model=ClimateChamberListResponse,
        )
        router.add_api_route(
            "/{chamber_id}/equipment",
            get_equipment,
            methods=["GET"],
            response_model=ClimateChamberEquipmentResponse,
        )
        router.add_api_route(
            "/{chamber_id}",
            update_chamber,
            methods=["PATCH"],
            response_model=ClimateChamberResponse,
        )

    root.include_router(versioned)
    root.include_router(compatibility)
    return root


def climate_chamber_etag(version: int) -> str:
    if version < 1:
        raise ValueError("climate chamber version must be positive")
    return f'W/"climate-chamber-v{version}"'


def parse_climate_chamber_if_match(value: str) -> int:
    match = _CHAMBER_ETAG_PATTERN.fullmatch(value.strip())
    if match is None:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "climate_chamber_if_match_required",
                "message": "If-Match must contain the current climate chamber ETag",
            },
        )
    return int(match.group("version"))


def _catalog_response(
    catalog: ClimateChamberEquipmentCatalog,
) -> ClimateChamberEquipmentResponse:
    return ClimateChamberEquipmentResponse(
        climate_chamber=ClimateChamberResponse.model_validate(catalog.chamber),
        temperature_controllers=[
            MeasurementDeviceResponse.model_validate(item)
            for item in catalog.temperature_controllers
        ],
        temperature_channels=[
            MeasurementChannelResponse(
                id=item.channel.id,
                channel_id=item.channel.channel_id,
                device_id=item.channel.device_id,
                controller_unit_id=item.device.unit_id,
                channel_number=item.channel.channel_number,
                logical_sensor_number=item.channel.logical_sensor_number,
                display_name=item.channel.display_name,
                physical_sensor_count=item.channel.physical_sensor_count,
                physical_sensors=[
                    PhysicalSensorResponse.model_validate(sensor)
                    for sensor in item.physical_sensors
                ],
                metric_type=item.channel.metric_type,
                unit=item.channel.unit,
                status=item.channel.status,
                created_at=item.channel.created_at,
                updated_at=item.channel.updated_at,
            )
            for item in catalog.temperature_channels
        ],
        energy_meters=[
            MeasurementDeviceResponse.model_validate(item)
            for item in catalog.energy_meters
        ],
        energy_meter_empty_message=(
            _KK2_ENERGY_EMPTY_MESSAGE if not catalog.energy_meters else None
        ),
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


def _repository_http_error(error: ClimateCatalogRepositoryError) -> HTTPException:
    if isinstance(error, ClimateChamberNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, ClimateChamberVersionConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "expected_version": error.expected_version,
                "actual_version": error.actual_version,
            },
        )
    return HTTPException(
        status_code=422,
        detail={"code": error.code, "message": str(error)},
    )
