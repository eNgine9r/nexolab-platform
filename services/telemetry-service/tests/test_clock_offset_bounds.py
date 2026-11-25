"""#1753: node clock offsets beyond the INTEGER column range must saturate, not fail ingestion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.nodes.domain import (
    CLOCK_OFFSET_MS_LIMIT,
    ClockStatus,
    bounded_clock_offset_ms,
    classify_clock_offset,
)

OBSERVED = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def test_normal_offsets_are_exact_rounded_milliseconds() -> None:
    assert bounded_clock_offset_ms(OBSERVED + timedelta(milliseconds=1500.4), OBSERVED) == 1500
    assert bounded_clock_offset_ms(OBSERVED - timedelta(hours=1, minutes=37), OBSERVED) == -5_820_000


def test_offsets_beyond_int32_saturate_both_ways() -> None:
    assert bounded_clock_offset_ms(datetime(1970, 1, 1, tzinfo=UTC), OBSERVED) == -CLOCK_OFFSET_MS_LIMIT
    assert bounded_clock_offset_ms(OBSERVED - timedelta(days=26), OBSERVED) == -CLOCK_OFFSET_MS_LIMIT
    assert bounded_clock_offset_ms(OBSERVED + timedelta(days=400), OBSERVED) == CLOCK_OFFSET_MS_LIMIT
    assert CLOCK_OFFSET_MS_LIMIT == 2**31 - 1


def test_saturated_offset_is_always_critical() -> None:
    offset = bounded_clock_offset_ms(datetime(1970, 1, 1, tzinfo=UTC), OBSERVED)
    assert classify_clock_offset(offset, warning_ms=5_000, critical_ms=60_000) is ClockStatus.CRITICAL
    assert classify_clock_offset(offset, warning_ms=1, critical_ms=CLOCK_OFFSET_MS_LIMIT) is ClockStatus.CRITICAL


def test_every_offset_write_site_uses_the_bounded_helper() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "nodes"
    for name in ("ingress.py", "repository.py", "stream_repository.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "bounded_clock_offset_ms(" in text, name
        assert ".total_seconds() * 1000)" not in text, name
