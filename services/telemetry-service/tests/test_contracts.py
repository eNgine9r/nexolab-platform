from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from app.contracts import TelemetryEvent


def xjp_payload() -> dict[str, object]:
    return {
        "event_id": "b3b365a6-001d-488e-a064-c50c40388769",
        "node_id": "edge-01",
        "captured_at": "2026-07-23T08:25:29.225501+00:00",
        "metric": "temperature.probe",
        "value": 26.0,
        "unit": "degC",
        "quality": "valid",
        "source": "dixell-xjp60d",
        "equipment_id": "K106",
        "channel_id": "106-03",
        "alarm": "high",
        "raw_value": 260,
        "raw_status": 4354,
        "future_field": "preserved in raw payload",
    }


def test_current_xjp60d_payload_validates() -> None:
    event = TelemetryEvent.model_validate(xjp_payload())
    assert event.value == 26.0
    assert event.captured_at.tzinfo == UTC
    assert event.model_extra == {"future_field": "preserved in raw payload"}


def test_current_le01mp_payload_validates() -> None:
    payload = xjp_payload() | {
        "event_id": "56bb5d38-1c20-48c7-bfaf-8d3101da9e21",
        "metric": "electrical.voltage",
        "value": 227.3,
        "unit": "V",
        "source": "f-and-f-le-01mp",
        "equipment_id": "LE01MP-201",
        "channel_id": "201-voltage",
        "alarm": None,
        "raw_value": 2273,
        "raw_status": None,
    }
    event = TelemetryEvent.model_validate(payload)
    assert event.metric == "electrical.voltage"


def test_valid_quality_requires_value() -> None:
    payload = xjp_payload() | {"value": None}
    with pytest.raises(ValidationError):
        TelemetryEvent.model_validate(payload)


def test_non_valid_quality_may_have_null_value() -> None:
    payload = xjp_payload() | {
        "quality": "sensor_error",
        "value": None,
        "alarm": None,
    }
    event = TelemetryEvent.model_validate(payload)
    assert event.value is None
