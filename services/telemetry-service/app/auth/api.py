from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from app.auth.middleware import current_principal
from app.auth.repository import AuthRepository


class AuthSessionResponse(BaseModel):
    subject: str
    organization_id: str
    role: str
    permissions: list[str]
    email: str | None
    display_name: str | None
    provider: str


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str | None
    actor_subject: str | None
    actor_role: str | None
    action: str
    outcome: str
    resource_type: str
    resource_id: str
    request_id: str
    metadata_payload: dict[str, Any]
    occurred_at: datetime


class AuditPageResponse(BaseModel):
    items: list[AuditEventResponse]
    count: int
    limit: int
    offset: int
    next_offset: int | None


def create_auth_router(repository: AuthRepository) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["authentication"])

    @router.get("/auth/session", response_model=AuthSessionResponse)
    def get_auth_session(request: Request) -> AuthSessionResponse:
        principal = current_principal(request)
        return AuthSessionResponse(
            subject=principal.subject,
            organization_id=principal.organization_id,
            role=principal.role.value,
            permissions=sorted(permission.value for permission in principal.permissions),
            email=principal.email,
            display_name=principal.display_name,
            provider=principal.provider,
        )

    @router.get("/audit/events", response_model=AuditPageResponse)
    def list_audit_events(
        request: Request,
        action: Annotated[str | None, Query(max_length=128)] = None,
        outcome: Annotated[str | None, Query(max_length=32)] = None,
        resource_type: Annotated[str | None, Query(max_length=64)] = None,
        resource_id: Annotated[str | None, Query(max_length=256)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AuditPageResponse:
        principal = current_principal(request)
        page = repository.list_audit(
            organization_id=principal.organization_id,
            action=action,
            outcome=outcome,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
        )
        return AuditPageResponse(
            items=[AuditEventResponse.model_validate(item) for item in page.items],
            count=page.count,
            limit=page.limit,
            offset=page.offset,
            next_offset=page.next_offset,
        )

    return router
