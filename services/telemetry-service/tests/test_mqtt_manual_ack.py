from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.db import Database
from app.durable_spool import DurableIngestionSpool
from app.ingestion import TelemetryIngestor
from app.mqtt_consumer import MqttConsumer
from app.state import RuntimeState


class AckClient:
    def __init__(self) -> None:
        self.acks: list[tuple[int, int]] = []

    def ack(self, mid: int, qos: int) -> int:
        self.acks.append((mid, qos))
        return 0


def payload() -> bytes:
    return json.dumps(
        {
            "event_id": str(uuid4()),
            "node_id": "edge-01",
            "captured_at": datetime.now(UTC).isoformat(),
            "metric": "temperature",
            "value": 4.2,
            "unit": "degC",
            "quality": "valid",
            "source": "dixell-xjp60d",
            "equipment_id": "XJP60D-106",
            "channel_id": "106-03",
            "alarm": None,
            "raw_value": 42,
            "raw_status": None,
        }
    ).encode()


def test_qos1_ack_is_sent_only_after_durable_stage(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    spool = DurableIngestionSpool(
        tmp_path / "spool.db",
        max_records=100,
        max_bytes=1024 * 1024,
    )
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        durable_spool=spool,
    )
    consumer = MqttConsumer(
        Settings(
            mqtt_enabled=True,
            mqtt_node_registry_enforced=False,
            ingestion_spool_enabled=True,
        ),
        ingestor,
        state,
    )
    client = AckClient()
    message = SimpleNamespace(
        payload=payload(),
        topic="nexolab/telemetry",
        mid=17,
        qos=1,
    )

    consumer._on_message(client, None, message)  # noqa: SLF001

    assert client.acks == [(17, 1)]
    assert spool.stats().pending_records == 1
    snapshot = state.snapshot()
    assert snapshot["spool_staged_total"] == 1
    assert snapshot["mqtt_manual_ack_total"] == 1

    spool.close()
    database.dispose()


def test_invalid_qos1_payload_is_acked_after_dead_letter_stage(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    spool = DurableIngestionSpool(
        tmp_path / "spool.db",
        max_records=100,
        max_bytes=1024 * 1024,
    )
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        durable_spool=spool,
    )
    consumer = MqttConsumer(
        Settings(
            mqtt_enabled=True,
            mqtt_node_registry_enforced=False,
            ingestion_spool_enabled=True,
        ),
        ingestor,
        state,
    )
    client = AckClient()
    message = SimpleNamespace(
        payload=b"not-json",
        topic="nexolab/telemetry",
        mid=18,
        qos=1,
    )

    consumer._on_message(client, None, message)  # noqa: SLF001

    assert client.acks == [(18, 1)]
    record = spool.oldest_pending()
    assert record is not None
    assert record.work_type == "dead_letter"
    assert record.reason_code == "invalid_json"

    spool.close()
    database.dispose()
