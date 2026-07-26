from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.alerts.domain import AlertSeverity, AlertState
from app.alerts.repository import (
    AlertConflictError,
    AlertNotFoundError,
    AlertRepository,
    AlertRepositoryError,
    AlertRuleConflictError,
    AlertRuleNotFoundError,
    RuleRecord,
)
from app.alerts.schemas import (
    AlertEvidencePage,
    AlertEvidenceRead,
    AlertLifecycleCommand,
    AlertLifecycleResponse,
    AlertPage,
    AlertRead,
    AlertRuleCreate,
    AlertRulePage,
    AlertRuleRead,
    AlertRuleReplace,
    AlertRuleVersionRead,
    AlertTransitionPage,
    AlertTransitionRead,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
]


def create_alert_router(
    repository: AlertRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_ALERTS,
    )
    manage_rules_access = _access_dependency(
        security_dependencies,
        Permission.MANAGE_ALERT_RULES,
    )
    acknowledge_access = _access_dependency(
        security_dependencies,
        Permission.ACKNOWLEDGE_ALERTS,
    )

    @router.post(
        "/rules",
        response_model=AlertRuleRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_rule(
        payload: AlertRuleCreate,
        authorized: AuthorizedRequest = Depends(manage_rules_access),
    ) -> AlertRuleRead:
        try:
            record = repository.for_organization(
                authorized.principal.organization_id
            ).create_rule(
                payload,
                actor_id=authorized.principal.subject,
            )
            return _rule_read(record)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/rules", response_model=AlertRulePage)
    def list_rules(
        authorized: AuthorizedRequest = Depends(read_access),
        enabled: Annotated[bool | None, Query()] = None,
        metric: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertRulePage:
        try:
            result = repository.for_organization(
                authorized.principal.organization_id
            ).list_rules(
                enabled=enabled,
                metric=metric,
                limit=limit,
                offset=offset,
            )
            return AlertRulePage(
                items=[_rule_read(item) for item in result.items],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/rules/{rule_id}", response_model=AlertRuleRead)
    def get_rule(
        rule_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> AlertRuleRead:
        try:
            record = repository.for_organization(
                authorized.principal.organization_id
            ).get_rule(rule_id)
            return _rule_read(record)
        except Exception as error:
            raise _http_error(error) from error

    @router.put("/rules/{rule_id}", response_model=AlertRuleRead)
    def replace_rule(
        rule_id: str,
        payload: AlertRuleReplace,
        authorized: AuthorizedRequest = Depends(manage_rules_access),
    ) -> AlertRuleRead:
        try:
            record = repository.for_organization(
                authorized.principal.organization_id
            ).replace_rule(
                rule_id,
                payload,
                actor_id=authorized.principal.subject,
            )
            return _rule_read(record)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/latest", response_model=AlertPage)
    def latest_alerts(
        authorized: AuthorizedRequest = Depends(read_access),
        severity: Annotated[AlertSeverity | None, Query()] = None,
        metric: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertPage:
        return _alert_page(
            repository,
            authorized,
            states=frozenset(
                {
                    AlertState.ACTIVE,
                    AlertState.ACKNOWLEDGED,
                    AlertState.RESOLVED,
                }
            ),
            severity=severity,
            metric=metric,
            limit=limit,
            offset=offset,
        )

    @router.get("/history", response_model=AlertPage)
    def alert_history(
        authorized: AuthorizedRequest = Depends(read_access),
        severity: Annotated[AlertSeverity | None, Query()] = None,
        metric: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertPage:
        return _alert_page(
            repository,
            authorized,
            states=frozenset({AlertState.CLOSED}),
            severity=severity,
            metric=metric,
            limit=limit,
            offset=offset,
        )

    @router.get("", response_model=AlertPage)
    def list_alerts(
        authorized: AuthorizedRequest = Depends(read_access),
        state_filter: Annotated[AlertState | None, Query(alias="state")] = None,
        severity: Annotated[AlertSeverity | None, Query()] = None,
        metric: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertPage:
        return _alert_page(
            repository,
            authorized,
            states=(
                frozenset({state_filter})
                if state_filter is not None
                else None
            ),
            severity=severity,
            metric=metric,
            limit=limit,
            offset=offset,
        )

    @router.get("/{alert_id}", response_model=AlertRead)
    def get_alert(
        alert_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> AlertRead:
        try:
            alert = repository.for_organization(
                authorized.principal.organization_id
            ).get_alert(alert_id)
            return AlertRead.model_validate(alert)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{alert_id}/transitions", response_model=AlertTransitionPage)
    def list_transitions(
        alert_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertTransitionPage:
        try:
            result = repository.for_organization(
                authorized.principal.organization_id
            ).transitions(alert_id, limit=limit, offset=offset)
            return AlertTransitionPage(
                items=[
                    AlertTransitionRead.model_validate(item)
                    for item in result.items
                ],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{alert_id}/evidence", response_model=AlertEvidencePage)
    def list_evidence(
        alert_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AlertEvidencePage:
        try:
            result = repository.for_organization(
                authorized.principal.organization_id
            ).evidence(alert_id, limit=limit, offset=offset)
            return AlertEvidencePage(
                items=[
                    AlertEvidenceRead.model_validate(item)
                    for item in result.items
                ],
                count=result.count,
                limit=result.limit,
                offset=result.offset,
                next_offset=result.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{alert_id}/acknowledge", response_model=AlertLifecycleResponse)
    def acknowledge_alert(
        alert_id: str,
        payload: AlertLifecycleCommand,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(acknowledge_access),
    ) -> AlertLifecycleResponse:
        try:
            result = repository.for_organization(
                authorized.principal.organization_id
            ).acknowledge(
                alert_id,
                payload,
                actor_id=authorized.principal.subject,
                actor_source=authorized.principal.provider,
                idempotency_key=idempotency_key,
            )
            return AlertLifecycleResponse(
                alert=AlertRead.model_validate(result.alert),
                transition=AlertTransitionRead.model_validate(result.transition),
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post("/{alert_id}/close", response_model=AlertLifecycleResponse)
    def close_alert(
        alert_id: str,
        payload: AlertLifecycleCommand,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(acknowledge_access),
    ) -> AlertLifecycleResponse:
        try:
            result = repository.for_organization(
                authorized.principal.organization_id
            ).close(
                alert_id,
                payload,
                actor_id=authorized.principal.subject,
                actor_source=authorized.principal.provider,
                idempotency_key=idempotency_key,
            )
            return AlertLifecycleResponse(
                alert=AlertRead.model_validate(result.alert),
                transition=AlertTransitionRead.model_validate(result.transition),
                replayed=result.replayed,
            )
        except Exception as error:
            raise _http_error(error) from error

    return router


def _alert_page(
    repository: AlertRepository,
    authorized: AuthorizedRequest,
    *,
    states: frozenset[AlertState] | None,
    severity: AlertSeverity | None,
    metric: str | None,
    limit: int,
    offset: int,
) -> AlertPage:
    try:
        result = repository.for_organization(
            authorized.principal.organization_id
        ).list_alerts(
            states=states,
            severity=severity.value if severity is not None else None,
            metric=metric,
            limit=limit,
            offset=offset,
        )
        return AlertPage(
            items=[AlertRead.model_validate(item) for item in result.items],
            count=result.count,
            limit=result.limit,
            offset=result.offset,
            next_offset=result.next_offset,
        )
    except Exception as error:
        raise _http_error(error) from error


def _rule_read(record: object) -> AlertRuleRead:
    if not isinstance(record, RuleRecord):
        raise TypeError("expected RuleRecord")
    return AlertRuleRead.model_validate(record.rule).model_copy(
        update={
            "version": AlertRuleVersionRead.model_validate(record.version),
        }
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


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, (AlertNotFoundError, AlertRuleNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, (AlertConflictError, AlertRuleConflictError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, AlertRepositoryError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, HTTPException):
        return error
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "alert_internal_error",
            "message": "alert operation failed",
        },
    )
