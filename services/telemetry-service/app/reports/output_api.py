from __future__ import annotations

from typing import Annotated, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.reports.approval import ApprovalCommand, ApprovalSnapshot, ReportApprovalError
from app.reports.output_queries import (
    ReportOutputQueryError,
    ReportOutputQueryNotFoundError,
    ReportOutputQueryRepository,
)
from app.reports.output_repository import (
    ReportOutputIdempotencyConflictError,
    ReportOutputNotFoundError,
    ReportOutputRepository,
    ReportOutputRepositoryError,
    ReportReplacementError,
    StoredApproval,
    StoredRender,
    SupersedeCommand,
)
from app.reports.output_schemas import (
    ReportApprovalActionResponse,
    ReportApprovalStateRead,
    ReportApproveRequest,
    ReportOutputStateRead,
    ReportRenderRead,
    ReportRenderRequest,
    ReportRenderResponse,
    ReportSupersedeRequest,
)
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
]


def create_report_output_router(
    repository: ReportOutputRepository,
    query_repository: ReportOutputQueryRepository,
    security_dependencies: SecurityDependencies | None = None,
    security_repository: SecurityRepository | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/reports", tags=["report-outputs"])
    read_access = _access_dependency(security_dependencies, Permission.READ_REPORTS)
    render_access = _access_dependency(
        security_dependencies,
        Permission.GENERATE_REPORTS,
    )
    approve_access = _access_dependency(
        security_dependencies,
        Permission.APPROVE_REPORTS,
    )

    @router.get("/{report_id}/outputs", response_model=ReportOutputStateRead)
    def get_output_state(
        report_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ReportOutputStateRead:
        try:
            organization_id = authorized.principal.organization_id
            scoped = repository.for_organization(organization_id)
            query = query_repository.for_organization(organization_id)
            return ReportOutputStateRead(
                report_id=report_id,
                approval=_approval_read(scoped.approval_snapshot(report_id)),
                renders=[
                    ReportRenderRead.model_validate(row)
                    for row in query.list_renders(report_id)
                ],
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{report_id}/renders/{format_name}",
        response_model=ReportRenderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def render_report(
        report_id: str,
        format_name: str,
        payload: ReportRenderRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(render_access),
    ) -> ReportRenderResponse | JSONResponse:
        try:
            stored = repository.for_organization(
                authorized.principal.organization_id
            ).render(
                report_id,
                format_name=format_name,
                idempotency_key=idempotency_key,
                rendered_by=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                expected_manifest_sha256=payload.expected_manifest_sha256,
                reason=payload.reason,
            )
            response = _render_response(stored)
            if stored.replayed:
                return JSONResponse(
                    content=response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                    headers={"Idempotent-Replay": "true"},
                )
            return response
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{report_id}/renders/{render_id}")
    def download_render(
        report_id: str,
        render_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> Response:
        try:
            row = repository.for_organization(
                authorized.principal.organization_id
            ).get_render(render_id)
            if row.report_id != report_id:
                raise ReportOutputNotFoundError(
                    f"render {render_id!r} was not found for report {report_id!r}"
                )
            _audit_render_access(
                security_repository,
                row=row,
                authorized=authorized,
            )
            encoded_name = quote(row.artifact_name, safe="")
            return Response(
                content=row.content,
                media_type=row.media_type,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{encoded_name}"
                    ),
                    "X-Content-SHA256": row.sha256,
                    "X-Manifest-SHA256": row.manifest_sha256,
                    "Content-Length": str(row.size_bytes),
                    "ETag": f'"{row.sha256}"',
                },
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{report_id}/approve",
        response_model=ReportApprovalActionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def approve_report(
        report_id: str,
        payload: ReportApproveRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(approve_access),
    ) -> ReportApprovalActionResponse | JSONResponse:
        try:
            stored = repository.for_organization(
                authorized.principal.organization_id
            ).approve(
                report_id,
                ApprovalCommand(
                    idempotency_key=idempotency_key,
                    actor_subject=authorized.principal.subject,
                    reason=payload.reason,
                    expected_manifest_sha256=payload.expected_manifest_sha256.lower(),
                    occurred_at=payload.occurred_at,
                ),
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
            )
            return _approval_response(stored)
        except Exception as error:
            raise _http_error(error) from error

    @router.post(
        "/{report_id}/supersede",
        response_model=ReportApprovalActionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def supersede_report(
        report_id: str,
        payload: ReportSupersedeRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(approve_access),
    ) -> ReportApprovalActionResponse | JSONResponse:
        try:
            stored = repository.for_organization(
                authorized.principal.organization_id
            ).supersede(
                report_id,
                SupersedeCommand(
                    idempotency_key=idempotency_key,
                    actor_subject=authorized.principal.subject,
                    reason=payload.reason,
                    expected_manifest_sha256=payload.expected_manifest_sha256.lower(),
                    replacement_report_id=payload.replacement_report_id,
                    occurred_at=payload.occurred_at,
                ),
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
            )
            return _approval_response(stored)
        except Exception as error:
            raise _http_error(error) from error

    return router


def _render_response(stored: StoredRender) -> ReportRenderResponse:
    payload = ReportRenderRead.model_validate(stored.render)
    return ReportRenderResponse(
        **payload.model_dump(),
        replayed=stored.replayed,
    )


def _approval_response(
    stored: StoredApproval,
) -> ReportApprovalActionResponse | JSONResponse:
    response = ReportApprovalActionResponse(
        event_id=stored.event.id,
        decision=stored.decision.value,
        approval=_approval_read(stored.snapshot),
    )
    if stored.decision.value == "replay":
        return JSONResponse(
            content=response.model_dump(mode="json"),
            status_code=status.HTTP_200_OK,
            headers={"Idempotent-Replay": "true"},
        )
    return response


def _approval_read(snapshot: ApprovalSnapshot) -> ReportApprovalStateRead:
    return ReportApprovalStateRead(
        state=snapshot.state.value,
        manifest_sha256=snapshot.manifest_sha256,
        approved_by=snapshot.approved_by,
        approved_at=snapshot.approved_at,
        approval_reason=snapshot.approval_reason,
        approval_idempotency_key=snapshot.approval_idempotency_key,
        approval_command_sha256=snapshot.approval_command_sha256,
        superseded_by_report_id=snapshot.superseded_by_report_id,
        superseded_at=snapshot.superseded_at,
    )


def _audit_render_access(
    security_repository: SecurityRepository | None,
    *,
    row: object,
    authorized: AuthorizedRequest,
) -> None:
    if security_repository is None:
        return
    render = row
    security_repository.append_audit_event(
        AuditEventInput(
            organization_id=authorized.principal.organization_id,
            actor_identity_id=authorized.identity_id,
            actor_subject=authorized.principal.subject,
            actor_roles=authorized.principal.roles,
            action="report.render.downloaded",
            entity_type="test_report_render",
            entity_id=render.id,
            after_snapshot={
                "report_id": render.report_id,
                "format": render.format,
                "artifact_name": render.artifact_name,
                "manifest_sha256": render.manifest_sha256,
                "sha256": render.sha256,
                "size_bytes": render.size_bytes,
            },
        )
    )


def _http_error(error: Exception) -> HTTPException:
    if isinstance(
        error,
        (
            ReportOutputNotFoundError,
            ReportOutputQueryNotFoundError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(
        error,
        (
            ReportApprovalError,
            ReportOutputIdempotencyConflictError,
            ReportReplacementError,
            ReportOutputRepositoryError,
        ),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(error, ValueError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "report_output_validation_error",
                "message": str(error),
            },
        )
    if isinstance(error, ReportOutputQueryError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": str(error)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "report_output_internal_error",
            "message": "report output operation failed",
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
