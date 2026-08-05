from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
)
from app.db import Database
from app.live_dashboard.models import LiveDashboard, LiveDashboardItem
from app.live_dashboard.schemas import LiveDashboardItemWrite, LiveDashboardWrite
from app.nodes.models import CentralNode
from app.security.repository import AuditEventInput, SecurityRepository


DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True, slots=True)
class DashboardItemRecord:
    id: str
    position: int
    channel_ref_id: str
    channel_id: str
    metric: str
    native_unit: str
    visualization: str
    color: str | None
    display_unit: str | None


@dataclass(frozen=True, slots=True)
class DashboardRecord:
    id: str
    organization_id: str
    name: str
    description: str | None
    owner_subject: str
    refresh_seconds: int
    time_window: str
    version: int
    status: str
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    archived_by: str | None
    archived_at: datetime | None
    items: tuple[DashboardItemRecord, ...]


@dataclass(frozen=True, slots=True)
class DashboardPage:
    items: tuple[DashboardRecord, ...]
    total: int


class LiveDashboardRepositoryError(RuntimeError):
    code = "live_dashboard_repository_error"


class LiveDashboardNotFoundError(LiveDashboardRepositoryError):
    code = "live_dashboard_not_found"


class LiveDashboardArchivedError(LiveDashboardRepositoryError):
    code = "live_dashboard_archived"


class LiveDashboardChannelNotFoundError(LiveDashboardRepositoryError):
    code = "live_dashboard_channel_not_found"


class LiveDashboardChannelMetricMismatchError(LiveDashboardRepositoryError):
    code = "live_dashboard_channel_metric_mismatch"


class LiveDashboardUnitConversionUnsupportedError(LiveDashboardRepositoryError):
    code = "live_dashboard_unit_conversion_unsupported"


class LiveDashboardVersionConflictError(LiveDashboardRepositoryError):
    code = "live_dashboard_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"live dashboard version conflict: expected {expected_version}, "
            f"actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class LiveDashboardRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        include_archived: bool = False,
        limit: int,
        offset: int,
    ) -> DashboardPage:
        filters = [LiveDashboard.organization_id == organization_id]
        if not include_archived:
            filters.append(LiveDashboard.status == "active")
        with Session(self._engine, expire_on_commit=False) as session:
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(LiveDashboard)
                    .where(*filters)
                )
                or 0
            )
            dashboards = list(
                session.scalars(
                    select(LiveDashboard)
                    .where(*filters)
                    .order_by(
                        LiveDashboard.updated_at.desc(),
                        LiveDashboard.id.asc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            records = self._records(session, dashboards)
            return DashboardPage(items=records, total=total)

    def get(
        self,
        dashboard_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> DashboardRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            dashboard = self._dashboard(
                session,
                organization_id=organization_id,
                dashboard_id=dashboard_id,
                lock=False,
            )
            return self._record(session, dashboard)

    def create(
        self,
        payload: LiveDashboardWrite,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> DashboardRecord:
        now = datetime.now(UTC)
        dashboard_id = str(uuid4())
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                resolved_items = self._resolve_items(
                    session,
                    organization_id=organization_id,
                    items=payload.items,
                )
                dashboard = LiveDashboard(
                    id=dashboard_id,
                    organization_id=organization_id,
                    name=payload.name,
                    description=payload.description,
                    owner_subject=actor_id,
                    refresh_seconds=payload.refresh_seconds,
                    time_window=payload.time_window.value,
                    version=1,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                    created_at=now,
                    updated_at=now,
                    archived_by=None,
                    archived_at=None,
                )
                session.add(dashboard)
                session.flush()
                self._replace_items(
                    session,
                    dashboard=dashboard,
                    resolved_items=resolved_items,
                )
                record = self._record(session, dashboard)
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    entity_id=dashboard.id,
                    before=None,
                    after=_snapshot(record),
                )
            return record

    def update(
        self,
        dashboard_id: str,
        payload: LiveDashboardWrite,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> DashboardRecord:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                dashboard = self._dashboard(
                    session,
                    organization_id=organization_id,
                    dashboard_id=dashboard_id,
                    lock=True,
                )
                self._check_mutable(dashboard)
                self._check_version(dashboard, expected_version)
                before = _snapshot(self._record(session, dashboard))
                resolved_items = self._resolve_items(
                    session,
                    organization_id=organization_id,
                    items=payload.items,
                )
                dashboard.name = payload.name
                dashboard.description = payload.description
                dashboard.refresh_seconds = payload.refresh_seconds
                dashboard.time_window = payload.time_window.value
                dashboard.updated_by = actor_id
                dashboard.updated_at = now
                dashboard.version += 1
                self._replace_items(
                    session,
                    dashboard=dashboard,
                    resolved_items=resolved_items,
                )
                session.flush()
                record = self._record(session, dashboard)
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    entity_id=dashboard.id,
                    before=before,
                    after=_snapshot(record),
                )
            return record

    def archive(
        self,
        dashboard_id: str,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> DashboardRecord:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                dashboard = self._dashboard(
                    session,
                    organization_id=organization_id,
                    dashboard_id=dashboard_id,
                    lock=True,
                )
                self._check_mutable(dashboard)
                self._check_version(dashboard, expected_version)
                before = _snapshot(self._record(session, dashboard))
                dashboard.status = "archived"
                dashboard.archived_by = actor_id
                dashboard.archived_at = now
                dashboard.updated_by = actor_id
                dashboard.updated_at = now
                dashboard.version += 1
                session.flush()
                record = self._record(session, dashboard)
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    entity_id=dashboard.id,
                    before=before,
                    after=_snapshot(record),
                )
            return record

    @staticmethod
    def _dashboard(
        session: Session,
        *,
        organization_id: str,
        dashboard_id: str,
        lock: bool,
    ) -> LiveDashboard:
        statement = select(LiveDashboard).where(
            LiveDashboard.organization_id == organization_id,
            LiveDashboard.id == dashboard_id,
        )
        if lock:
            statement = statement.with_for_update()
        dashboard = session.scalar(statement)
        if dashboard is None:
            raise LiveDashboardNotFoundError(
                f"live dashboard {dashboard_id!r} was not found"
            )
        return dashboard

    @staticmethod
    def _check_mutable(dashboard: LiveDashboard) -> None:
        if dashboard.status != "active":
            raise LiveDashboardArchivedError(
                f"live dashboard {dashboard.id!r} is archived"
            )

    @staticmethod
    def _check_version(dashboard: LiveDashboard, expected_version: int) -> None:
        if dashboard.version != expected_version:
            raise LiveDashboardVersionConflictError(
                expected_version=expected_version,
                actual_version=dashboard.version,
            )

    @staticmethod
    def _resolve_items(
        session: Session,
        *,
        organization_id: str,
        items: list[LiveDashboardItemWrite],
    ) -> list[tuple[LiveDashboardItemWrite, MeasurementChannel]]:
        resolved: list[tuple[LiveDashboardItemWrite, MeasurementChannel]] = []
        for item in items:
            channel = session.scalar(
                select(MeasurementChannel)
                .join(
                    MeasurementDevice,
                    (
                        MeasurementDevice.organization_id
                        == MeasurementChannel.organization_id
                    )
                    & (MeasurementDevice.id == MeasurementChannel.device_id),
                )
                .join(
                    MeasurementBus,
                    (MeasurementBus.organization_id == MeasurementChannel.organization_id)
                    & (MeasurementBus.id == MeasurementChannel.bus_id),
                )
                .join(
                    ClimateChamber,
                    (
                        ClimateChamber.organization_id
                        == MeasurementChannel.organization_id
                    )
                    & (
                        ClimateChamber.id
                        == MeasurementChannel.climate_chamber_id
                    ),
                )
                .join(
                    CentralNode,
                    (CentralNode.organization_id == MeasurementBus.organization_id)
                    & (CentralNode.node_id == MeasurementBus.node_id),
                )
                .where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.channel_id == item.channel_id,
                    MeasurementChannel.status == "active",
                    MeasurementDevice.status == "active",
                    MeasurementBus.status == "active",
                    ClimateChamber.status == "active",
                    CentralNode.state != "revoked",
                )
            )
            if channel is None:
                raise LiveDashboardChannelNotFoundError(
                    f"active channel {item.channel_id!r} was not found "
                    "in this organization"
                )
            if channel.metric_type != item.metric:
                raise LiveDashboardChannelMetricMismatchError(
                    f"channel {item.channel_id!r} exposes metric "
                    f"{channel.metric_type!r}, not {item.metric!r}"
                )
            if item.display_unit is not None and item.display_unit != channel.unit:
                raise LiveDashboardUnitConversionUnsupportedError(
                    f"display unit {item.display_unit!r} is not supported for "
                    f"channel {item.channel_id!r}; native unit is {channel.unit!r}"
                )
            resolved.append((item, channel))
        return resolved

    @staticmethod
    def _replace_items(
        session: Session,
        *,
        dashboard: LiveDashboard,
        resolved_items: list[tuple[LiveDashboardItemWrite, MeasurementChannel]],
    ) -> None:
        session.execute(
            delete(LiveDashboardItem).where(
                LiveDashboardItem.organization_id == dashboard.organization_id,
                LiveDashboardItem.dashboard_id == dashboard.id,
            )
        )
        session.add_all(
            LiveDashboardItem(
                id=str(uuid4()),
                organization_id=dashboard.organization_id,
                dashboard_id=dashboard.id,
                position=position,
                channel_ref_id=channel.id,
                channel_id=channel.channel_id,
                metric=item.metric,
                native_unit=channel.unit,
                visualization=item.visualization.value,
                color=item.color,
                display_unit=item.display_unit,
            )
            for position, (item, channel) in enumerate(resolved_items, start=1)
        )
        session.flush()

    @staticmethod
    def _records(
        session: Session,
        dashboards: list[LiveDashboard],
    ) -> tuple[DashboardRecord, ...]:
        if not dashboards:
            return ()
        dashboard_ids = [dashboard.id for dashboard in dashboards]
        rows = list(
            session.scalars(
                select(LiveDashboardItem)
                .where(LiveDashboardItem.dashboard_id.in_(dashboard_ids))
                .order_by(
                    LiveDashboardItem.dashboard_id,
                    LiveDashboardItem.position,
                    LiveDashboardItem.id,
                )
            )
        )
        grouped: dict[str, list[LiveDashboardItem]] = {
            dashboard_id: [] for dashboard_id in dashboard_ids
        }
        for row in rows:
            grouped[row.dashboard_id].append(row)
        return tuple(
            _dashboard_record(dashboard, grouped[dashboard.id])
            for dashboard in dashboards
        )

    @staticmethod
    def _record(
        session: Session,
        dashboard: LiveDashboard,
    ) -> DashboardRecord:
        rows = list(
            session.scalars(
                select(LiveDashboardItem)
                .where(
                    LiveDashboardItem.organization_id
                    == dashboard.organization_id,
                    LiveDashboardItem.dashboard_id == dashboard.id,
                )
                .order_by(
                    LiveDashboardItem.position,
                    LiveDashboardItem.id,
                )
            )
        )
        return _dashboard_record(dashboard, rows)

    @staticmethod
    def _append_audit(
        session: Session,
        repository: SecurityRepository | None,
        event: AuditEventInput | None,
        *,
        entity_id: str,
        before: dict[str, object] | None,
        after: dict[str, object],
    ) -> None:
        if repository is None or event is None:
            return
        repository.append_audit_event(
            replace(
                event,
                entity_id=entity_id,
                before_snapshot=before,
                after_snapshot=after,
            ),
            session=session,
        )


def _dashboard_record(
    dashboard: LiveDashboard,
    items: list[LiveDashboardItem],
) -> DashboardRecord:
    return DashboardRecord(
        id=dashboard.id,
        organization_id=dashboard.organization_id,
        name=dashboard.name,
        description=dashboard.description,
        owner_subject=dashboard.owner_subject,
        refresh_seconds=dashboard.refresh_seconds,
        time_window=dashboard.time_window,
        version=dashboard.version,
        status=dashboard.status,
        created_by=dashboard.created_by,
        updated_by=dashboard.updated_by,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
        archived_by=dashboard.archived_by,
        archived_at=dashboard.archived_at,
        items=tuple(
            DashboardItemRecord(
                id=item.id,
                position=item.position,
                channel_ref_id=item.channel_ref_id,
                channel_id=item.channel_id,
                metric=item.metric,
                native_unit=item.native_unit,
                visualization=item.visualization,
                color=item.color,
                display_unit=item.display_unit,
            )
            for item in items
        ),
    )


def _snapshot(record: DashboardRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "organization_id": record.organization_id,
        "name": record.name,
        "description": record.description,
        "owner_subject": record.owner_subject,
        "refresh_seconds": record.refresh_seconds,
        "time_window": record.time_window,
        "version": record.version,
        "status": record.status,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "archived_by": record.archived_by,
        "items": [
            {
                "position": item.position,
                "channel_ref_id": item.channel_ref_id,
                "channel_id": item.channel_id,
                "metric": item.metric,
                "native_unit": item.native_unit,
                "visualization": item.visualization,
                "color": item.color,
                "display_unit": item.display_unit,
            }
            for item in record.items
        ],
    }
