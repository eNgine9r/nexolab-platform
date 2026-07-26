from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.nodes.domain import (
    NodeDomainError,
    NodeState,
    NodeStateTransitionError,
    ProvisionNodeCommand,
    RotateNodeCredentialCommand,
)
from app.nodes.repository import (
    NodeConflictError,
    NodeIdempotencyConflictError,
    NodeNotFoundError,
    NodeRepository,
    NodeRepositoryError,
    ProvisionedNode,
    RotatedNodeCredential,
)
from app.nodes.schemas import (
    NodeCredentialRead,
    NodeRead,
    NodeStateChangeRequest,
    ProvisionNodeRequest,
    ProvisionNodeResponse,
    RotateNodeCredentialRequest,
    RotateNodeCredentialResponse,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=128),
]


def create_node_router(
    repository: NodeRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])
    read_access = _access_dependency(security_dependencies, Permission.READ_NODES)
    manage_access = _access_dependency(security_dependencies, Permission.MANAGE_NODES)

    @router.get("", response_model=list[NodeRead])
    def list_nodes(
        state_filter: Annotated[NodeState | None, Query(alias="state")] = None,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[NodeRead]:
        try:
            rows = repository.for_organization(
                authorized.principal.organization_id
            ).list_nodes(state=state_filter)
            return [NodeRead.model_validate(row) for row in rows]
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{node_id}", response_model=NodeRead)
    def get_node(
        node_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> NodeRead:
        try:
            row = repository.for_organization(
                authorized.principal.organization_id
            ).get_node(node_id)
            return NodeRead.model_validate(row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "",
        response_model=ProvisionNodeResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def provision_node(
        payload: ProvisionNodeRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> ProvisionNodeResponse | JSONResponse:
        try:
            stored = repository.for_organization(
                authorized.principal.organization_id
            ).provision(
                ProvisionNodeCommand(
                    node_id=payload.node_id,
                    display_name=payload.display_name,
                    idempotency_key=idempotency_key,
                    actor_subject=authorized.principal.subject,
                    clock_warning_ms=payload.clock_warning_ms,
                    clock_critical_ms=payload.clock_critical_ms,
                ),
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
            )
            response = _provision_response(stored)
            if stored.replayed:
                return JSONResponse(
                    content=response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                    headers={"Idempotent-Replay": "true"},
                )
            return response
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{node_id}/activate", response_model=NodeRead)
    def activate_node(
        node_id: str,
        payload: NodeStateChangeRequest,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> NodeRead:
        try:
            row = repository.for_organization(
                authorized.principal.organization_id
            ).activate(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return NodeRead.model_validate(row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{node_id}/suspend", response_model=NodeRead)
    def suspend_node(
        node_id: str,
        payload: NodeStateChangeRequest,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> NodeRead:
        try:
            row = repository.for_organization(
                authorized.principal.organization_id
            ).suspend(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return NodeRead.model_validate(row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{node_id}/revoke", response_model=NodeRead)
    def revoke_node(
        node_id: str,
        payload: NodeStateChangeRequest,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> NodeRead:
        try:
            row = repository.for_organization(
                authorized.principal.organization_id
            ).revoke(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return NodeRead.model_validate(row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{node_id}/credentials/rotate",
        response_model=RotateNodeCredentialResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def rotate_node_credential(
        node_id: str,
        payload: RotateNodeCredentialRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> RotateNodeCredentialResponse | JSONResponse:
        try:
            stored = repository.for_organization(
                authorized.principal.organization_id
            ).rotate_credential(
                RotateNodeCredentialCommand(
                    node_id=node_id,
                    idempotency_key=idempotency_key,
                    actor_subject=authorized.principal.subject,
                    reason=payload.reason,
                ),
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
            )
            response = _rotation_response(stored)
            if stored.replayed:
                return JSONResponse(
                    content=response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                    headers={"Idempotent-Replay": "true"},
                )
            return response
        except Exception as error:
            raise _http_error(error) from error

    return router


def _provision_response(stored: ProvisionedNode) -> ProvisionNodeResponse:
    return ProvisionNodeResponse(
        node=NodeRead.model_validate(stored.node),
        credential=NodeCredentialRead.model_validate(stored.credential),
        provisioning_secret=stored.secret,
        replayed=stored.replayed,
    )


def _rotation_response(stored: RotatedNodeCredential) -> RotateNodeCredentialResponse:
    return RotateNodeCredentialResponse(
        node=NodeRead.model_validate(stored.node),
        credential=NodeCredentialRead.model_validate(stored.credential),
        provisioning_secret=stored.secret,
        replayed=stored.replayed,
    )


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, NodeNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(
        error,
        (
            NodeConflictError,
            NodeIdempotencyConflictError,
            NodeStateTransitionError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": getattr(error, "code", "node_conflict"), "message": str(error)},
        )
    if isinstance(error, (NodeDomainError, ValueError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": getattr(error, "code", "node_validation_error"), "message": str(error)},
        )
    if isinstance(error, NodeRepositoryError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": str(error)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "node_internal_error",
            "message": "node operation failed",
        },
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
