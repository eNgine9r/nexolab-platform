from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class DeliveryState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    id: str
    organization_id: str
    profile_id: str
    equipment_id: str
    scheduled_for: datetime
    payload_sha256: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    text: str
    button_url: str
