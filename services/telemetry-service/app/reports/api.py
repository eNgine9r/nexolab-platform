from __future__ import annotations

from typing import Annotated, Callable
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.reports.repository import (
    ReportIdempotencyConflictError,
    ReportNotFoundError,
    ReportRecord,
    ReportRepository,
    ReportRepositoryError,
    ReportSessionNotFoundError,
    ReportSessionStateError,
    ReportSourceChangedError,
)
from app.reports.schemas import (
    ReportArtifactRead,
    ReportGenerateRequest,
    ReportGenerationResponse,
    ReportPageRead,
    ReportRead,
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


def create_report_router(
    repository: ReportRepository,
    security_dependencies: SecurityDependencies | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_REPORTS,
    )
    generate_access = _access_dependency(
        security_dependencies,
        Permission.GENERATE_REPORTS,
    )

    @router.post(
        "/sessions/{session_id}",
        response_model=ReportGenerationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def generate_report(
        session_id: str,
        payload: ReportGenerateRequest,
        idempotency_key: IdempotencyKey,
        authorized: AuthorizedRequest = Depends(generate_access),
    ) -> ReportGenerationResponse | JSONResponse:
        try:
            record = repository.for_organization(
                authorized.principal.organization_id
            ).generate(
                session_id,
                idempotency_key=idempotency_key,
                generated_by=authorized.principal.subject,
                actor_identity_id=authorized.identity_id,
                actor_roles=authorized.principal.roles,
                expected_source_sha256=payload.expected_source_sha256,
                reason=payload.reason,
                binding_ids=payload.binding_ids,
            )
            response = _generation_read(record)
            if record.replayed:
                return JSONResponse(
                    content=response.model_dump(mode="json"),
                    status_code=status.HTTP_200_OK,
                    headers={"Idempotent-Replay": "true"},
                )
            return response
        except Exception as error:
            raise _http_error(error) from error

    @router.get("", response_model=ReportPageRead)
    def list_reports(
        authorized: AuthorizedRequest = Depends(read_access),
        session_id: Annotated[str | None, Query(max_length=36)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ReportPageRead:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            page = scoped.list_reports(
                session_id=session_id,
                limit=limit,
                offset=offset,
            )
            return ReportPageRead(
                items=[_report_read(scoped.get_report(item.id)) for item in page.items],
                count=page.count,
                limit=page.limit,
                offset=page.offset,
                next_offset=page.next_offset,
            )
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{report_id}", response_model=ReportRead)
    def get_report(
        report_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ReportRead:
        try:
            record = repository.for_organization(
                authorized.principal.organization_id
            ).get_report(report_id)
            return _report_read(record)
        except Exception as error:
            raise _http_error(error) from error

    @router.get("/{report_id}/artifacts/{artifact_name}")
    def download_artifact(
        report_id: str,
        artifact_name: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> Response:
        try:
            scoped = repository.for_organization(
                authorized.principal.organization_id
            )
            artifact = scoped.get_artifact(report_id, artifact_name)
            scoped.audit_artifact_access(
                artifact,
                actor_identity_id=authorized.identity_id,
                actor_subject=authorized.principal.subject,
                actor_roles=authorized.principal.roles,
            )
            encoded_name = quote(artifact.name, safe="")
            return Response(
                content=artifact.content,
                media_type=artifact.media_type,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{encoded_name}"
                    ),
                    "X-Content-SHA256": artifact.sha256,
                    "Content-Length": str(artifact.size_bytes),
                },
            )
        except Exception as error:
            raise _http_error(error) from error

    return router


def _report_read(record: ReportRecord) -> ReportRead:
    report = record.report
    return ReportRead(
        id=report.id,
        organization_id=report.organization_id,
        session_id=report.session_id,
        config_snapshot_id=report.config_snapshot_id,
        version=report.version,
        session_state=report.session_state,
        source_started_at=report.source_started_at,
        source_ended_at=report.source_ended_at,
        source_sha256=report.source_sha256,
        manifest_sha256=report.manifest_sha256,
        generator_version=report.generator_version,
        generated_by=report.generated_by,
        generated_at=report.generated_at,
        created_at=report.created_at,
        artifacts=[
            ReportArtifactRead.model_validate(artifact)
            for artifact in record.artifacts
        ],
    )


def _generation_read(record: ReportRecord) -> ReportGenerationResponse:
    payload = _report_read(record)
    return ReportGenerationResponse(
        **payload.model_dump(),
        replayed=record.replayed,
    )


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, (ReportNotFoundError, ReportSessionNotFoundError)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": str(error)},
        )
    if isinstance(
        error,
        (
            ReportSessionStateError,
            ReportSourceChangedError,
            ReportIdempotencyConflictError,
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
                "code": "report_validation_error",
                "message": str(error),
            },
        )
    if isinstance(error, ReportRepositoryError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": error.code, "message": str(error)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "report_internal_error",
            "message": "report operation failed",
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
