from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.refrigeration.calculation_policy import (
    CalculationPolicyConflictError,
    CalculationPolicyCreateRequest,
    CalculationPolicyListResponse,
    CalculationPolicyNotFoundError,
    CalculationPolicyRepository,
    CalculationPolicyRepositoryError,
    CalculationPolicyResponse,
    calculation_policy_response,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


def create_calculation_policy_router(
    repository: CalculationPolicyRepository,
    *,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
    default_organization_id: str,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/refrigeration/calculation-policies",
        tags=["refrigeration-calculation-policies"],
    )
    read_access = _access_dependency(
        security_dependencies, Permission.READ_DASHBOARD, default_organization_id
    )
    manage_access = _access_dependency(
        security_dependencies, Permission.MANAGE_EQUIPMENT, default_organization_id
    )

    @router.get("", response_model=CalculationPolicyListResponse)
    def list_policies(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CalculationPolicyListResponse:
        rows = repository.list(organization_id=authorized.principal.organization_id)
        return CalculationPolicyListResponse(
            items=[calculation_policy_response(row) for row in rows]
        )

    @router.get("/{version}", response_model=CalculationPolicyResponse)
    def get_policy(
        version: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> CalculationPolicyResponse:
        try:
            row = repository.get(
                version, organization_id=authorized.principal.organization_id
            )
        except CalculationPolicyRepositoryError as error:
            raise _http_error(error) from error
        return calculation_policy_response(row)

    @router.post(
        "",
        response_model=CalculationPolicyResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_policy(
        payload: CalculationPolicyCreateRequest,
        request: Request,
        audit_reason: str | None = Header(
            default=None, alias="X-Audit-Reason", max_length=1024
        ),
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> CalculationPolicyResponse:
        try:
            row = repository.create(
                payload,
                actor_id=authorized.principal.subject,
                organization_id=authorized.principal.organization_id,
                audit_repository=security_repository,
                audit_event=_audit_event(
                    authorized,
                    request,
                    action="refrigeration.calculation_policy.created",
                    entity_type="refrigeration_calculation_policy",
                    entity_id="pending",
                    reason=audit_reason,
                ),
            )
        except CalculationPolicyRepositoryError as error:
            raise _http_error(error) from error
        return calculation_policy_response(row)

    return router


def _http_error(error: CalculationPolicyRepositoryError) -> HTTPException:
    if isinstance(error, CalculationPolicyNotFoundError):
        status_code = 404
    elif isinstance(error, CalculationPolicyConflictError):
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
