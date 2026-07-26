from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.reports.models import TestReportRender, TestReportVersion


class ReportOutputQueryError(RuntimeError):
    code = "report_output_query_error"


class ReportOutputQueryNotFoundError(ReportOutputQueryError):
    code = "report_output_not_found"


class ReportOutputQueryRepository:
    def __init__(
        self,
        database: Database,
        *,
        organization_id: str | None = None,
    ) -> None:
        self._engine = database.engine
        self._organization_id = organization_id

    def for_organization(self, organization_id: str) -> "ReportOutputQueryRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return ReportOutputQueryRepository(
            Database.from_engine(self._engine),
            organization_id=normalized,
        )

    def list_renders(self, report_id: str) -> list[TestReportRender]:
        normalized = _required_text(report_id, "report_id", 36)
        organization_id = self._scope()
        with Session(self._engine, expire_on_commit=False) as session:
            report = session.scalar(
                select(TestReportVersion.id).where(
                    TestReportVersion.id == normalized,
                    TestReportVersion.organization_id == organization_id,
                )
            )
            if report is None:
                raise ReportOutputQueryNotFoundError(
                    f"report {normalized!r} was not found"
                )
            rows = list(
                session.scalars(
                    select(TestReportRender)
                    .where(
                        TestReportRender.report_id == normalized,
                        TestReportRender.organization_id == organization_id,
                    )
                    .order_by(
                        TestReportRender.rendered_at.desc(),
                        TestReportRender.id.desc(),
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def _scope(self) -> str:
        if self._organization_id is None:
            raise ReportOutputQueryError("organization scope is required")
        return self._organization_id


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized
