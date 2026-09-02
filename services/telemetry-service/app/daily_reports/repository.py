from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
import math
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance, AlertTransition
from app.daily_reports.domain import (
    DAILY_REPORT_SCHEMA,
    TelemetryPoint,
    calculate_compressor_runtime,
    calculate_state_duration,
    derive_source_gap_seconds,
    next_scheduled_at,
    resolve_report_window,
    validate_weekdays,
)
from app.daily_reports.models import (
    RefrigerationDailyReportProfile,
    RefrigerationDailyReportSnapshot,
)
from app.daily_reports.schemas import DailyReportProfileWrite, TelemetryIdentity
from app.db import Database, TelemetrySample
from app.refrigeration.models import (
    EquipmentSensorBinding,
    RefrigerationControllerBinding,
    RefrigerationEquipmentRecord,
)
from app.nodes.domain import NodeState
from app.nodes.models import CentralNode
from app.reports.domain import canonical_json_bytes, sha256_hex
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository
from app.sessions.time_utils import as_utc

_SYSTEM_ACTOR = "system:daily-report-scheduler"
_CONTROL_STATES = {
    0: "idle",
    1: "cooling",
    2: "prepare_defrost",
    3: "defrost",
    4: "post_defrost",
    5: "pulldown",
}


class DailyReportRepositoryError(RuntimeError):
    code = "daily_report_repository_error"


class DailyReportNotFoundError(DailyReportRepositoryError):
    code = "daily_report_not_found"


class DailyReportProfileNotFoundError(DailyReportRepositoryError):
    code = "daily_report_profile_not_found"


class DailyReportProfileConflictError(DailyReportRepositoryError):
    code = "daily_report_profile_conflict"


class DailyReportProfileVersionConflictError(DailyReportRepositoryError):
    code = "daily_report_profile_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"daily report profile version conflict: expected {expected_version}, "
            f"actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class DailyReportGenerationError(DailyReportRepositoryError):
    code = "daily_report_generation_error"


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    snapshot: RefrigerationDailyReportSnapshot
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class SnapshotPage:
    items: list[RefrigerationDailyReportSnapshot]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


class DailyReportRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
        organization_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._engine = database.engine
        self._security_repository = security_repository
        self._organization_id = organization_id
        self._clock = clock or (lambda: datetime.now(UTC))

    def for_organization(self, organization_id: str) -> "DailyReportRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return DailyReportRepository(
            self._database,
            security_repository=self._security_repository,
            organization_id=normalized,
            clock=self._clock,
        )

    def create_profile(
        self,
        payload: DailyReportProfileWrite,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str | None = None,
    ) -> RefrigerationDailyReportProfile:
        organization_id = self._scope()
        now = self._clock()
        record = RefrigerationDailyReportProfile(
            id=str(uuid4()),
            organization_id=organization_id,
            equipment_id=payload.equipment_id,
            name=payload.name,
            enabled=payload.enabled,
            timezone=payload.timezone,
            report_hour=payload.report_hour,
            report_minute=payload.report_minute,
            weekdays=list(payload.weekdays),
            analysis_window_minutes=payload.analysis_window_minutes,
            m_packet_channels=[item.model_dump(exclude_none=True) for item in payload.m_packet_channels],
            temperature_min_c=payload.temperature_min_c,
            temperature_max_c=payload.temperature_max_c,
            energy_source=(payload.energy_source.model_dump(exclude_none=True) if payload.energy_source else None),
            version=1,
            created_by=_required_text(actor_subject, "actor_subject", 255),
            created_at=now,
            updated_at=now,
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    equipment = self._require_equipment(session, payload.equipment_id)
                    self._validate_profile_sources(session, equipment, payload)
                    session.add(record)
                    session.flush()
                    self._audit(
                        session,
                        action="daily_report.profile.created",
                        entity_type="daily_report_profile",
                        entity_id=record.id,
                        actor_identity_id=actor_identity_id,
                        actor_subject=actor_subject,
                        actor_roles=actor_roles,
                        before=None,
                        after=_profile_snapshot(record),
                        reason=reason,
                    )
                session.expunge(record)
                return record
        except IntegrityError as error:
            raise DailyReportProfileConflictError(
                "daily report profile name or equipment relationship conflicts with existing data"
            ) from error

    def update_profile(
        self,
        profile_id: str,
        payload: DailyReportProfileWrite,
        *,
        expected_version: int,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str | None = None,
    ) -> RefrigerationDailyReportProfile:
        now = self._clock()
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    record = self._locked_profile(session, profile_id)
                    if record.version != expected_version:
                        raise DailyReportProfileVersionConflictError(
                            expected_version=expected_version,
                            actual_version=record.version,
                        )
                    equipment = self._require_equipment(session, payload.equipment_id)
                    self._validate_profile_sources(session, equipment, payload)
                    before = _profile_snapshot(record)
                    record.equipment_id = payload.equipment_id
                    record.name = payload.name
                    record.enabled = payload.enabled
                    record.timezone = payload.timezone
                    record.report_hour = payload.report_hour
                    record.report_minute = payload.report_minute
                    record.weekdays = list(payload.weekdays)
                    record.analysis_window_minutes = payload.analysis_window_minutes
                    record.m_packet_channels = [
                        item.model_dump(exclude_none=True) for item in payload.m_packet_channels
                    ]
                    record.temperature_min_c = payload.temperature_min_c
                    record.temperature_max_c = payload.temperature_max_c
                    record.energy_source = (
                        payload.energy_source.model_dump(exclude_none=True)
                        if payload.energy_source
                        else None
                    )
                    record.version += 1
                    record.updated_at = now
                    session.flush()
                    self._audit(
                        session,
                        action="daily_report.profile.updated",
                        entity_type="daily_report_profile",
                        entity_id=record.id,
                        actor_identity_id=actor_identity_id,
                        actor_subject=actor_subject,
                        actor_roles=actor_roles,
                        before=before,
                        after=_profile_snapshot(record),
                        reason=reason,
                    )
                session.expunge(record)
                return record
        except IntegrityError as error:
            raise DailyReportProfileConflictError(
                "daily report profile name or equipment relationship conflicts with existing data"
            ) from error

    def list_enabled_profile_refs(self) -> list[tuple[str, str]]:
        """Return bounded scheduler identities without crossing tenant data boundaries."""
        with Session(self._engine) as session:
            return list(
                session.execute(
                    select(
                        RefrigerationDailyReportProfile.organization_id,
                        RefrigerationDailyReportProfile.id,
                    )
                    .where(RefrigerationDailyReportProfile.enabled.is_(True))
                    .order_by(
                        RefrigerationDailyReportProfile.organization_id,
                        RefrigerationDailyReportProfile.id,
                    )
                ).all()
            )

    def list_profiles(self, *, enabled_only: bool = False) -> list[RefrigerationDailyReportProfile]:
        statement = select(RefrigerationDailyReportProfile).where(
            RefrigerationDailyReportProfile.organization_id == self._scope()
        )
        if enabled_only:
            statement = statement.where(RefrigerationDailyReportProfile.enabled.is_(True))
        statement = statement.order_by(
            RefrigerationDailyReportProfile.name,
            RefrigerationDailyReportProfile.id,
        )
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            session.expunge_all()
            return rows

    def next_scheduled_for(self, now: datetime) -> datetime | None:
        profiles = self.list_profiles(enabled_only=True)
        if not profiles:
            return None
        candidates = [
            next_scheduled_at(
                now,
                timezone=profile.timezone,
                report_hour=profile.report_hour,
                report_minute=profile.report_minute,
                weekdays=profile.weekdays,
            )
            for profile in profiles
        ]
        return min(candidates)

    def get_profile(self, profile_id: str) -> RefrigerationDailyReportProfile:
        with Session(self._engine, expire_on_commit=False) as session:
            record = session.scalar(
                select(RefrigerationDailyReportProfile).where(
                    RefrigerationDailyReportProfile.organization_id == self._scope(),
                    RefrigerationDailyReportProfile.id == profile_id,
                )
            )
            if record is None:
                raise DailyReportProfileNotFoundError(
                    f"daily report profile {profile_id!r} was not found"
                )
            session.expunge(record)
            return record

    def generate(
        self,
        profile_id: str,
        *,
        local_report_date: date,
        generated_by: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str | None = None,
    ) -> SnapshotRecord:
        organization_id = self._scope()
        actor = _required_text(generated_by, "generated_by", 255)
        generated_at = self._clock()
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    profile = self._locked_profile(session, profile_id)
                    if local_report_date.weekday() not in validate_weekdays(profile.weekdays):
                        raise DailyReportGenerationError(
                            "requested report date is not enabled by the profile weekday schedule"
                        )
                    window = resolve_report_window(
                        local_report_date,
                        timezone=profile.timezone,
                        report_hour=profile.report_hour,
                        report_minute=profile.report_minute,
                        analysis_window_minutes=profile.analysis_window_minutes,
                    )
                    if window.scheduled_for > generated_at:
                        raise DailyReportGenerationError(
                            "daily report snapshot cannot be generated before its scheduled time"
                        )
                    existing = session.scalar(
                        select(RefrigerationDailyReportSnapshot).where(
                            RefrigerationDailyReportSnapshot.organization_id == organization_id,
                            RefrigerationDailyReportSnapshot.profile_id == profile_id,
                            RefrigerationDailyReportSnapshot.local_report_date == local_report_date,
                        )
                    )
                    if existing is not None:
                        session.expunge(existing)
                        return SnapshotRecord(existing, replayed=True)
                    equipment = self._require_equipment(session, profile.equipment_id)
                    payload, overall_status = self._build_payload(
                        session,
                        profile=profile,
                        equipment=equipment,
                        window_start=window.window_start,
                        window_end=window.window_end,
                        scheduled_for=window.scheduled_for,
                        local_report_date=local_report_date,
                    )
                    normalized_payload = json.loads(canonical_json_bytes(payload))
                    snapshot = RefrigerationDailyReportSnapshot(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        profile_id=profile.id,
                        equipment_id=profile.equipment_id,
                        local_report_date=local_report_date,
                        scheduled_for=window.scheduled_for,
                        window_start=window.window_start,
                        window_end=window.window_end,
                        timezone=window.timezone,
                        status=overall_status,
                        schema_version=DAILY_REPORT_SCHEMA,
                        payload=normalized_payload,
                        payload_sha256=sha256_hex(canonical_json_bytes(normalized_payload)),
                        generated_by=actor,
                        generated_at=generated_at,
                        created_at=generated_at,
                    )
                    session.add(snapshot)
                    session.flush()
                    self._audit(
                        session,
                        action="daily_report.snapshot.generated",
                        entity_type="daily_report_snapshot",
                        entity_id=snapshot.id,
                        actor_identity_id=actor_identity_id,
                        actor_subject=actor,
                        actor_roles=actor_roles,
                        before=None,
                        after={
                            "profile_id": profile.id,
                            "equipment_id": profile.equipment_id,
                            "local_report_date": local_report_date.isoformat(),
                            "status": overall_status,
                            "payload_sha256": snapshot.payload_sha256,
                        },
                        reason=reason,
                    )
                session.expunge(snapshot)
                return SnapshotRecord(snapshot, replayed=False)
        except IntegrityError as error:
            # A concurrent generator may have won the unique profile/date insert.
            with Session(self._engine, expire_on_commit=False) as session:
                existing = session.scalar(
                    select(RefrigerationDailyReportSnapshot).where(
                        RefrigerationDailyReportSnapshot.organization_id == organization_id,
                        RefrigerationDailyReportSnapshot.profile_id == profile_id,
                        RefrigerationDailyReportSnapshot.local_report_date == local_report_date,
                    )
                )
                if existing is not None:
                    session.expunge(existing)
                    return SnapshotRecord(existing, replayed=True)
            raise DailyReportGenerationError("daily report generation conflicted") from error

    def list_snapshots(
        self,
        *,
        profile_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SnapshotPage:
        filters = [RefrigerationDailyReportSnapshot.organization_id == self._scope()]
        if profile_id is not None:
            filters.append(RefrigerationDailyReportSnapshot.profile_id == profile_id)
        statement = (
            select(RefrigerationDailyReportSnapshot)
            .where(*filters)
            .order_by(
                RefrigerationDailyReportSnapshot.scheduled_for.desc(),
                RefrigerationDailyReportSnapshot.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        count_statement = (
            select(func.count())
            .select_from(RefrigerationDailyReportSnapshot)
            .where(*filters)
        )
        with Session(self._engine, expire_on_commit=False) as session:
            items = list(session.scalars(statement))
            count = int(session.scalar(count_statement) or 0)
            session.expunge_all()
            return SnapshotPage(items=items, count=count, limit=limit, offset=offset)

    def get_snapshot(self, snapshot_id: str) -> RefrigerationDailyReportSnapshot:
        with Session(self._engine, expire_on_commit=False) as session:
            snapshot = session.scalar(
                select(RefrigerationDailyReportSnapshot).where(
                    RefrigerationDailyReportSnapshot.organization_id == self._scope(),
                    RefrigerationDailyReportSnapshot.id == snapshot_id,
                )
            )
            if snapshot is None:
                raise DailyReportNotFoundError(
                    f"daily report snapshot {snapshot_id!r} was not found"
                )
            session.expunge(snapshot)
            return snapshot

    def _build_payload(
        self,
        session: Session,
        *,
        profile: RefrigerationDailyReportProfile,
        equipment: RefrigerationEquipmentRecord,
        window_start: datetime,
        window_end: datetime,
        scheduled_for: datetime,
        local_report_date: date,
    ) -> tuple[dict[str, Any], str]:
        identities = [TelemetryIdentity.model_validate(item) for item in profile.m_packet_channels]
        m_packets = self._m_packet_summary(
            session,
            identities=identities,
            window_start=window_start,
            window_end=window_end,
            minimum=profile.temperature_min_c,
            maximum=profile.temperature_max_c,
        )
        binding = session.scalar(
            select(RefrigerationControllerBinding).where(
                RefrigerationControllerBinding.organization_id == self._scope(),
                RefrigerationControllerBinding.equipment_id == profile.equipment_id,
                RefrigerationControllerBinding.unbound_at.is_(None),
            )
        )
        controller, compressor, defrost = self._controller_summaries(
            session,
            binding=binding,
            window_start=window_start,
            window_end=window_end,
        )
        energy = self._energy_summary(
            session,
            source=(
                TelemetryIdentity.model_validate(profile.energy_source)
                if profile.energy_source is not None
                else None
            ),
            window_start=window_start,
            window_end=window_end,
        )
        alerts = self._alert_summary(
            session,
            equipment_id=profile.equipment_id,
            controller_equipment_id=(binding.controller_equipment_id if binding else None),
            identities=identities,
            window_start=window_start,
            window_end=window_end,
        )
        incomplete_reasons: list[str] = []
        if m_packets["valid_channels"] < m_packets["configured_channels"]:
            incomplete_reasons.append("m_packet_coverage_incomplete")
        if binding is None:
            incomplete_reasons.append("controller_not_bound")
        else:
            if controller["status"] != "available":
                incomplete_reasons.append("controller_state_unavailable")
            if compressor["status"] != "available":
                incomplete_reasons.append("compressor_evidence_unavailable")
            elif not _interval_evidence_complete(compressor):
                incomplete_reasons.append("compressor_coverage_incomplete")
            if defrost["status"] != "available":
                incomplete_reasons.append("defrost_evidence_unavailable")
            elif not _interval_evidence_complete(defrost):
                incomplete_reasons.append("defrost_coverage_incomplete")
        if profile.energy_source is not None and energy["status"] != "available":
            incomplete_reasons.append("energy_evidence_unavailable")
        if alerts["truncated"]:
            incomplete_reasons.append("alert_history_truncated")

        active_severities = set(alerts["active_severities"])
        if active_severities.intersection({"critical", "alarm"}):
            overall_status = "critical"
        elif "warning" in active_severities or m_packets["out_of_limit_channels"]:
            overall_status = "attention"
        elif incomplete_reasons:
            overall_status = "incomplete"
        else:
            overall_status = "normal"

        unavailable_metric = {"status": "unavailable", "reason": "not_implemented"}
        payload = {
            "schema": DAILY_REPORT_SCHEMA,
            "identity": {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "equipment_id": equipment.id,
                "equipment_code": equipment.code,
                "equipment_name": equipment.name,
                "manufacturer": equipment.manufacturer,
                "model": equipment.model,
                "serial_number": equipment.serial_number,
            },
            "report": {
                "local_report_date": local_report_date.isoformat(),
                "timezone": profile.timezone,
                "scheduled_for": scheduled_for,
                "window_start": window_start,
                "window_end": window_end,
                "analysis_window_minutes": profile.analysis_window_minutes,
                "status": overall_status,
            },
            "m_packets": m_packets,
            "controller": controller,
            "refrigeration_circuit": {
                "evaporation_pressure": unavailable_metric,
                "evaporation_saturation_temperature": unavailable_metric,
                "evaporator_outlet_temperature_186": unavailable_metric,
                "superheat": unavailable_metric,
                "condensation_pressure": unavailable_metric,
                "condensation_saturation_temperature": unavailable_metric,
                "showcase_inlet_temperature_187": unavailable_metric,
                "subcooling": unavailable_metric,
            },
            "compressor": compressor,
            "energy": energy,
            "defrost": _public_defrost_summary(defrost),
            "alerts": alerts,
            "quality": {
                "status": "incomplete" if incomplete_reasons else "complete",
                "reasons": incomplete_reasons,
            },
        }
        return payload, overall_status

    def _m_packet_summary(
        self,
        session: Session,
        *,
        identities: list[TelemetryIdentity],
        window_start: datetime,
        window_end: datetime,
        minimum: float | None,
        maximum: float | None,
    ) -> dict[str, Any]:
        channel_rows: list[dict[str, Any]] = []
        current_values: list[float] = []
        out_of_limit: list[dict[str, Any]] = []
        for identity in identities:
            rows = list(
                session.scalars(
                    select(TelemetrySample)
                    .where(
                        TelemetrySample.node_id == identity.node_id,
                        TelemetrySample.equipment_id == identity.equipment_id,
                        TelemetrySample.channel_id == identity.channel_id,
                        TelemetrySample.metric == identity.metric,
                        TelemetrySample.captured_at >= window_start,
                        TelemetrySample.captured_at <= window_end,
                    )
                    .order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
                )
            )
            points = [_telemetry_point(row) for row in rows]
            source_gap = derive_source_gap_seconds(points) if points else None
            latest = points[-1] if points else None
            age_seconds = (
                (as_utc(window_end) - as_utc(latest.captured_at)).total_seconds()
                if latest is not None
                else None
            )
            current_value = (
                latest.value
                if latest is not None
                and latest.quality == "valid"
                and latest.value is not None
                and math.isfinite(latest.value)
                and age_seconds is not None
                and source_gap is not None
                and 0 <= age_seconds <= source_gap
                else None
            )
            if latest is None:
                reason = "no_data"
            elif age_seconds is None or source_gap is None or age_seconds > source_gap:
                reason = "stale"
            elif latest.quality != "valid" or latest.value is None:
                reason = "invalid_quality"
            else:
                reason = None
            is_out = bool(
                current_value is not None
                and (
                    (minimum is not None and current_value < minimum)
                    or (maximum is not None and current_value > maximum)
                )
            )
            item = {
                "node_id": identity.node_id,
                "equipment_id": identity.equipment_id,
                "channel_id": identity.channel_id,
                "metric": identity.metric,
                "label": identity.label,
                "status": "available" if current_value is not None else "unavailable",
                "reason": reason,
                "value_c": current_value,
                "captured_at": as_utc(latest.captured_at) if latest is not None else None,
                "age_seconds": age_seconds,
                "source_gap_seconds": source_gap,
            }
            channel_rows.append(item)
            if current_value is not None:
                current_values.append(current_value)
            if is_out:
                out_of_limit.append(item)
        return {
            "status": "available" if current_values else "unavailable",
            "minimum_c": min(current_values) if current_values else None,
            "maximum_c": max(current_values) if current_values else None,
            "valid_channels": sum(1 for item in channel_rows if item["status"] == "available"),
            "configured_channels": len(channel_rows),
            "temperature_limits_c": {"minimum": minimum, "maximum": maximum},
            "out_of_limit_channels": out_of_limit,
            "channels": channel_rows,
        }

    def _controller_summaries(
        self,
        session: Session,
        *,
        binding: RefrigerationControllerBinding | None,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if binding is None:
            unavailable = {"status": "unavailable", "reason": "controller_not_bound"}
            return unavailable, unavailable.copy(), unavailable.copy()
        speed = self._metric_points(
            session,
            node_id=binding.node_id,
            equipment_id=binding.controller_equipment_id,
            metric="compressor.speed",
            window_start=window_start,
            window_end=window_end,
            surrounding=True,
        )
        runtime = calculate_compressor_runtime(
            speed,
            window_start=window_start,
            window_end=window_end,
        )
        state = self._metric_points(
            session,
            node_id=binding.node_id,
            equipment_id=binding.controller_equipment_id,
            metric="refrigeration.control_state",
            window_start=window_start,
            window_end=window_end,
            surrounding=True,
        )
        defrost_result = calculate_state_duration(
            state,
            window_start=window_start,
            window_end=window_end,
            active_values=frozenset({3}),
        )
        current_state = self._current_state(state, window_end)
        controller = {
            "status": "available" if current_state is not None else "unavailable",
            "family": binding.controller_family,
            "controller_equipment_id": binding.controller_equipment_id,
            "profile_version": binding.profile_version,
            "control_state": current_state,
            "setpoint": {"status": "unavailable", "reason": "unverified_semantics"},
        }
        compressor = {
            "status": runtime.status,
            "duty_percent": runtime.duty_percent,
            "running_seconds": runtime.running_seconds,
            "observed_seconds": runtime.observed_seconds,
            "requested_seconds": runtime.requested_seconds,
            "coverage_percent": runtime.coverage_percent,
            "continuity_breaks": runtime.continuity_breaks,
            "source_gap_seconds": runtime.source_gap_seconds,
        }
        defrost = {
            "status": defrost_result.status,
            "duration_seconds": defrost_result.duration_seconds,
            "observed_seconds": defrost_result.observed_seconds,
            "requested_seconds": defrost_result.requested_seconds,
            "coverage_percent": defrost_result.coverage_percent,
            "continuity_breaks": defrost_result.continuity_breaks,
            "source_gap_seconds": defrost_result.source_gap_seconds,
        }
        return controller, compressor, defrost

    @staticmethod
    def _current_state(points: list[TelemetryPoint], window_end: datetime) -> dict[str, Any] | None:
        candidates = [point for point in points if point.captured_at <= window_end]
        if not candidates:
            return None
        latest = max(candidates, key=lambda point: point.captured_at)
        if (
            latest.quality != "valid"
            or latest.value is None
            or not math.isfinite(latest.value)
            or latest.value < 0
        ):
            return None
        gap = derive_source_gap_seconds(points)
        age = (as_utc(window_end) - as_utc(latest.captured_at)).total_seconds()
        if age < 0 or age > gap:
            return None
        raw = int(latest.value)
        return {
            "value": raw,
            "semantic": _CONTROL_STATES.get(raw, "unknown"),
            "captured_at": as_utc(latest.captured_at),
        }

    def _energy_summary(
        self,
        session: Session,
        *,
        source: TelemetryIdentity | None,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, Any]:
        if source is None:
            return {"status": "unavailable", "reason": "not_configured"}
        if source.metric != "electrical.energy.active":
            return {"status": "unavailable", "reason": "unsupported_metric"}
        before = session.scalar(
            select(TelemetrySample)
            .where(
                *_identity_filters(source),
                TelemetrySample.captured_at <= window_start,
            )
            .order_by(TelemetrySample.captured_at.desc(), TelemetrySample.event_id.desc())
            .limit(1)
        )
        ending = session.scalar(
            select(TelemetrySample)
            .where(
                *_identity_filters(source),
                TelemetrySample.captured_at <= window_end,
            )
            .order_by(TelemetrySample.captured_at.desc(), TelemetrySample.event_id.desc())
            .limit(1)
        )
        if before is None or ending is None or ending.captured_at <= before.captured_at:
            return {"status": "unavailable", "reason": "boundary_evidence_missing"}
        rows = list(
            session.scalars(
                select(TelemetrySample)
                .where(
                    *_identity_filters(source),
                    TelemetrySample.captured_at >= before.captured_at,
                    TelemetrySample.captured_at <= ending.captured_at,
                )
                .order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
            )
        )
        points = [_telemetry_point(row) for row in rows]
        gap = derive_source_gap_seconds(points)
        start_age = (as_utc(window_start) - as_utc(before.captured_at)).total_seconds()
        end_age = (as_utc(window_end) - as_utc(ending.captured_at)).total_seconds()
        if start_age < 0 or end_age < 0 or start_age > gap or end_age > gap:
            return {"status": "unavailable", "reason": "boundary_evidence_stale"}
        if any(
            row.quality != "valid"
            or row.value is None
            or not math.isfinite(row.value)
            or row.unit != "kWh"
            for row in rows
        ):
            return {"status": "unavailable", "reason": "invalid_evidence"}
        ordered_values = [float(row.value) for row in rows if row.value is not None]
        if any(right < left for left, right in zip(ordered_values, ordered_values[1:], strict=False)):
            return {"status": "unavailable", "reason": "counter_discontinuity"}
        ordered_times = [as_utc(row.captured_at) for row in rows]
        if any(
            (right - left).total_seconds() > gap
            for left, right in zip(ordered_times, ordered_times[1:], strict=False)
        ):
            return {"status": "unavailable", "reason": "continuity_gap"}
        delta = ordered_values[-1] - ordered_values[0]
        return {
            "status": "available",
            "interval_kwh": delta,
            "start_kwh": ordered_values[0],
            "end_kwh": ordered_values[-1],
            "source": source.model_dump(exclude_none=True),
            "start_captured_at": as_utc(before.captured_at),
            "end_captured_at": as_utc(ending.captured_at),
            "source_gap_seconds": gap,
        }

    def _alert_summary(
        self,
        session: Session,
        *,
        equipment_id: str,
        controller_equipment_id: str | None,
        identities: list[TelemetryIdentity],
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, Any]:
        equipment_ids = {equipment_id, *(item.equipment_id for item in identities)}
        if controller_equipment_id:
            equipment_ids.add(controller_equipment_id)
        channel_ids = {item.channel_id for item in identities}
        resource_filter = AlertInstance.equipment_id.in_(sorted(equipment_ids))
        if channel_ids:
            resource_filter = or_(
                resource_filter,
                AlertInstance.channel_id.in_(sorted(channel_ids)),
            )
        rows = list(
            session.scalars(
                select(AlertInstance)
                .where(
                    AlertInstance.organization_id == self._scope(),
                    resource_filter,
                    AlertInstance.triggered_at < window_end,
                    or_(
                        AlertInstance.closed_at.is_(None),
                        AlertInstance.closed_at >= window_start,
                    ),
                )
                .order_by(AlertInstance.triggered_at.desc(), AlertInstance.id.desc())
                .limit(50)
            )
        )
        state_at_end: dict[str, str] = {}
        if rows:
            transitions = list(
                session.scalars(
                    select(AlertTransition)
                    .where(
                        AlertTransition.alert_id.in_([row.id for row in rows]),
                        AlertTransition.occurred_at <= window_end,
                    )
                    .order_by(AlertTransition.occurred_at, AlertTransition.id)
                )
            )
            for transition in transitions:
                state_at_end[transition.alert_id] = transition.next_state
        active = [
            row
            for row in rows
            if state_at_end.get(row.id) in {"active", "acknowledged"}
        ]
        return {
            "active_count": len(active),
            "recent_count": len(rows),
            "truncated": len(rows) >= 50,
            "active_severities": sorted({row.severity for row in active}),
            "items": [
                {
                    "id": row.id,
                    "severity": row.severity,
                    "state": state_at_end.get(row.id, "unknown"),
                    "equipment_id": row.equipment_id,
                    "channel_id": row.channel_id,
                    "metric": row.metric,
                    "triggered_at": as_utc(row.triggered_at),
                    "resolved_at": (
                        as_utc(row.resolved_at)
                        if row.resolved_at is not None
                        and as_utc(row.resolved_at) <= as_utc(window_end)
                        else None
                    ),
                    "closed_at": (
                        as_utc(row.closed_at)
                        if row.closed_at is not None
                        and as_utc(row.closed_at) <= as_utc(window_end)
                        else None
                    ),
                }
                for row in rows[:20]
            ],
        }

    def _metric_points(
        self,
        session: Session,
        *,
        node_id: str,
        equipment_id: str,
        metric: str,
        window_start: datetime,
        window_end: datetime,
        surrounding: bool,
    ) -> list[TelemetryPoint]:
        rows: list[TelemetrySample] = []
        if surrounding:
            predecessor = session.scalar(
                select(TelemetrySample)
                .where(
                    TelemetrySample.node_id == node_id,
                    TelemetrySample.equipment_id == equipment_id,
                    TelemetrySample.metric == metric,
                    TelemetrySample.captured_at < window_start,
                )
                .order_by(TelemetrySample.captured_at.desc(), TelemetrySample.event_id.desc())
                .limit(1)
            )
            if predecessor is not None:
                rows.append(predecessor)
        rows.extend(
            session.scalars(
                select(TelemetrySample)
                .where(
                    TelemetrySample.node_id == node_id,
                    TelemetrySample.equipment_id == equipment_id,
                    TelemetrySample.metric == metric,
                    TelemetrySample.captured_at >= window_start,
                    TelemetrySample.captured_at <= window_end,
                )
                .order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
            )
        )
        if surrounding:
            successor = session.scalar(
                select(TelemetrySample)
                .where(
                    TelemetrySample.node_id == node_id,
                    TelemetrySample.equipment_id == equipment_id,
                    TelemetrySample.metric == metric,
                    TelemetrySample.captured_at > window_end,
                )
                .order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
                .limit(1)
            )
            if successor is not None:
                rows.append(successor)
        return [_telemetry_point(row) for row in rows]

    def _locked_profile(
        self,
        session: Session,
        profile_id: str,
    ) -> RefrigerationDailyReportProfile:
        profile = session.scalar(
            select(RefrigerationDailyReportProfile)
            .where(
                RefrigerationDailyReportProfile.organization_id == self._scope(),
                RefrigerationDailyReportProfile.id == profile_id,
            )
            .with_for_update()
        )
        if profile is None:
            raise DailyReportProfileNotFoundError(
                f"daily report profile {profile_id!r} was not found"
            )
        return profile

    def _validate_profile_sources(
        self,
        session: Session,
        equipment: RefrigerationEquipmentRecord,
        payload: DailyReportProfileWrite,
    ) -> None:
        organization_id = self._scope()
        bindings = list(
            session.scalars(
                select(EquipmentSensorBinding).where(
                    EquipmentSensorBinding.organization_id == organization_id,
                    EquipmentSensorBinding.equipment_id == equipment.id,
                    EquipmentSensorBinding.unbound_at.is_(None),
                )
            )
        )
        allowed_channels = {(item.node_id, item.channel_id) for item in bindings}
        for identity in payload.m_packet_channels:
            if identity.metric != "temperature.probe":
                raise ValueError("M-packet channels must use temperature.probe")
            if (identity.node_id, identity.channel_id) not in allowed_channels:
                raise ValueError(
                    "M-packet channel must be actively bound to the selected refrigeration equipment"
                )

        if payload.energy_source is not None and payload.energy_source.metric != "electrical.energy.active":
            raise ValueError("energy_source must use electrical.energy.active")

        source_nodes = {identity.node_id for identity in payload.m_packet_channels}
        if payload.energy_source is not None:
            source_nodes.add(payload.energy_source.node_id)
        for node_id in source_nodes:
            owners = set(
                session.scalars(
                    select(CentralNode.organization_id)
                    .where(
                        CentralNode.node_id == node_id,
                        CentralNode.state != NodeState.REVOKED.value,
                    )
                    .distinct()
                )
            )
            if owners != {organization_id}:
                raise ValueError(
                    f"telemetry node {node_id!r} is not uniquely owned by this organization"
                )

    def _require_equipment(
        self,
        session: Session,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        equipment = session.scalar(
            select(RefrigerationEquipmentRecord).where(
                RefrigerationEquipmentRecord.organization_id == self._scope(),
                RefrigerationEquipmentRecord.id == equipment_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
            )
        )
        if equipment is None:
            raise DailyReportGenerationError(
                f"active refrigeration equipment {equipment_id!r} was not found"
            )
        return equipment

    def _audit(
        self,
        session: Session,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        actor_identity_id: str | None,
        actor_subject: str,
        actor_roles: frozenset[Role],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str | None,
    ) -> None:
        if self._security_repository is None:
            return
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=self._scope(),
                actor_identity_id=actor_identity_id,
                actor_subject=_required_text(actor_subject, "actor_subject", 255),
                actor_roles=actor_roles,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_snapshot=before,
                after_snapshot=after,
                reason=reason,
            ),
            session=session,
        )

    def _scope(self) -> str:
        if self._organization_id is None:
            raise DailyReportRepositoryError("organization scope is required")
        return self._organization_id


def _public_defrost_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if summary.get("status") == "available":
        return {
            "status": "available",
            "duration_seconds": summary.get("duration_seconds"),
        }
    return {
        "status": "unavailable",
        "reason": summary.get("reason", "evidence_unavailable"),
    }


def _interval_evidence_complete(summary: dict[str, Any]) -> bool:
    requested = float(summary.get("requested_seconds") or 0.0)
    observed = float(summary.get("observed_seconds") or 0.0)
    source_gap = float(summary.get("source_gap_seconds") or 0.0)
    breaks = int(summary.get("continuity_breaks") or 0)
    if requested <= 0 or observed <= 0 or source_gap <= 0 or breaks > 0:
        return False
    return max(0.0, requested - observed) <= source_gap


def _identity_filters(identity: TelemetryIdentity) -> tuple[Any, ...]:
    return (
        TelemetrySample.node_id == identity.node_id,
        TelemetrySample.equipment_id == identity.equipment_id,
        TelemetrySample.channel_id == identity.channel_id,
        TelemetrySample.metric == identity.metric,
    )


def _telemetry_point(row: TelemetrySample) -> TelemetryPoint:
    return TelemetryPoint(
        captured_at=as_utc(row.captured_at),
        value=float(row.value) if row.value is not None else None,
        quality=row.quality,
        event_id=row.event_id,
    )


def _profile_snapshot(profile: RefrigerationDailyReportProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "organization_id": profile.organization_id,
        "equipment_id": profile.equipment_id,
        "name": profile.name,
        "enabled": profile.enabled,
        "timezone": profile.timezone,
        "report_hour": profile.report_hour,
        "report_minute": profile.report_minute,
        "weekdays": list(profile.weekdays),
        "analysis_window_minutes": profile.analysis_window_minutes,
        "m_packet_channels": list(profile.m_packet_channels),
        "temperature_min_c": profile.temperature_min_c,
        "temperature_max_c": profile.temperature_max_c,
        "energy_source": profile.energy_source,
        "version": profile.version,
    }


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized
