from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.live_dashboard.export import LiveDashboardExportTimezoneError, _resolve_timezone


def test_legacy_kiev_timezone_uses_canonical_kyiv_rules() -> None:
    timezone = _resolve_timezone("Europe/Kiev")
    captured_at = datetime(2026, 8, 27, 7, 0, tzinfo=UTC)

    assert timezone.key == "Europe/Kyiv"
    assert captured_at.astimezone(timezone).utcoffset() == timedelta(hours=3)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(LiveDashboardExportTimezoneError):
        _resolve_timezone("Invalid/Timezone")
