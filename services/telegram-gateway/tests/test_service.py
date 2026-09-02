from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.outbox import DeliveryOutbox
from app.service import GatewayRuntime, TelegramDeliveryWorker
from app.telegram import TelegramApiError, TelegramSendResult
from tests.support import ORG_ID, sample_snapshot


NOW = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)
DIRECT_LINK = "https://t.me/nexolab_bot/nexolab?startapp=report_{snapshot_id}"
DESTINATION = "-1001234567890"


class SnapshotSource:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = 0

    def list_snapshots(self, *, limit: int, offset: int = 0):
        self.calls += 1
        return list(self.snapshots[offset : offset + limit])


class TelegramSink:
    def __init__(self, errors=None):
        self.calls = []
        self.errors = list(errors or [])

    def send_message(self, *, chat_id: str, text: str, button_url: str):
        self.calls.append((chat_id, text, button_url))
        if self.errors:
            raise self.errors.pop(0)
        return TelegramSendResult(message_id=100 + len(self.calls))


def settings(tmp_path, **overrides) -> Settings:
    values = {
        "telegram_enabled": True,
        "telegram_state_db_path": str(tmp_path / "outbox.db"),
        "telegram_destination_chat_id": DESTINATION,
        "telegram_mini_app_url_template": DIRECT_LINK,
        "nexolab_backend_auth_mode": "none",
        "nexolab_backend_organization_id": ORG_ID,
        "telegram_retry_initial_seconds": 5,
        "telegram_retry_max_seconds": 60,
        "telegram_max_attempts": 3,
    }
    values.update(overrides)
    return Settings(**values)


def build_worker(tmp_path, source, sink, *, now=NOW, **overrides):
    config = settings(tmp_path, **overrides)
    runtime = GatewayRuntime(enabled=True)
    outbox = DeliveryOutbox(config.telegram_state_db_path)
    worker = TelegramDeliveryWorker(
        config,
        source,
        sink,
        outbox,
        runtime,
        clock=lambda: now,
    )
    return worker, outbox, runtime


def test_worker_sends_persisted_snapshot_once_across_restart(tmp_path) -> None:
    source = SnapshotSource([sample_snapshot()])
    first_sink = TelegramSink()
    worker, outbox, runtime = build_worker(tmp_path, source, first_sink)
    worker.run_once()
    assert len(first_sink.calls) == 1
    record = outbox.get_by_snapshot("snapshot-1", DESTINATION)
    assert record is not None and record.telegram_message_id == 101
    assert runtime.snapshot().last_send_at == NOW

    second_sink = TelegramSink()
    restarted, restarted_outbox, _ = build_worker(tmp_path, source, second_sink)
    restarted.run_once()
    assert second_sink.calls == []
    replay = restarted_outbox.get_by_snapshot("snapshot-1", DESTINATION)
    assert replay is not None and replay.telegram_message_id == 101


def test_retryable_failure_is_retained_without_mutating_snapshot(tmp_path) -> None:
    snapshot = sample_snapshot()
    original_payload = snapshot.payload.copy()
    error = TelegramApiError("telegram_server_error", retryable=True)
    sink = TelegramSink([error])
    worker, outbox, runtime = build_worker(tmp_path, SnapshotSource([snapshot]), sink)
    worker.run_once()
    record = outbox.get_by_snapshot(snapshot.id, DESTINATION)
    assert record is not None
    assert record.state.value == "retry_wait"
    assert record.attempts == 1
    assert record.available_at == NOW + timedelta(seconds=5)
    assert runtime.snapshot().last_error_code == "telegram_server_error"
    assert snapshot.payload == original_payload


def test_non_retryable_failure_becomes_failed(tmp_path) -> None:
    error = TelegramApiError("telegram_http_400", retryable=False)
    sink = TelegramSink([error])
    worker, outbox, _ = build_worker(tmp_path, SnapshotSource([sample_snapshot()]), sink)
    worker.run_once()
    record = outbox.get_by_snapshot("snapshot-1", DESTINATION)
    assert record is not None
    assert record.state.value == "failed"
    assert record.last_error_code == "telegram_http_400"


def test_worker_discovers_multiple_snapshot_pages(tmp_path) -> None:
    source = SnapshotSource([sample_snapshot(snapshot_id="snapshot-1"), sample_snapshot(snapshot_id="snapshot-2")])
    sink = TelegramSink()
    worker, outbox, _ = build_worker(
        tmp_path,
        source,
        sink,
        telegram_snapshot_page_size=1,
        telegram_snapshot_max_pages=3,
    )
    worker.run_once()
    assert source.calls == 3
    assert len(sink.calls) == 2
    assert outbox.get_by_snapshot("snapshot-1", DESTINATION) is not None
    assert outbox.get_by_snapshot("snapshot-2", DESTINATION) is not None
