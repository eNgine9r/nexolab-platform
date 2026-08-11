from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.local_admin_api import create_local_user_admin_router
from app.security.local_admin_service import LocalUserAdminService
from app.security.repository import AuditEventInput, SecurityRepository, SecuritySession


class MembershipUpsertRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    roles: set[Role] = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=1024)


def create_security_router(
    repository: SecurityRepository,
    dependencies: SecurityDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["security"])

    @router.get("/auth/session")
    def auth_session(
        session: SecuritySession = Depends(dependencies.current_session),
    ) -> dict[str, Any]:
        return _session_payload(session)

    @router.put("/organizations/{organization_id}/memberships")
    def upsert_membership(
        organization_id: str,
        payload: MembershipUpsertRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.MANAGE_MEMBERSHIPS)
        ),
    ) -> dict[str, Any]:
        if organization_id != authorized.principal.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "organization_scope_mismatch",
                    "message": "membership can only be managed in the selected organization",
                },
            )
        target_claims = VerifiedIdentityClaims(
            provider=payload.provider.strip(),
            subject=payload.subject.strip(),
            email=payload.email.strip() if payload.email else None,
            display_name=payload.display_name.strip() if payload.display_name else None,
        )
        target_session = repository.provision_membership(
            organization_id=organization_id,
            claims=target_claims,
            roles=payload.roles,
            assigned_by=authorized.principal.subject,
            audit_event=AuditEventInput(
                organization_id=organization_id,
                actor_identity_id=authorized.identity_id,
                actor_subject=authorized.principal.subject,
                actor_roles=authorized.principal.roles,
                action="security.membership.upserted",
                entity_type="organization_membership",
                entity_id="pending",
                reason=payload.reason,
                request_id=request.headers.get("X-Request-ID"),
                source_ip=request.client.host if request.client is not None else None,
                user_agent=request.headers.get("User-Agent"),
            ),
        )
        membership = next(
            item
            for item in target_session.memberships
            if item.organization_id == organization_id
        )
        return {
            "identity": {
                "id": target_session.identity_id,
                "provider": target_session.provider,
                "subject": target_session.subject,
                "email": target_session.email,
                "display_name": target_session.display_name,
            },
            "membership": _membership_payload(membership),
        }

    @router.get("/audit/events")
    def audit_events(
        authorized: AuthorizedRequest = Depends(
            dependencies.authorized_request(Permission.READ_AUDIT)
        ),
        limit: int = Query(default=100, ge=1, le=500),
        entity_type: str | None = Query(default=None, max_length=128),
        entity_id: str | None = Query(default=None, max_length=255),
    ) -> dict[str, Any]:
        rows = repository.list_audit_events(
            organization_id=authorized.principal.organization_id,
            limit=limit,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "organization_id": row.organization_id,
                    "actor_identity_id": row.actor_identity_id,
                    "actor_subject": row.actor_subject,
                    "actor_roles": row.actor_roles,
                    "action": row.action,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "before_snapshot": row.before_snapshot,
                    "after_snapshot": row.after_snapshot,
                    "reason": row.reason,
                    "request_id": row.request_id,
                    "source_ip": row.source_ip,
                    "user_agent": row.user_agent,
                    "occurred_at": row.occurred_at.isoformat(),
                }
                for row in rows
            ],
            "count": len(rows),
        }

    if dependencies.local_user_administration_enabled:
        database_view = SimpleNamespace(engine=repository._engine)  # noqa: SLF001
        router.include_router(
            create_local_user_admin_router(
                LocalUserAdminService(  # type: ignore[arg-type]
                    database_view,
                    repository,
                ),
                dependencies,
            )
        )

    return router


def _session_payload(session: SecuritySession) -> dict[str, Any]:
    return {
        "authenticated": True,
        "identity": {
            "id": session.identity_id,
            "provider": session.provider,
            "subject": session.subject,
            "email": session.email,
            "display_name": session.display_name,
        },
        "memberships": [
            _membership_payload(membership)
            for membership in session.memberships
        ],
    }


def _membership_payload(membership: object) -> dict[str, Any]:
    return {
        "organization_id": membership.organization_id,
        "organization_slug": membership.organization_slug,
        "organization_name": membership.organization_name,
        "roles": sorted(role.value for role in membership.roles),
        "permissions": sorted(
            permission.value for permission in membership.permissions
        ),
    }
