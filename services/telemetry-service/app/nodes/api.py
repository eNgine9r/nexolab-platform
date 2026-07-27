from __future__ import annotations

from datetime import UTC, datetime
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
from app.nodes.models import CentralNode
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
from app.nodes.stream_repository import NodeStreamRepository
from app.nodes.stream_schemas import (
    NodeHealthRead,
    NodeOperationalStateRead,
    NodeStatusRead,
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
    *,
    health_stale_after_seconds: int = 90,
) -> APIRouter:
    if health_stale_after_seconds < 1:
        raise ValueError("health_stale_after_seconds must be positive")

    router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])
    read_access = _access_dependency(security_dependencies, Permission.READ_NODES)
    manage_access = _access_dependency(security_dependencies, Permission.MANAGE_NODES)
    stream_repository = NodeStreamRepository(
        repository._database  # noqa: SLF001 - shared node persistence boundary
    )

    @router.get("", response_model=list[NodeRead])
    def list_nodes(
        state_filter: Annotated[NodeState | None, Query(alias="state")] = None,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[NodeRead]:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            rows = scoped.list_nodes(state=state_filter)
            return [_node_read(scoped, row) for row in rows]
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{node_id}", response_model=NodeRead)
    def get_node(
        node_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> NodeRead:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            return _node_read(scoped, scoped.get_node(node_id))
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{node_id}/operational-state",
        response_model=NodeOperationalStateRead,
    )
    def get_operational_state(
        node_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> NodeOperationalStateRead:
        try:
            organization_id = authorized.principal.organization_id
            scoped_nodes = repository.for_organization(organization_id)
            node = scoped_nodes.get_node(node_id)
            scoped_streams = stream_repository.for_organization(organization_id)
            latest_health = scoped_streams.latest_health(node.node_id)
            latest_status = scoped_streams.latest_status(node.node_id)
            return _operational_state(
                node.node_id,
                latest_health=(
                    None
                    if latest_health is None
                    else NodeHealthRead.model_validate(latest_health)
                ),
                latest_status=(
                    None
                    if latest_status is None
                    else NodeStatusRead.model_validate(latest_status)
                ),
                stale_after_seconds=health_stale_after_seconds,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{node_id}/health-history",
        response_model=list[NodeHealthRead],
    )
    def get_health_history(
        node_id: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[NodeHealthRead]:
        try:
            organization_id = authorized.principal.organization_id
            scoped_nodes = repository.for_organization(organization_id)
            node = scoped_nodes.get_node(node_id)
            rows = stream_repository.for_organization(
                organization_id
            ).health_history(node.node_id, limit=limit)
            return [NodeHealthRead.model_validate(row) for row in rows]
        except Exception as error:
            raise _http_error(error) from error

    @router.get(
        "/{node_id}/status-history",
        response_model=list[NodeStatusRead],
    )
    def get_status_history(
        node_id: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> list[NodeStatusRead]:
        try:
            organization_id = authorized.principal.organization_id
            scoped_nodes = repository.for_organization(organization_id)
            node = scoped_nodes.get_node(node_id)
            rows = stream_repository.for_organization(
                organization_id
            ).status_history(node.node_id, limit=limit)
            return [NodeStatusRead.model_validate(row) for row in rows]
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
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            row = scoped.activate(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return _node_read(scoped, row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{node_id}/suspend", response_model=NodeRead)
    def suspend_node(
        node_id: str,
        payload: NodeStateChangeRequest,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> NodeRead:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            row = scoped.suspend(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return _node_read(scoped, row)
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{node_id}/revoke", response_model=NodeRead)
    def revoke_node(
        node_id: str,
        payload: NodeStateChangeRequest,
        authorized: AuthorizedRequest = Depends(manage_access),
    ) -> NodeRead:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            row = scoped.revoke(
                node_id,
                actor_subject=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                reason=payload.reason,
            )
            return _node_read(scoped, row)
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


def _node_read(repository: NodeRepository, node: CentralNode) -> NodeRead:
    credential = repository.current_credential(node.node_id)
    return NodeRead(
        **NodeRead.model_validate(node).model_dump(
            exclude={"current_credential"}
        ),
        current_credential=(
            None
            if credential is None
            else NodeCredentialRead.model_validate(credential)
        ),
    )


def _operational_state(
    node_id: str,
    *,
    latest_health: NodeHealthRead | None,
    latest_status: NodeStatusRead | None,
    stale_after_seconds: int,
    observed_at: datetime | None = None,
) -> NodeOperationalStateRead:
    now = _as_utc(observed_at or datetime.now(UTC))
    heartbeat_age: float | None = None
    if latest_health is not None:
        heartbeat_age = max(
            0.0,
            (now - _as_utc(latest_health.received_at)).total_seconds(),
        )

    offline_is_latest = bool(
        latest_status is not None
        and latest_status.status == "offline"
        and (
            latest_health is None
            or _as_utc(latest_status.received_at)
            >= _as_utc(latest_health.received_at)
        )
    )
    if offline_is_latest:
        availability = "offline"
    elif latest_health is None:
        availability = (
            "stale"
            if latest_status is not None and latest_status.status == "online"
            else "unknown"
        )
    elif heartbeat_age is not None and heartbeat_age > stale_after_seconds:
        availability = "stale"
    else:
        availability = "online"

    degraded_reason: str | None = None
    if availability == "offline" and latest_status is not None:
        degraded_reason = latest_status.reason
    elif latest_health is not None and latest_health.health == "degraded":
        degraded_reason = latest_health.last_error
    elif availability == "stale":
        degraded_reason = "node heartbeat is stale"

    return NodeOperationalStateRead(
        node_id=node_id,
        availability=availability,
        stale_after_seconds=stale_after_seconds,
        heartbeat_age_seconds=heartbeat_age,
        degraded_reason=degraded_reason,
        latest_health=latest_health,
        latest_status=latest_status,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _provision_response(stored: ProvisionedNode) -> ProvisionNodeResponse:
    credential = NodeCredentialRead.model_validate(stored.credential)
    return ProvisionNodeResponse(
        node=NodeRead(
            **NodeRead.model_validate(stored.node).model_dump(
                exclude={"current_credential"}
            ),
            current_credential=credential,
        ),
        credential=credential,
        provisioning_secret=stored.secret,
        replayed=stored.replayed,
    )


def _rotation_response(stored: RotatedNodeCredential) -> RotateNodeCredentialResponse:
    credential = NodeCredentialRead.model_validate(stored.credential)
    return RotateNodeCredentialResponse(
        node=NodeRead(
            **NodeRead.model_validate(stored.node).model_dump(
                exclude={"current_credential"}
            ),
            current_credential=credential,
        ),
        credential=credential,
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
