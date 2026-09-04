from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from app.domain import ReportSnapshot
from app.http_transport import HttpResponse


ORG_ID = "00000000-0000-0000-0000-000000000001"


def sample_snapshot(*, snapshot_id: str = "snapshot-1", status: str = "normal") -> ReportSnapshot:
    payload: dict[str, Any] = {
        "schema": "nexolab.daily-refrigeration-report.v1",
        "identity": {"equipment_name": "Cool jet", "equipment_code": "CJ-01"},
        "report": {
            "timezone": "Europe/Kyiv",
            "scheduled_for": "2026-09-02T04:50:00+00:00",
            "analysis_window_minutes": 720,
            "status": status,
        },
        "m_packets": {
            "minimum_c": 0.0,
            "maximum_c": 11.0,
            "valid_channels": 48,
            "configured_channels": 48,
        },
        "refrigeration_circuit": {
            "evaporation_saturation_temperature": {"status": "unavailable", "reason": "not_implemented"},
            "superheat": {"status": "unavailable", "reason": "not_implemented"},
            "condensation_saturation_temperature": {"status": "unavailable", "reason": "not_implemented"},
            "subcooling": {"status": "unavailable", "reason": "not_implemented"},
        },
        "compressor": {"status": "available", "duty_percent": 0.0},
        "energy": {"status": "available", "interval_kwh": 0.0},
        "defrost": {"status": "available", "duration_seconds": 0.0},
        "alerts": {"active_count": 0, "recent_count": 0, "truncated": False, "items": []},
        "quality": {"status": "complete", "reasons": []},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ReportSnapshot(
        id=snapshot_id,
        organization_id=ORG_ID,
        profile_id="profile-1",
        equipment_id="equipment-1",
        scheduled_for=datetime(2026, 9, 2, 4, 50, tzinfo=UTC),
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
        payload=payload,
    )


def http_response(status: int, payload: object, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(
        status=status,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers or {},
    )
