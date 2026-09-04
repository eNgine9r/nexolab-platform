from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Callable, Protocol, Sequence
from uuid import UUID

from app.backend import BackendError, build_snapshot_client
from app.config import Settings, read_secret_file, validate_enabled_configuration
from app.domain import DeliveryState, RenderedMessage, ReportSnapshot
from app.outbox import DeliveryOutbox, DeliveryOutboxError, DeliveryRecord
from app.render import render_report
from app.telegram import TelegramApiError, TelegramClient, TelegramSendResult


APPROVAL_PHRASE = "SEND_EXACT_SNAPSHOT_ONCE"


class ControlledSendError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ExactSnapshotSource(Protocol):
    def get_snapshot(self, snapshot_id: str) -> ReportSnapshot: ...


class TelegramSink(Protocol):
    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        button_url: str,
    ) -> TelegramSendResult: ...


@dataclass(frozen=True, slots=True)
class ControlledSendResult:
    status: str
    snapshot_id: str
    payload_sha256: str
    delivery_state: str
    telegram_message_id: int | None = None
    duplicate_risk: bool = False
    error_code: str | None = None

    def sanitized(self) -> dict[str, object]:
        result: dict[str, object] = {
            "status": self.status,
            "snapshot_id": self.snapshot_id,
            "payload_sha256": self.payload_sha256,
            "delivery_state": self.delivery_state,
            "duplicate_risk": self.duplicate_risk,
        }
        if self.telegram_message_id is not None:
            result["telegram_message_id"] = self.telegram_message_id
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


def execute_controlled_send(
    settings: Settings,
    *,
    snapshot_id: str,
    expected_payload_sha256: str,
    dry_run: bool,
    approval: str | None = None,
    snapshot_client: ExactSnapshotSource | None = None,
    telegram_client: TelegramSink | None = None,
    outbox: DeliveryOutbox | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ControlledSendResult:
    validate_enabled_configuration(settings)
    if settings.telegram_enabled:
        raise ControlledSendError("persistent_delivery_must_remain_disabled")
    if dry_run:
        if approval is not None:
            raise ControlledSendError("dry_run_cannot_include_send_approval")
    elif approval != APPROVAL_PHRASE:
        raise ControlledSendError("single_send_approval_required")

    normalized_snapshot_id = _snapshot_id(snapshot_id)
    expected_digest = _digest(expected_payload_sha256)
    destination = settings.telegram_destination_chat_id
    template = settings.telegram_mini_app_url_template
    assert destination is not None
    assert template is not None

    source = snapshot_client or build_snapshot_client(settings)
    snapshot = source.get_snapshot(normalized_snapshot_id)
    _verify_snapshot(settings, snapshot, normalized_snapshot_id, expected_digest)
    rendered = render_report(
        snapshot,
        mini_app_url_template=template,
        max_chars=settings.telegram_message_max_chars,
    )

    existing = _existing_delivery(
        settings,
        normalized_snapshot_id,
        destination,
        outbox,
    )
    if existing is not None:
        _verify_delivery_identity(existing, expected_digest)
        if existing.state is DeliveryState.SENT:
            return _result_from_record("already_sent", snapshot, existing)
        _ensure_sendable(existing)
        _verify_delivery_render(existing, rendered)

    if dry_run:
        state = DeliveryState.PENDING.value if existing is not None else "absent"
        return ControlledSendResult(
            status="dry_run_ready",
            snapshot_id=snapshot.id,
            payload_sha256=snapshot.payload_sha256,
            delivery_state=state,
            duplicate_risk=False,
        )

    sink = telegram_client or _telegram_client(settings)
    delivery_outbox = outbox or DeliveryOutbox(settings.telegram_state_db_path)
    current = delivery_outbox.get_by_snapshot(normalized_snapshot_id, destination)
    if current is None:
        current, _ = delivery_outbox.enqueue(
            snapshot,
            destination,
            rendered,
            now=_now(clock),
        )
    else:
        _verify_delivery_identity(current, expected_digest)
    if current.state is DeliveryState.SENT:
        return _result_from_record("already_sent", snapshot, current)
    _ensure_sendable(current)
    _verify_delivery_render(current, rendered)

    claimed = delivery_outbox.claim_exact(
        normalized_snapshot_id,
        destination,
        now=_now(clock),
    )
    try:
        sent = sink.send_message(
            chat_id=destination,
            text=claimed.text,
            button_url=claimed.button_url,
        )
    except TelegramApiError as error:
        failed = delivery_outbox.mark_failed(
            claimed.id,
            error_code=error.code,
            duplicate_risk=error.retryable,
            now=_now(clock),
        )
        return ControlledSendResult(
            status="failed",
            snapshot_id=snapshot.id,
            payload_sha256=snapshot.payload_sha256,
            delivery_state=failed.state.value,
            duplicate_risk=failed.duplicate_risk,
            error_code=error.code,
        )

    committed = delivery_outbox.mark_sent(
        claimed.id,
        telegram_message_id=sent.message_id,
        now=_now(clock),
    )
    return _result_from_record("sent", snapshot, committed)


def _existing_delivery(
    settings: Settings,
    snapshot_id: str,
    destination: str,
    outbox: DeliveryOutbox | None,
) -> DeliveryRecord | None:
    if outbox is not None:
        return outbox.get_by_snapshot(snapshot_id, destination)
    return DeliveryOutbox.inspect_existing(
        settings.telegram_state_db_path,
        snapshot_id,
        destination,
    )


def _verify_snapshot(
    settings: Settings,
    snapshot: ReportSnapshot,
    snapshot_id: str,
    expected_digest: str,
) -> None:
    if snapshot.id != snapshot_id:
        raise ControlledSendError("snapshot_identity_mismatch")
    if _organization(snapshot.organization_id) != _organization(
        settings.nexolab_backend_organization_id
    ):
        raise ControlledSendError("snapshot_organization_mismatch")
    if snapshot.payload_sha256.lower() != expected_digest:
        raise ControlledSendError("snapshot_payload_sha256_mismatch")
    if _payload_digest(snapshot.payload) != snapshot.payload_sha256.lower():
        raise ControlledSendError("snapshot_payload_integrity_mismatch")


def _verify_delivery_identity(record: DeliveryRecord, expected_digest: str) -> None:
    if record.snapshot_sha256.lower() != expected_digest:
        raise ControlledSendError("delivery_payload_identity_mismatch")


def _verify_delivery_render(record: DeliveryRecord, rendered: RenderedMessage) -> None:
    if record.text != rendered.text or record.button_url != rendered.button_url:
        raise ControlledSendError("delivery_render_identity_mismatch")


def _ensure_sendable(record: DeliveryRecord) -> None:
    if record.duplicate_risk:
        raise ControlledSendError("delivery_duplicate_risk_requires_manual_resolution")
    if record.state is not DeliveryState.PENDING:
        raise ControlledSendError(f"delivery_state_{record.state.value}_not_sendable")


def _result_from_record(
    status: str,
    snapshot: ReportSnapshot,
    record: DeliveryRecord,
) -> ControlledSendResult:
    return ControlledSendResult(
        status=status,
        snapshot_id=snapshot.id,
        payload_sha256=snapshot.payload_sha256,
        delivery_state=record.state.value,
        telegram_message_id=record.telegram_message_id,
        duplicate_risk=record.duplicate_risk,
    )


def _telegram_client(settings: Settings) -> TelegramClient:
    token = read_secret_file(settings.telegram_bot_token_file, label="Telegram bot token")
    return TelegramClient(
        settings.telegram_bot_api_base_url,
        token,
        timeout_seconds=settings.telegram_request_timeout_seconds,
    )


def _snapshot_id(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as error:
        raise ControlledSendError("snapshot_id_invalid") from error


def _organization(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as error:
        raise ControlledSendError("organization_id_invalid") from error


def _digest(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ControlledSendError("expected_payload_sha256_invalid")
    return normalized


def _payload_digest(payload: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        raise ControlledSendError("snapshot_payload_not_canonical_json") from error
    return hashlib.sha256(encoded).hexdigest()


def _now(clock: Callable[[], datetime] | None) -> datetime:
    value = clock() if clock is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ControlledSendError("clock_must_be_timezone_aware")
    return value.astimezone(UTC)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send at most one exact persisted NEXOLAB report to the configured Telegram group."
        ),
    )
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--expected-payload-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument(
        "--approve-single-send",
        metavar="ACK",
        choices=[APPROVAL_PHRASE],
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = execute_controlled_send(
            Settings(),
            snapshot_id=args.snapshot_id,
            expected_payload_sha256=args.expected_payload_sha256,
            dry_run=bool(args.dry_run),
            approval=args.approve_single_send,
        )
    except ControlledSendError as error:
        _emit_error(error.code)
        return 2
    except BackendError as error:
        _emit_error(error.code)
        return 2
    except DeliveryOutboxError:
        _emit_error("delivery_outbox_error")
        return 2
    except ValueError:
        _emit_error("configuration_invalid")
        return 2
    except Exception:
        _emit_error("controlled_send_internal_error")
        return 2
    print(json.dumps(result.sanitized(), sort_keys=True, separators=(",", ":")))
    return 3 if result.status == "failed" else 0


def _emit_error(code: str) -> None:
    print(json.dumps({"status": "error", "code": code[:96]}, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
