from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.refrigeration.controller_binding_repository import (
    ControllerBindingConflictError,
    ControllerBindingEquipmentNotFoundError,
    ControllerBindingError,
    ControllerBindingNotFoundError,
    ControllerBindingUnverifiedError,
    PostgresRefrigerationControllerBindingRepository,
)
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.refrigeration.models import RefrigerationControllerBinding
from app.refrigeration.schemas import (
    RefrigerationControllerBindingResponse,
    RefrigerationControllerBindingWrite,
    RefrigerationControllerSummaryListResponse,
    RefrigerationControllerSummaryResponse,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_refrigeration_controller_binding_router(
    repository: PostgresRefrigerationControllerBindingRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment", tags=["refrigeration-controller-binding"])
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

    @router.get(
        "/controller-summaries",
        response_model=RefrigerationControllerSummaryListResponse,
    )
    def list_controller_summaries(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> RefrigerationControllerSummaryListResponse:
        rows = repository.list_summaries(
            organization_id=authorized.principal.organization_id,
        )
        return RefrigerationControllerSummaryListResponse(
            items=[
                RefrigerationControllerSummaryResponse(
                    equipment_id=row.binding.equipment_id,
                    controller_family="embraco",
                    controller_equipment_id=row.binding.controller_equipment_id,
                    unit_id=row.binding.unit_id,
                    profile_version=row.binding.profile_version,
                    control_state=row.control_state,
                    compressor_speed_rpm=row.compressor_speed_rpm,
                    last_seen_at=row.last_seen_at,
                )
                for row in rows
            ]
        )

    @router.get(
        "/{equipment_id}/controller-binding",
        response_model=RefrigerationControllerBindingResponse,
    )
    def get_controller_binding(
        equipment_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> RefrigerationControllerBindingResponse:
        try:
            binding = repository.get_active(
                equipment_id,
                organization_id=authorized.principal.organization_id,
            )
        except ControllerBindingError as error:
            raise _http_error(error) from error
        return _response(binding)

    @router.put(
        "/{equipment_id}/controller-binding",
        response_model=RefrigerationControllerBindingResponse,
    )
    def put_controller_binding(
        equipment_id: str,
        payload: RefrigerationControllerBindingWrite,
        request: Request,
        audit_reason: str | None = Header(
            default=None,
            alias="X-Audit-Reason",
            max_length=1024,
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> RefrigerationControllerBindingResponse:
        try:
            binding = repository.replace_active(
                equipment_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    entity_id=equipment_id,
                    reason=audit_reason,
                ),
            )
        except ControllerBindingError as error:
            raise _http_error(error) from error
        return _response(binding)

    return router


def _response(binding: RefrigerationControllerBinding) -> RefrigerationControllerBindingResponse:
    return RefrigerationControllerBindingResponse(
        id=binding.id,
        equipment_id=binding.equipment_id,
        node_id=binding.node_id,
        controller_family="embraco",
        controller_equipment_id=binding.controller_equipment_id,
        unit_id=binding.unit_id,
        profile_version=binding.profile_version,
        bound_at=binding.bound_at,
        verified_from_telemetry=True,
    )


def _http_error(error: ControllerBindingError) -> HTTPException:
    if isinstance(error, ControllerBindingNotFoundError):
        status_code = 404
    elif isinstance(error, ControllerBindingUnverifiedError):
        status_code = 422
    elif isinstance(error, ControllerBindingEquipmentNotFoundError):
        status_code = 404
    elif isinstance(error, ControllerBindingConflictError):
        status_code = 409
    else:
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": str(error)},
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
    entity_id: str,
    reason: str | None,
) -> AuditEventInput:
    return AuditEventInput(
        organization_id=authorized.principal.organization_id,
        actor_identity_id=authorized.identity_id,
        actor_subject=authorized.principal.subject,
        actor_roles=authorized.principal.roles,
        action="equipment.controller_binding.updated",
        entity_type="refrigeration_controller_binding",
        entity_id=entity_id,
        reason=reason,
        request_id=request.headers.get("X-Request-ID"),
        source_ip=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("User-Agent"),
    )
