from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import math
import statistics
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAILY_REPORT_SCHEMA = "nexolab.daily-refrigeration-report.v1"
DEFAULT_TIMEZONE = "Europe/Kyiv"
DEFAULT_REPORT_HOUR = 7
DEFAULT_REPORT_MINUTE = 50
DEFAULT_WEEKDAYS = (0, 1, 2, 3, 4)
DEFAULT_ANALYSIS_WINDOW_MINUTES = 720
DEFAULT_SOURCE_GAP_SECONDS = 90.0
SOURCE_GAP_MULTIPLIER = 3.0


@dataclass(frozen=True, slots=True)
class ReportWindow:
    local_report_date: date
    timezone: str
    scheduled_local: datetime
    scheduled_for: datetime
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class TelemetryPoint:
    captured_at: datetime
    value: float | None
    quality: str
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class CompressorRuntimeResult:
    status: str
    duty_percent: float | None
    coverage_percent: float
    running_seconds: float
    observed_seconds: float
    requested_seconds: float
    continuity_breaks: int
    source_gap_seconds: float


@dataclass(frozen=True, slots=True)
class StateDurationResult:
    status: str
    duration_seconds: float | None
    observed_seconds: float
    coverage_percent: float
    continuity_breaks: int
    source_gap_seconds: float


def validate_timezone(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA timezone: {normalized}") from error
    return normalized


def validate_weekdays(values: Iterable[int]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized:
        raise ValueError("weekdays must contain at least one weekday")
    if any(value < 0 or value > 6 for value in normalized):
        raise ValueError("weekdays must contain integers from 0 through 6")
    return normalized


def resolve_report_window(
    local_report_date: date,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    report_hour: int = DEFAULT_REPORT_HOUR,
    report_minute: int = DEFAULT_REPORT_MINUTE,
    analysis_window_minutes: int = DEFAULT_ANALYSIS_WINDOW_MINUTES,
) -> ReportWindow:
    zone_name = validate_timezone(timezone)
    if not 0 <= report_hour <= 23 or not 0 <= report_minute <= 59:
        raise ValueError("report time is outside the valid clock range")
    if analysis_window_minutes <= 0:
        raise ValueError("analysis_window_minutes must be positive")
    zone = ZoneInfo(zone_name)
    scheduled_local = datetime.combine(
        local_report_date,
        time(report_hour, report_minute),
        tzinfo=zone,
    )
    window_start_local = scheduled_local - timedelta(minutes=analysis_window_minutes)
    return ReportWindow(
        local_report_date=local_report_date,
        timezone=zone_name,
        scheduled_local=scheduled_local,
        scheduled_for=scheduled_local.astimezone(UTC),
        window_start=window_start_local.astimezone(UTC),
        window_end=scheduled_local.astimezone(UTC),
    )


def latest_due_report_date(
    now: datetime,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    report_hour: int = DEFAULT_REPORT_HOUR,
    report_minute: int = DEFAULT_REPORT_MINUTE,
    weekdays: Sequence[int] = DEFAULT_WEEKDAYS,
) -> date | None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    zone_name = validate_timezone(timezone)
    allowed = validate_weekdays(weekdays)
    local_now = now.astimezone(ZoneInfo(zone_name))
    for days_back in range(8):
        candidate = local_now.date() - timedelta(days=days_back)
        if candidate.weekday() not in allowed:
            continue
        scheduled = datetime.combine(
            candidate,
            time(report_hour, report_minute),
            tzinfo=ZoneInfo(zone_name),
        )
        if scheduled <= local_now:
            return candidate
    return None


def next_scheduled_at(
    now: datetime,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    report_hour: int = DEFAULT_REPORT_HOUR,
    report_minute: int = DEFAULT_REPORT_MINUTE,
    weekdays: Sequence[int] = DEFAULT_WEEKDAYS,
) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    zone_name = validate_timezone(timezone)
    allowed = validate_weekdays(weekdays)
    zone = ZoneInfo(zone_name)
    local_now = now.astimezone(zone)
    for days_ahead in range(8):
        candidate = local_now.date() + timedelta(days=days_ahead)
        if candidate.weekday() not in allowed:
            continue
        scheduled = datetime.combine(
            candidate,
            time(report_hour, report_minute),
            tzinfo=zone,
        )
        if scheduled > local_now:
            return scheduled.astimezone(UTC)
    raise ValueError("unable to resolve the next scheduled report")


def derive_source_gap_seconds(
    points: Sequence[TelemetryPoint],
    minimum_seconds: float = DEFAULT_SOURCE_GAP_SECONDS,
) -> float:
    if not math.isfinite(minimum_seconds) or minimum_seconds <= 0:
        raise ValueError("minimum_seconds must be positive and finite")
    timestamps = sorted({_timestamp(point.captured_at) for point in points})
    deltas = sorted(
        right - left
        for left, right in zip(timestamps, timestamps[1:], strict=False)
        if right > left
    )
    if len(deltas) < 2:
        return minimum_seconds
    return max(minimum_seconds, statistics.median(deltas) * SOURCE_GAP_MULTIPLIER)


def calculate_compressor_runtime(
    points: Sequence[TelemetryPoint],
    *,
    window_start: datetime,
    window_end: datetime,
) -> CompressorRuntimeResult:
    start = _timestamp(window_start)
    end = _timestamp(window_end)
    if end <= start:
        raise ValueError("compressor window must be a positive interval")
    ordered = _normalize_points(points, nonnegative=True)
    gap = derive_source_gap_seconds(ordered)
    running = 0.0
    observed = 0.0
    breaks = 0
    for current, following in zip(ordered, ordered[1:], strict=False):
        current_at = _timestamp(current.captured_at)
        next_at = _timestamp(following.captured_at)
        duration = next_at - current_at
        if duration <= 0:
            continue
        overlap = min(end, next_at) - max(start, current_at)
        if overlap <= 0:
            continue
        if duration > gap or not _valid_point(current, nonnegative=True) or not _valid_point(
            following,
            nonnegative=True,
        ):
            breaks += 1
            continue
        observed += overlap
        if current.value is not None and current.value > 0:
            running += overlap
    requested = end - start
    coverage = min(100.0, observed / requested * 100.0)
    return CompressorRuntimeResult(
        status="available" if observed > 0 else "unavailable",
        duty_percent=(running / observed * 100.0 if observed > 0 else None),
        coverage_percent=coverage,
        running_seconds=running,
        observed_seconds=observed,
        requested_seconds=requested,
        continuity_breaks=breaks,
        source_gap_seconds=gap,
    )


def calculate_state_duration(
    points: Sequence[TelemetryPoint],
    *,
    window_start: datetime,
    window_end: datetime,
    active_values: frozenset[int],
) -> StateDurationResult:
    start = _timestamp(window_start)
    end = _timestamp(window_end)
    if end <= start:
        raise ValueError("state-duration window must be a positive interval")
    ordered = _normalize_points(points, nonnegative=True)
    gap = derive_source_gap_seconds(ordered)
    active = 0.0
    observed = 0.0
    breaks = 0
    for current, following in zip(ordered, ordered[1:], strict=False):
        current_at = _timestamp(current.captured_at)
        next_at = _timestamp(following.captured_at)
        duration = next_at - current_at
        if duration <= 0:
            continue
        overlap = min(end, next_at) - max(start, current_at)
        if overlap <= 0:
            continue
        if duration > gap or not _valid_point(current, nonnegative=True) or not _valid_point(
            following,
            nonnegative=True,
        ):
            breaks += 1
            continue
        observed += overlap
        if current.value is not None and int(current.value) in active_values:
            active += overlap
    requested = end - start
    return StateDurationResult(
        status="available" if observed > 0 else "unavailable",
        duration_seconds=(active if observed > 0 else None),
        observed_seconds=observed,
        coverage_percent=min(100.0, observed / requested * 100.0),
        continuity_breaks=breaks,
        source_gap_seconds=gap,
    )


def _normalize_points(
    points: Sequence[TelemetryPoint],
    *,
    nonnegative: bool,
) -> list[TelemetryPoint]:
    by_timestamp: dict[float, TelemetryPoint] = {}
    for point in sorted(points, key=lambda item: (_timestamp(item.captured_at), item.event_id)):
        timestamp = _timestamp(point.captured_at)
        value = point.value
        valid = (
            point.quality == "valid"
            and value is not None
            and math.isfinite(value)
            and (not nonnegative or value >= 0)
        )
        by_timestamp[timestamp] = TelemetryPoint(
            captured_at=point.captured_at,
            value=value if valid else None,
            quality=point.quality if valid else "invalid",
            event_id=point.event_id,
        )
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _valid_point(point: TelemetryPoint, *, nonnegative: bool) -> bool:
    return (
        point.quality == "valid"
        and point.value is not None
        and math.isfinite(point.value)
        and (not nonnegative or point.value >= 0)
    )


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("telemetry timestamps must be timezone-aware")
    return value.astimezone(UTC).timestamp()
