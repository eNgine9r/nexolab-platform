from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from app.config import Settings
from app.controlled_send import (
    APPROVAL_PHRASE,
    ControlledSendError,
    execute_controlled_send,
    parse_args,
)
from app.domain import DeliveryState, RenderedMessage
from app.outbox import DeliveryOutbox
from app.render import render_report
from app.telegram import TelegramApiError, TelegramSendResult
from tests.support import ORG_ID, sample_snapshot


NOW = datetime(2026, 9, 4, 5, 0, tzinfo=UTC)
TARGET_ID = "76957482-57c4-4daf-ac30-d8592847cfbd"
OTHER_ID = "11111111-2222-4333-8444-555555555555"
DESTINATION = "-1001234567890"
DIRECT_LINK = "https://t.me/nexolab_bot/nexolab?startapp=report_{snapshot_id}"


def controlled_settings(tmp_path, **overrides) -> Settings:
    values = {
        "telegram_enabled": False,
        "telegram_state_db_path": str(tmp_path / "outbox.db"),
        "telegram_destination_chat_id": DESTINATION,
        "telegram_mini_app_url_template": DIRECT_LINK,
        "nexolab_backend_auth_mode": "none",
        "nexolab_backend_unauthenticated_test_mode_enabled": True,
        "nexolab_backend_organization_id": ORG_ID,
    }
    values.update(overrides)
    return Settings(**values)


class ExactSource:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls: list[str] = []

    def get_snapshot(self, snapshot_id: str):
        self.calls.append(snapshot_id)
        return self.snapshot


class TelegramSink:
    def __init__(self, error: TelegramApiError | None = None):
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def send_message(self, *, chat_id: str, text: str, button_url: str):
        self.calls.append((chat_id, text, button_url))
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        return TelegramSendResult(message_id=701)


def target_snapshot():
    return sample_snapshot(snapshot_id=TARGET_ID)


def queued_message(snapshot) -> RenderedMessage:
    return render_report(
        snapshot,
        mini_app_url_template=DIRECT_LINK,
        max_chars=3900,
    )


def canonical_message(snapshot) -> RenderedMessage:
    return render_report(snapshot, mini_app_url_template=DIRECT_LINK)


def test_dry_run_fetches_exact_snapshot_without_send_or_outbox_mutation(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    source = ExactSource(target_snapshot())
    sink = TelegramSink()

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=source.snapshot.payload_sha256,
        dry_run=True,
        snapshot_client=source,
        telegram_client=sink,
        clock=lambda: NOW,
    )

    assert result.status == "dry_run_ready"
    assert result.delivery_state == "absent"
    assert source.calls == [TARGET_ID]
    assert sink.calls == []
    assert (tmp_path / "outbox.db").exists() is False


def test_wrong_payload_sha_fails_closed_before_outbox_or_send(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    source = ExactSource(target_snapshot())
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256="f" * 64,
            dry_run=True,
            snapshot_client=source,
            telegram_client=sink,
            clock=lambda: NOW,
        )

    assert caught.value.code == "snapshot_payload_sha256_mismatch"
    assert sink.calls == []
    assert (tmp_path / "outbox.db").exists() is False


def test_exact_send_does_not_claim_unrelated_pending_delivery(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    unrelated = sample_snapshot(snapshot_id=OTHER_ID)
    outbox.enqueue(unrelated, DESTINATION, queued_message(unrelated), now=NOW)
    target = target_snapshot()
    source = ExactSource(target)
    sink = TelegramSink()

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=False,
        approval=APPROVAL_PHRASE,
        snapshot_client=source,
        telegram_client=sink,
        outbox=outbox,
        clock=lambda: NOW,
    )

    assert result.status == "sent"
    assert result.telegram_message_id == 701
    assert len(sink.calls) == 1
    unrelated_record = outbox.get_by_snapshot(OTHER_ID, DESTINATION)
    target_record = outbox.get_by_snapshot(TARGET_ID, DESTINATION)
    assert unrelated_record is not None
    assert unrelated_record.state is DeliveryState.PENDING
    assert unrelated_record.attempts == 0
    assert target_record is not None
    assert target_record.state is DeliveryState.SENT
    assert target_record.attempts == 1


def test_already_sent_exact_snapshot_is_idempotent_noop(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    target = target_snapshot()
    created, _ = outbox.enqueue(
        target,
        DESTINATION,
        queued_message(target),
        now=NOW,
    )
    claimed = outbox.claim_exact(TARGET_ID, DESTINATION, now=NOW)
    assert claimed.id == created.id
    outbox.mark_sent(claimed.id, telegram_message_id=599, now=NOW)
    sink = TelegramSink()

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=False,
        approval=APPROVAL_PHRASE,
        snapshot_client=ExactSource(target),
        telegram_client=sink,
        outbox=outbox,
        clock=lambda: NOW,
    )

    assert result.status == "already_sent"
    assert result.telegram_message_id == 599
    assert sink.calls == []


def test_exact_sending_state_fails_closed_without_second_api_call(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    target = target_snapshot()
    outbox.enqueue(target, DESTINATION, queued_message(target), now=NOW)
    outbox.claim_exact(TARGET_ID, DESTINATION, now=NOW)
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=False,
            approval=APPROVAL_PHRASE,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            outbox=outbox,
            clock=lambda: NOW,
        )

    assert caught.value.code == "delivery_state_sending_not_sendable"
    assert sink.calls == []


def test_telegram_failure_is_terminal_and_not_automatically_retried(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    target = target_snapshot()
    sink = TelegramSink(TelegramApiError("telegram_server_error", retryable=True))

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=False,
        approval=APPROVAL_PHRASE,
        snapshot_client=ExactSource(target),
        telegram_client=sink,
        outbox=outbox,
        clock=lambda: NOW,
    )

    assert result.status == "failed"
    assert result.error_code == "telegram_server_error"
    assert len(sink.calls) == 1
    record = outbox.get_by_snapshot(TARGET_ID, DESTINATION)
    assert record is not None
    assert record.state is DeliveryState.FAILED
    assert record.attempts == 1
    assert record.duplicate_risk is True

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=False,
            approval=APPROVAL_PHRASE,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            outbox=outbox,
            clock=lambda: NOW,
        )

    assert caught.value.code == "delivery_duplicate_risk_requires_manual_resolution"
    assert len(sink.calls) == 1


def test_approval_is_required_before_fetch_or_send(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    source = ExactSource(target_snapshot())
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=source.snapshot.payload_sha256,
            dry_run=False,
            snapshot_client=source,
            telegram_client=sink,
            clock=lambda: NOW,
        )

    assert caught.value.code == "single_send_approval_required"
    assert source.calls == []
    assert sink.calls == []


def test_sanitized_result_contains_no_destination_or_rendered_message(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    target = target_snapshot()
    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=True,
        snapshot_client=ExactSource(target),
        clock=lambda: NOW,
    )

    payload = result.sanitized()
    encoded = json.dumps(payload, sort_keys=True)
    assert set(payload) == {
        "status",
        "snapshot_id",
        "payload_sha256",
        "delivery_state",
        "duplicate_risk",
    }
    assert DESTINATION not in encoded
    assert "queued report" not in encoded
    assert DIRECT_LINK not in encoded


def test_cli_modes_are_mutually_exclusive_and_ack_is_literal() -> None:
    digest = "a" * 64
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--snapshot-id",
                TARGET_ID,
                "--expected-payload-sha256",
                digest,
                "--dry-run",
                "--approve-single-send",
                APPROVAL_PHRASE,
            ]
        )
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--snapshot-id",
                TARGET_ID,
                "--expected-payload-sha256",
                digest,
                "--approve-single-send",
                "NOT_APPROVED",
            ]
        )


def test_dry_run_preserves_existing_pending_record(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    target = target_snapshot()
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    before, _ = outbox.enqueue(
        target,
        DESTINATION,
        canonical_message(target),
        now=NOW,
    )

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=True,
        snapshot_client=ExactSource(target),
        clock=lambda: NOW,
    )
    after = outbox.get_by_snapshot(TARGET_ID, DESTINATION)

    assert result.status == "dry_run_ready"
    assert result.delivery_state == DeliveryState.PENDING.value
    assert after == before
    assert after is not None and after.attempts == 0


def test_snapshot_organization_mismatch_fails_before_outbox_or_send(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    target = sample_snapshot(snapshot_id=TARGET_ID)
    target = target.__class__(
        id=target.id,
        organization_id="22222222-2222-4222-8222-222222222222",
        profile_id=target.profile_id,
        equipment_id=target.equipment_id,
        scheduled_for=target.scheduled_for,
        payload_sha256=target.payload_sha256,
        payload=target.payload,
    )
    source = ExactSource(target)
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=True,
            snapshot_client=source,
            telegram_client=sink,
            clock=lambda: NOW,
        )

    assert caught.value.code == "snapshot_organization_mismatch"
    assert sink.calls == []
    assert (tmp_path / "outbox.db").exists() is False


def test_persistent_delivery_enabled_blocks_before_fetch_or_send(tmp_path) -> None:
    settings = controlled_settings(tmp_path, telegram_enabled=True)
    source = ExactSource(target_snapshot())
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=source.snapshot.payload_sha256,
            dry_run=True,
            snapshot_client=source,
            telegram_client=sink,
            clock=lambda: NOW,
        )

    assert caught.value.code == "persistent_delivery_must_remain_disabled"
    assert source.calls == []
    assert sink.calls == []


def test_nonretryable_telegram_failure_is_terminal_without_second_call(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    target = target_snapshot()
    sink = TelegramSink(TelegramApiError("telegram_http_403", retryable=False))

    result = execute_controlled_send(
        settings,
        snapshot_id=TARGET_ID,
        expected_payload_sha256=target.payload_sha256,
        dry_run=False,
        approval=APPROVAL_PHRASE,
        snapshot_client=ExactSource(target),
        telegram_client=sink,
        outbox=outbox,
        clock=lambda: NOW,
    )

    assert result.status == "failed"
    assert result.delivery_state == DeliveryState.FAILED.value
    assert result.duplicate_risk is False
    assert len(sink.calls) == 1

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=False,
            approval=APPROVAL_PHRASE,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            outbox=outbox,
            clock=lambda: NOW,
        )

    assert caught.value.code == "delivery_state_failed_not_sendable"
    assert len(sink.calls) == 1


def test_retry_wait_state_fails_closed_for_controlled_send(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    target = target_snapshot()
    outbox.enqueue(target, DESTINATION, queued_message(target), now=NOW)
    claimed = outbox.claim_exact(TARGET_ID, DESTINATION, now=NOW)
    outbox.mark_retry(
        claimed.id,
        delay=timedelta(seconds=30),
        error_code="telegram_network_error",
        now=NOW,
    )
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=False,
            approval=APPROVAL_PHRASE,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            outbox=outbox,
            clock=lambda: NOW,
        )

    assert caught.value.code == "delivery_state_retry_wait_not_sendable"
    assert sink.calls == []
    record = outbox.get_by_snapshot(TARGET_ID, DESTINATION)
    assert record is not None
    assert record.state is DeliveryState.RETRY_WAIT
    assert record.attempts == 1


def test_payload_field_digest_must_match_actual_canonical_payload(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    target = target_snapshot()
    target.payload["report"]["status"] = "critical"
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=True,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            clock=lambda: NOW,
        )

    assert caught.value.code == "snapshot_payload_integrity_mismatch"
    assert sink.calls == []
    assert (tmp_path / "outbox.db").exists() is False


def test_existing_pending_render_mismatch_fails_closed(tmp_path) -> None:
    settings = controlled_settings(tmp_path)
    target = target_snapshot()
    outbox = DeliveryOutbox(settings.telegram_state_db_path)
    canonical = queued_message(target)
    stale = RenderedMessage(text="stale report", button_url=canonical.button_url)
    outbox.enqueue(target, DESTINATION, stale, now=NOW)
    sink = TelegramSink()

    with pytest.raises(ControlledSendError) as caught:
        execute_controlled_send(
            settings,
            snapshot_id=TARGET_ID,
            expected_payload_sha256=target.payload_sha256,
            dry_run=False,
            approval=APPROVAL_PHRASE,
            snapshot_client=ExactSource(target),
            telegram_client=sink,
            outbox=outbox,
            clock=lambda: NOW,
        )

    assert caught.value.code == "delivery_render_identity_mismatch"
    assert sink.calls == []
    record = outbox.get_by_snapshot(TARGET_ID, DESTINATION)
    assert record is not None and record.state is DeliveryState.PENDING
    assert record.attempts == 0
