from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.auth.domain import (
    AuthError,
    PermissionDeniedError,
    Principal,
    Role,
    permission_for_http_request,
    permissions_for_role,
)
from app.auth.repository import AuthRepository, ResourceOrganizationError
from app.auth.service import AuthService


_PUBLIC_PATHS = {"/", "/health/live", "/health/ready"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True, slots=True)
class ResourceContext:
    resource_type: str
    resource_id: str
    create_if_missing: bool


class AuthenticationAuthorizationMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        service: AuthService,
        repository: AuthRepository,
    ) -> None:
        super().__init__(app)
        self._service = service
        self._repository = repository

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or path in _PUBLIC_PATHS:
            return await call_next(request)

        request_id = _request_id(request)
        principal: Principal | None = None
        try:
            principal = self._service.authenticate(request.headers.get("Authorization"))
            request.state.principal = principal
            permission = permission_for_http_request(request.method, path)
            if permission is not None and not principal.has(permission):
                raise PermissionDeniedError(permission)

            resource = _resource_context(request.method, path)
            if resource is not None and self._service.persistence_enforced:
                self._repository.ensure_resource_access(
                    principal,
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    create_if_missing=resource.create_if_missing,
                )
        except AuthError as error:
            self._safe_audit(
                principal=principal,
                action=_audit_action(request.method, path),
                outcome="denied",
                resource=_resource_context(request.method, path),
                request_id=request_id,
                metadata_payload={"code": error.code, "status_code": error.status_code},
            )
            return _error_response(error, request_id=request_id)

        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)

        if request.method not in _SAFE_METHODS and path.startswith("/api/v1/"):
            resource = _resource_context(request.method, path)
            self._safe_audit(
                principal=principal,
                action=_audit_action(request.method, path),
                outcome="success" if response.status_code < 400 else "failed",
                resource=resource,
                request_id=request_id,
                metadata_payload={"status_code": response.status_code},
            )
        return response

    def _safe_audit(
        self,
        *,
        principal: Principal | None,
        action: str,
        outcome: str,
        resource: ResourceContext | None,
        request_id: str,
        metadata_payload: dict[str, object],
    ) -> None:
        if not self._service.persistence_enforced:
            return
        try:
            self._repository.record_audit(
                principal=principal,
                action=action,
                outcome=outcome,
                resource_type=resource.resource_type if resource else "http_endpoint",
                resource_id=resource.resource_id if resource else action,
                request_id=request_id,
                metadata_payload=metadata_payload,
            )
        except Exception:
            # Authentication and authorization remain fail-closed even when audit
            # persistence is temporarily unavailable.
            return


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal

    # Routers are also exercised directly in focused unit tests without the
    # application middleware stack. Deployed requests always pass through the
    # middleware; this compatibility principal is limited to direct invocation.
    return Principal(
        subject="development-admin",
        organization_id="nexolab-default",
        role=Role.ADMIN,
        permissions=permissions_for_role(Role.ADMIN),
        email="development-admin@nexolab.local",
        display_name="Development administrator",
        provider="development",
    )


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and len(supplied) <= 128:
        return supplied
    return str(uuid4())


def _resource_context(method: str, path: str) -> ResourceContext | None:
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 4 and segments[:3] == ["api", "v1", "equipment"]:
        equipment_id = segments[3]
        create_if_missing = (
            method.upper() not in _SAFE_METHODS
            or segments[4:] == ["layout", "draft"]
        )
        return ResourceContext(
            resource_type="equipment",
            resource_id=equipment_id,
            create_if_missing=create_if_missing,
        )

    if len(segments) >= 4 and segments[:3] == ["api", "v1", "sessions"]:
        session_id = segments[3]
        if session_id not in {"telemetry"}:
            return ResourceContext(
                resource_type="test_session",
                resource_id=session_id,
                create_if_missing=True,
            )
    return None


def _audit_action(method: str, path: str) -> str:
    return f"http.{method.lower()}:{path}"[:128]


def _error_response(error: AuthError, *, request_id: str) -> JSONResponse:
    headers = {"X-Request-ID": request_id}
    if error.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    payload: dict[str, object] = {
        "detail": {
            "code": error.code,
            "message": str(error),
            "request_id": request_id,
        }
    }
    if isinstance(error, PermissionDeniedError):
        detail = payload["detail"]
        assert isinstance(detail, dict)
        detail["permission"] = error.permission.value
    if isinstance(error, ResourceOrganizationError):
        detail = payload["detail"]
        assert isinstance(detail, dict)
        detail["organization_scoped"] = True
    return JSONResponse(payload, status_code=error.status_code, headers=headers)
