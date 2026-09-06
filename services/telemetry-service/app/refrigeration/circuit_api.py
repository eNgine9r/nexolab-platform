from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.refrigeration.circuit_models import (
    RefrigerationCircuitConfigurationRecord,
    RefrigerationCircuitLifecycleRecord,
)
from app.refrigeration.circuit_repository import (
    CircuitBindingCompatibilityError,
    CircuitBindingNotFoundError,
    CircuitConflictError,
    CircuitDomainError,
    CircuitEquipmentNotFoundError,
    CircuitHistoryOrderError,
    CircuitNotFoundError,
    CircuitResolutionError,
    CircuitSignalNotFoundError,
    RefrigerationCircuitRepository,
    ResolvedCircuitBinding,
)
from app.refrigeration.circuit_schemas import (
    CircuitBindingAppendRequest,
    CircuitBindingEndRequest,
    CircuitBindingListResponse,
    CircuitBindingResponse,
    CircuitConfigurationAppendRequest,
    CircuitConfigurationHistoryResponse,
    CircuitConfigurationResponse,
    CircuitCreateRequest,
    CircuitLifecycleAppendRequest,
    CircuitLifecycleHistoryResponse,
    CircuitLifecycleResponse,
    CircuitListResponse,
    CircuitResponse,
)
from app.refrigeration.equipment_repository import DEFAULT_ORGANIZATION_ID
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_refrigeration_circuit_router(
    repository: RefrigerationCircuitRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/refrigeration/circuits",
        tags=["refrigeration-circuits"],
    )
    read_access = _access_dependency(
        security_dependencies, Permission.READ_DASHBOARD, default_organization_id
    )
    manage_access = _access_dependency(
        security_dependencies, Permission.MANAGE_EQUIPMENT, default_organization_id
    )

    @router.get("", response_model=CircuitListResponse)
    def list_circuits(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitListResponse:
        return CircuitListResponse(
            items=[
                _circuit_response(row)
                for row in repository.list_circuits(
                    organization_id=authorized.principal.organization_id
                )
            ]
        )

    @router.post("", response_model=CircuitResponse, status_code=status.HTTP_201_CREATED)
    def create_circuit(
        payload: CircuitCreateRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CircuitResponse:
        try:
            circuit, _ = repository.create_circuit(
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.circuit.created",
                    entity_type="refrigeration_circuit",
                    entity_id="pending",
                    reason=audit_reason,
                ),
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _circuit_response(circuit)

    @router.get("/{circuit_id}", response_model=CircuitResponse)
    def get_circuit(
        circuit_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitResponse:
        try:
            row = repository.get_circuit(
                circuit_id, organization_id=authorized.principal.organization_id
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _circuit_response(row)

    @router.get(
        "/{circuit_id}/lifecycle-history",
        response_model=CircuitLifecycleHistoryResponse,
    )
    def list_lifecycle_history(
        circuit_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitLifecycleHistoryResponse:
        try:
            rows = repository.list_lifecycle_history(
                circuit_id, organization_id=authorized.principal.organization_id
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return CircuitLifecycleHistoryResponse(items=[_lifecycle_response(row) for row in rows])

    @router.post(
        "/{circuit_id}/lifecycle-history",
        response_model=CircuitLifecycleResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def append_lifecycle(
        circuit_id: str,
        payload: CircuitLifecycleAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CircuitLifecycleResponse:
        try:
            row = repository.append_lifecycle(
                circuit_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.circuit.lifecycle.appended",
                    entity_type="refrigeration_circuit_lifecycle",
                    entity_id=circuit_id,
                    reason=audit_reason,
                ),
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _lifecycle_response(row)

    @router.get(
        "/{circuit_id}/lifecycle-effective",
        response_model=CircuitLifecycleResponse,
    )
    def resolve_lifecycle(
        circuit_id: str,
        at: str = Query(),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitLifecycleResponse:
        try:
            row = repository.resolve_lifecycle(
                circuit_id,
                _parse_datetime(at),
                organization_id=authorized.principal.organization_id,
            )
        except (CircuitDomainError, ValueError) as error:
            raise _http_error(error) from error
        return _lifecycle_response(row)

    @router.get(
        "/{circuit_id}/configuration-history",
        response_model=CircuitConfigurationHistoryResponse,
    )
    def list_configuration_history(
        circuit_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitConfigurationHistoryResponse:
        try:
            rows = repository.list_configuration_history(
                circuit_id, organization_id=authorized.principal.organization_id
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return CircuitConfigurationHistoryResponse(
            items=[_configuration_response(row) for row in rows]
        )

    @router.post(
        "/{circuit_id}/configuration-history",
        response_model=CircuitConfigurationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def append_configuration(
        circuit_id: str,
        payload: CircuitConfigurationAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CircuitConfigurationResponse:
        try:
            row = repository.append_configuration(
                circuit_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.circuit.configuration.appended",
                    entity_type="refrigeration_circuit_configuration",
                    entity_id=circuit_id,
                    reason=audit_reason,
                ),
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _configuration_response(row)

    @router.get(
        "/{circuit_id}/configuration-effective",
        response_model=CircuitConfigurationResponse,
    )
    def resolve_configuration(
        circuit_id: str,
        at: str = Query(),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitConfigurationResponse:
        try:
            row = repository.resolve_configuration(
                circuit_id,
                _parse_datetime(at),
                organization_id=authorized.principal.organization_id,
            )
        except (CircuitDomainError, ValueError) as error:
            raise _http_error(error) from error
        return _configuration_response(row)

    @router.get(
        "/{circuit_id}/bindings",
        response_model=CircuitBindingListResponse,
    )
    def list_bindings(
        circuit_id: str,
        include_history: bool = Query(default=False),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitBindingListResponse:
        try:
            rows = repository.list_bindings(
                circuit_id,
                include_history=include_history,
                organization_id=authorized.principal.organization_id,
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return CircuitBindingListResponse(items=[_binding_response(row) for row in rows])

    @router.post(
        "/{circuit_id}/bindings",
        response_model=CircuitBindingResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def append_binding(
        circuit_id: str,
        payload: CircuitBindingAppendRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CircuitBindingResponse:
        try:
            row = repository.append_binding(
                circuit_id,
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.circuit.binding.appended",
                    entity_type="refrigeration_circuit_signal_binding",
                    entity_id=circuit_id,
                    reason=audit_reason,
                ),
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _binding_response(row)

    @router.post(
        "/{circuit_id}/bindings/{role}/end",
        response_model=CircuitBindingResponse,
    )
    def end_binding(
        circuit_id: str,
        role: str,
        payload: CircuitBindingEndRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CircuitBindingResponse:
        try:
            row = repository.end_binding(
                circuit_id,
                role,
                payload.valid_to,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.circuit.binding.ended",
                    entity_type="refrigeration_circuit_signal_binding",
                    entity_id=circuit_id,
                    reason=audit_reason,
                ),
            )
        except CircuitDomainError as error:
            raise _http_error(error) from error
        return _binding_response(row)

    @router.get(
        "/{circuit_id}/bindings/{role}/effective",
        response_model=CircuitBindingResponse,
    )
    def resolve_binding(
        circuit_id: str,
        role: str,
        at: str = Query(),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CircuitBindingResponse:
        try:
            row = repository.resolve_binding(
                circuit_id,
                role,
                _parse_datetime(at),
                organization_id=authorized.principal.organization_id,
            )
        except (CircuitDomainError, ValueError) as error:
            raise _http_error(error) from error
        return _binding_response(row)

    return router


def _circuit_response(row: object) -> CircuitResponse:
    return CircuitResponse.model_validate(row)


def _lifecycle_response(row: RefrigerationCircuitLifecycleRecord) -> CircuitLifecycleResponse:
    return CircuitLifecycleResponse(
        id=row.id,
        circuit_id=row.circuit_id,
        state=row.state,
        calculation_enabled=row.state == "active",
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        revision=row.revision,
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def _configuration_response(
    row: RefrigerationCircuitConfigurationRecord,
) -> CircuitConfigurationResponse:
    return CircuitConfigurationResponse(
        id=row.id,
        circuit_id=row.circuit_id,
        schema_version="refrigeration-circuit-configuration/v1",
        refrigerant_code=row.refrigerant_code,
        calculation_policy_version=row.calculation_policy_version,
        property_provider_profile=row.property_provider_profile,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        revision=row.revision,
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
    )


def _binding_response(row: ResolvedCircuitBinding) -> CircuitBindingResponse:
    return CircuitBindingResponse(
        id=row.binding.id,
        circuit_id=row.binding.circuit_id,
        signal_id=row.binding.signal_id,
        role=row.binding.role,
        physical_quantity=row.signal.physical_quantity,
        engineering_unit=row.signal.engineering_unit,
        instrument_kind=row.instrument.instrument_kind,
        pressure_reference=row.instrument.pressure_reference,
        valid_from=row.binding.valid_from,
        valid_to=row.binding.valid_to,
        revision=row.binding.revision,
        recorded_by=row.binding.recorded_by,
        recorded_at=row.binding.recorded_at,
        ended_by=row.binding.ended_by,
        ended_at=row.binding.ended_at,
    )


def _parse_datetime(value: str):
    from datetime import datetime

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    resolved = datetime.fromisoformat(normalized)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return resolved


def _http_error(error: Exception) -> HTTPException:
    if isinstance(
        error,
        (
            CircuitNotFoundError,
            CircuitEquipmentNotFoundError,
            CircuitSignalNotFoundError,
            CircuitBindingNotFoundError,
        ),
    ):
        code = error.code
        status_code = 404
    elif isinstance(
        error,
        (
            CircuitConflictError,
            CircuitHistoryOrderError,
            CircuitResolutionError,
            CircuitBindingCompatibilityError,
        ),
    ):
        code = error.code
        status_code = 409
    elif isinstance(error, ValueError):
        code = "refrigeration_circuit_invalid_timestamp"
        status_code = 422
    elif isinstance(error, CircuitDomainError):
        code = error.code
        status_code = 500
    else:
        code = "refrigeration_circuit_error"
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(error)},
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
