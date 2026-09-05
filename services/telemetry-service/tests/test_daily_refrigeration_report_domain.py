from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.daily_reports.domain import (
    TelemetryPoint,
    calculate_compressor_runtime,
    calculate_state_duration,
    latest_due_report_date,
    resolve_report_window,
)


def point(base: datetime, seconds: int, value: float | None, quality: str = "valid") -> TelemetryPoint:
    return TelemetryPoint(
        captured_at=base + timedelta(seconds=seconds),
        value=value,
        quality=quality,
        event_id=f"event-{seconds}",
    )


def test_default_schedule_resolves_weekday_0750_and_previous_12_wall_clock_hours() -> None:
    window = resolve_report_window(date(2026, 9, 2))

    assert window.scheduled_local.isoformat() == "2026-09-02T07:50:00+03:00"
    assert window.window_end == datetime(2026, 9, 2, 4, 50, tzinfo=UTC)
    assert window.window_start == datetime(2026, 9, 1, 16, 50, tzinfo=UTC)


def test_dst_transition_preserves_local_1950_to_0750_contract() -> None:
    spring = resolve_report_window(date(2026, 3, 29))
    fall = resolve_report_window(date(2026, 10, 25))

    assert spring.scheduled_local.isoformat() == "2026-03-29T07:50:00+03:00"
    assert spring.window_start.astimezone(spring.scheduled_local.tzinfo).strftime("%H:%M") == "19:50"
    assert (spring.window_end - spring.window_start).total_seconds() == 11 * 3600

    assert fall.scheduled_local.isoformat() == "2026-10-25T07:50:00+02:00"
    assert fall.window_start.astimezone(fall.scheduled_local.tzinfo).strftime("%H:%M") == "19:50"
    assert (fall.window_end - fall.window_start).total_seconds() == 13 * 3600


def test_latest_due_date_skips_weekends_and_waits_until_0750() -> None:
    before_monday_report = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)  # 07:00 Kyiv
    after_monday_report = datetime(2026, 9, 7, 5, 0, tzinfo=UTC)  # 08:00 Kyiv

    assert latest_due_report_date(before_monday_report) == date(2026, 9, 4)
    assert latest_due_report_date(after_monday_report) == date(2026, 9, 7)


def test_compressor_runtime_matches_accepted_time_weighted_semantics() -> None:
    base = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
    result = calculate_compressor_runtime(
        [point(base, 0, 4500), point(base, 10, 0), point(base, 70, 0)],
        window_start=base,
        window_end=base + timedelta(minutes=10),
    )

    assert result.duty_percent == pytest.approx((10 / 70) * 100)
    assert result.running_seconds == 10
    assert result.observed_seconds == 70


def test_compressor_runtime_excludes_invalid_and_continuity_gap_evidence() -> None:
    base = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
    result = calculate_compressor_runtime(
        [
            point(base, 0, 4500),
            point(base, 30, None, "communication_error"),
            point(base, 60, 0),
            point(base, 90, 0),
            point(base, 300, 4500),
        ],
        window_start=base,
        window_end=base + timedelta(minutes=6),
    )

    assert result.running_seconds == 0
    assert result.observed_seconds == 30
    assert result.continuity_breaks == 3


def test_defrost_duration_counts_only_verified_defrost_state_three() -> None:
    base = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)
    result = calculate_state_duration(
        [
            point(base, 0, 2),
            point(base, 60, 3),
            point(base, 120, 3),
            point(base, 180, 4),
            point(base, 240, 1),
        ],
        window_start=base,
        window_end=base + timedelta(minutes=4),
        active_values=frozenset({3}),
    )

    assert result.status == "available"
    assert result.duration_seconds == 120
    assert result.observed_seconds == 240


def test_malformed_or_naive_schedule_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_due_report_date(datetime(2026, 9, 2, 7, 50))
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        resolve_report_window(date(2026, 9, 2), timezone="Mars/Lab")
