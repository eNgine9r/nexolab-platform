from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.alerts.domain import AlertCondition, AlertState
from app.alerts.repository import (
    AlertNotFoundError,
    AlertRepository,
    AlertRuleConflictError,
    AlertStateConflictError,
    CreateAlertRuleInput,
    serialize_alert,
    serialize_event,
    serialize_rule,
)
from app.security.authorization import Permission
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


class CreateAlertRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    node_id: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    condition: AlertCondition
    severity: Literal["information", "warning", "alarm", "critical", "system"]
    trigger_threshold: float | None = None
    clear_threshold: float | None = None
    target_quality: Literal[
        "valid", "sensor_error", "communication_error", "unknown"
    ] | None = None
    minimum_duration_seconds: int = Field(default=0, ge=0, le=86_400)
    cooldown_seconds: int = Field(default=0, ge=0, le=604_800)
    reason: str | None = Field(default=None, max_length=1024)


class AlertActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1024)


def create_alert_router(
    repository: AlertRepository,
    security: SecurityDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["alerts"])
    read_dependency = security.authorized_request(Permission.READ_TELEMETRY)
    manage_dependency = security.authorized_request(Permission.MANAGE_EQUIPMENT)
    acknowledge_dependency = security.authorized_request(
        Permission.ACKNOWLEDGE_ALERTS
    )

    @router.get("/alert-rules")
    def list_rules(
        enabled: bool | None = None,
        actor: AuthorizedRequest = Depends(read_dependency),
    ) -> dict[str, object]:
        rows = repository.list_rules(
            organization_id=actor.principal.organization_id,
            enabled=enabled,
        )
        return {"items": [serialize_rule(row) for row in rows]}

    @router.post("/alert-rules", status_code=status.HTTP_201_CREATED)
    def create_rule(
        payload: CreateAlertRuleRequest,
        actor: AuthorizedRequest = Depends(manage_dependency),
    ) -> dict[str, object]:
        try:
            row = repository.create_rule(
                CreateAlertRuleInput(
                    organization_id=actor.principal.organization_id,
                    name=payload.name,
                    node_id=payload.node_id,
                    equipment_id=payload.equipment_id,
                    channel_id=payload.channel_id,
                    metric=payload.metric,
                    condition=payload.condition,
                    severity=payload.severity,
                    trigger_threshold=payload.trigger_threshold,
                    clear_threshold=payload.clear_threshold,
                    target_quality=payload.target_quality,
                    minimum_duration_seconds=payload.minimum_duration_seconds,
                    cooldown_seconds=payload.cooldown_seconds,
                ),
                actor=actor,
                reason=payload.reason,
            )
        except ValueError as error:
            raise _unprocessable("invalid_alert_rule", str(error)) from error
        except AlertRuleConflictError as error:
            raise _conflict(error.code, str(error)) from error
        return serialize_rule(row)

    @router.get("/alerts")
    def list_alerts(
        state_filter: Annotated[
            list[AlertState] | None,
            Query(alias="state"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        actor: AuthorizedRequest = Depends(read_dependency),
    ) -> dict[str, object]:
        rows = repository.list_alerts(
            organization_id=actor.principal.organization_id,
            states=state_filter,
            limit=limit,
        )
        return {"items": [serialize_alert(row) for row in rows]}

    @router.get("/alerts/{alert_id}")
    def get_alert(
        alert_id: str,
        actor: AuthorizedRequest = Depends(read_dependency),
    ) -> dict[str, object]:
        try:
            row = repository.get_alert(
                organization_id=actor.principal.organization_id,
                alert_id=alert_id,
            )
        except AlertNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        return serialize_alert(row)

    @router.get("/alerts/{alert_id}/events")
    def list_alert_events(
        alert_id: str,
        actor: AuthorizedRequest = Depends(read_dependency),
    ) -> dict[str, object]:
        try:
            rows = repository.list_events(
                organization_id=actor.principal.organization_id,
                alert_id=alert_id,
            )
        except AlertNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        return {"items": [serialize_event(row) for row in rows]}

    @router.post("/alerts/{alert_id}/acknowledge")
    def acknowledge(
        alert_id: str,
        payload: AlertActionRequest,
        actor: AuthorizedRequest = Depends(acknowledge_dependency),
    ) -> dict[str, object]:
        try:
            row = repository.acknowledge(
                organization_id=actor.principal.organization_id,
                alert_id=alert_id,
                actor=actor,
                reason=payload.reason,
            )
        except AlertNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        except AlertStateConflictError as error:
            raise _conflict(error.code, str(error)) from error
        return serialize_alert(row)

    @router.post("/alerts/{alert_id}/close")
    def close(
        alert_id: str,
        payload: AlertActionRequest,
        actor: AuthorizedRequest = Depends(acknowledge_dependency),
    ) -> dict[str, object]:
        try:
            row = repository.close(
                organization_id=actor.principal.organization_id,
                alert_id=alert_id,
                actor=actor,
                reason=payload.reason,
            )
        except AlertNotFoundError as error:
            raise _not_found(error.code, str(error)) from error
        except AlertStateConflictError as error:
            raise _conflict(error.code, str(error)) from error
        return serialize_alert(row)

    return router


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )
