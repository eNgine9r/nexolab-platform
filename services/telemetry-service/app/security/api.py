from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.security.authorization import Permission, effective_permissions
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import SecurityRepository, SecuritySession


def create_security_router(
    repository: SecurityRepository,
    dependencies: SecurityDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["security"])

    @router.get("/auth/session")
    def auth_session(
        session: Annotated[SecuritySession, Depends(dependencies.current_session)],
    ) -> dict[str, Any]:
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
                {
                    "organization_id": membership.organization_id,
                    "organization_slug": membership.organization_slug,
                    "organization_name": membership.organization_name,
                    "roles": sorted(role.value for role in membership.roles),
                    "permissions": sorted(
                        permission.value
                        for permission in effective_permissions(membership.roles)
                    ),
                }
                for membership in session.memberships
            ],
        }

    @router.get("/audit/events")
    def audit_events(
        authorized: Annotated[
            AuthorizedRequest,
            Depends(dependencies.authorized_request(Permission.READ_AUDIT)),
        ],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        entity_type: Annotated[str | None, Query(max_length=128)] = None,
        entity_id: Annotated[str | None, Query(max_length=255)] = None,
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

    return router
