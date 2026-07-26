from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.contracts import TelemetryEvent
from app.ingestion import (
    PostPersistProcessingError,
    TelemetryIngestor,
    TelemetryWork,
)
from app.state import RuntimeState


class ReplayDatabase:
    def __init__(self) -> None:
        self.persist_calls = 0

    def persist(self, event: TelemetryEvent, raw: dict) -> bool:
        del event, raw
        self.persist_calls += 1
        return self.persist_calls == 1


def test_post_persist_failure_replays_without_duplicate_live_publish() -> None:
    database = ReplayDatabase()
    state = RuntimeState()
    live_payloads: list[dict] = []
    processing_payloads: list[dict] = []

    def process(payload: dict) -> None:
        processing_payloads.append(payload)
        if len(processing_payloads) == 1:
            raise RuntimeError("temporary evaluator failure")

    ingestor = TelemetryIngestor(
        database=database,  # type: ignore[arg-type]
        state=state,
        queue_maxsize=4,
        on_persisted=live_payloads.append,
        after_persist=process,
    )
    event = TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=datetime(2026, 7, 26, 15, 0, tzinfo=UTC),
        metric="temperature.probe",
        value=9.0,
        unit="degC",
        quality="valid",
        source="post-persist-test",
        equipment_id="K106",
        channel_id="106-03",
    )
    work = TelemetryWork(event=event, raw=event.normalized_payload())

    with pytest.raises(PostPersistProcessingError):
        ingestor._persist(work)

    ingestor._persist(work)

    assert database.persist_calls == 2
    assert len(live_payloads) == 1
    assert len(processing_payloads) == 2
    assert processing_payloads[0]["event_id"] == str(event.event_id)
    assert processing_payloads[1]["event_id"] == str(event.event_id)
