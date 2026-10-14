from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.api import _read_access_dependency
from app.db import Database
from app.energy_export.jobs import ExportJobs
from app.energy_export.schemas import STEPS, ExportError, ExportOptions
from app.energy_export.source import catalog
from app.security.authorization import Permission
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


def _owner(authorized: AuthorizedRequest) -> tuple[str, ...]:
    principal = authorized.principal
    return principal.organization_id, principal.provider, principal.subject, authorized.identity_id or ""


def _http(error: ExportError):
    status = 404 if error.code == "job_not_found" else 403 if error.code == "series_unavailable" else 503 if error.code in {"service_unavailable", "spool_unavailable"} else 429 if error.code in {"queue_full", "owner_limit"} else 409 if error.code in {"job_not_prepared", "artifact_not_ready", "download_expired"} else 422
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def create_energy_export_router(database: Database, jobs: ExportJobs, security_dependencies: SecurityDependencies | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/energy/exports", tags=["energy-exports"], dependencies=[Depends(_no_store)])
    read_access = _read_access_dependency(security_dependencies)

    @router.get("/catalog")
    def list_catalog(authorized: AuthorizedRequest = Depends(read_access)):
        try:
            return {"items": [item.model_dump() for item in catalog(database, authorized.principal.organization_id)], "timezone": "Europe/Kyiv", "steps": STEPS, "retention_days": jobs.policy.retention_days}
        except ExportError as error:
            raise _http(error) from error

    @router.post("/preview", status_code=202)
    def preview(options: ExportOptions, authorized: AuthorizedRequest = Depends(read_access)):
        try:
            return jobs.create(_owner(authorized), options)
        except ExportError as error:
            raise _http(error) from error

    @router.get("/{job_id}")
    def status(job_id: str, authorized: AuthorizedRequest = Depends(read_access)):
        try:
            return jobs.get(_owner(authorized), job_id)
        except ExportError as error:
            raise _http(error) from error

    @router.post("/{job_id}/start", status_code=202)
    def start(job_id: str, authorized: AuthorizedRequest = Depends(read_access)):
        try:
            return jobs.confirm(_owner(authorized), job_id)
        except ExportError as error:
            raise _http(error) from error

    @router.post("/{job_id}/cancel")
    def cancel(job_id: str, authorized: AuthorizedRequest = Depends(read_access)):
        try:
            return jobs.cancel(_owner(authorized), job_id)
        except ExportError as error:
            raise _http(error) from error

    @router.post("/{job_id}/download-ticket")
    def download_ticket(job_id: str, authorized: AuthorizedRequest = Depends(read_access), authorization: str | None = Header(default=None), selected_organization_id: str | None = Header(default=None, alias="X-Organization-ID")):
        try:
            def reauthorize():
                if security_dependencies is not None:
                    refreshed = security_dependencies.authorize_credentials(authorization, selected_organization_id, Permission.READ_TELEMETRY)
                    if _owner(refreshed) != _owner(authorized):
                        raise HTTPException(status_code=403, detail="Access denied")
            # This short-lived in-memory callback rechecks session revocation and
            # membership at the actual download. User credentials never enter a URL
            # or a job manifest; the URL contains only a one-use artifact nonce.
            result = jobs.ticket(_owner(authorized), job_id, reauthorize)
            return {"download_path": f"/api/v1/energy/exports/{job_id}/download?ticket={result['ticket']}", "expires_in_seconds": result["expires_in_seconds"]}
        except ExportError as error:
            raise _http(error) from error

    @router.get("/{job_id}/download")
    def download(job_id: str, ticket: Annotated[str, Query(min_length=40, max_length=64)]):
        try:
            path, filename, format = jobs.consume_ticket(job_id, ticket)
            return FileResponse(path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else "text/csv; charset=utf-8", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})
        except ExportError as error:
            raise _http(error) from error

    return router
