from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.nodes.broker_control import BrokerControlOperation, BrokerControlState
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.broker_schemas import (
    BrokerControlCommandRead,
    BrokerDesiredState,
    BrokerSynchronizationState,
    NodeBrokerControlRead,
)
from app.nodes.domain import NodeState
from app.nodes.repository import NodeNotFoundError, NodeRepository
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


def create_broker_control_router(
    node_repository: NodeRepository,
    broker_repository: BrokerControlRepository | None,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/nodes", tags=["node-broker-control"])
    read_access = _access_dependency(security_dependencies, Permission.READ_NODES)

    @router.get(
        "/{node_id}/broker-control",
        response_model=NodeBrokerControlRead,
    )
    def get_broker_control(
        node_id: str,
        limit: int = Query(default=20, ge=1, le=100),
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> NodeBrokerControlRead:
        organization_id = authorized.principal.organization_id
        try:
            node = node_repository.for_organization(organization_id).get_node(node_id)
        except NodeNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": error.code, "message": str(error)},
            ) from error

        desired_state, compatible_operations = _desired_broker_state(
            NodeState(node.state)
        )
        if broker_repository is None:
            return NodeBrokerControlRead(
                node_id=node.node_id,
                lifecycle_state=NodeState(node.state),
                enabled=False,
                desired_state=desired_state,
                synchronization="disabled",
                synchronized=False,
                latest_command=None,
                commands=[],
            )

        rows = broker_repository.history(
            organization_id=organization_id,
            node_id=node.node_id,
            limit=limit,
        )
        commands = [BrokerControlCommandRead.model_validate(row) for row in rows]
        latest = commands[0] if commands else None
        synchronization, synchronized = _synchronization(
            latest,
            compatible_operations=compatible_operations,
        )
        return NodeBrokerControlRead(
            node_id=node.node_id,
            lifecycle_state=NodeState(node.state),
            enabled=True,
            desired_state=desired_state,
            synchronization=synchronization,
            synchronized=synchronized,
            latest_command=latest,
            commands=commands,
        )

    return router


def _desired_broker_state(
    state: NodeState,
) -> tuple[BrokerDesiredState, frozenset[BrokerControlOperation]]:
    if state is NodeState.PENDING:
        return "provisioned", frozenset({BrokerControlOperation.PROVISION})
    if state is NodeState.ACTIVE:
        return "enabled", frozenset(
            {
                BrokerControlOperation.PROVISION,
                BrokerControlOperation.ROTATE,
                BrokerControlOperation.ENABLE,
            }
        )
    if state is NodeState.SUSPENDED:
        return "disabled", frozenset({BrokerControlOperation.DISABLE})
    return "deleted", frozenset({BrokerControlOperation.DELETE})


def _synchronization(
    latest: BrokerControlCommandRead | None,
    *,
    compatible_operations: frozenset[BrokerControlOperation],
) -> tuple[BrokerSynchronizationState, bool]:
    if latest is None:
        return "unknown", False
    if latest.operation not in compatible_operations:
        return "out_of_sync", False
    if latest.state is BrokerControlState.APPLIED:
        return "applied", True
    return latest.state.value, False


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
