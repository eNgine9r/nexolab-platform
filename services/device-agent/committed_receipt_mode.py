"""Edge committed-receipt mode behind ``DEVICE_AGENT_COMMITTED_RECEIPTS`` (#1762 slice 2).

Default ``disabled``: the Device Agent keeps the legacy outbox (rows are deleted
after the broker's MQTT QoS 1 PUBACK). Nothing in this module runs.

``enabled``: the outbox is a ``CommittedReceiptQueue``. A broker PUBACK never
deletes a row. A row is pruned only by a validated ``postgres_committed``
receipt that the ledger applies atomically (``apply_committed_receipt``).

Trust model. MQTT 3.1.1 does not tell a subscriber who published a message.
The only publisher authority is the installed broker ACL: only the central
receipt publisher identity may publish to ``nexolab/v1/+/+/receipts``, and
only this node's dedicated receipt identity may read its own receipt topic.
The operator states that ACL in configuration
(``DEVICE_AGENT_RECEIPT_BROKER_ACL=broker-enforced`` plus the central
publisher username). ``central_publisher_authorized`` passed to the ledger is
derived only from that validated configuration and from the message having
arrived on this dedicated subscriber's exact subscription. It never comes from
the receipt body or topic text.
"""

from __future__ import annotations

import bisect
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from durable_receipt_v1 import NODE_ID, ReceiptProtocolError

LOG = logging.getLogger("nexolab.device_agent.committed_receipts")

FLAG = "DEVICE_AGENT_COMMITTED_RECEIPTS"
BROKER_ACL_ATTESTATION = "broker-enforced"
CENTRAL_PUBLISHER_NAMESPACE = re.compile(
    r"^nexolab-central-receipts-[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$"
)
_IDENTITY_TOKEN = re.compile(r"^[!-~]{1,256}$")
MAX_REASON_KEYS = 32
FLUSH_BATCH_LIMIT = 100
CATCH_UP_WINDOW_LIMIT = 500
CATCH_UP_RATE_LIMIT = 1000.0


@dataclass(frozen=True)
class CommittedReceiptConfig:
    organization_id: str
    node_id: str
    username: str
    client_id: str
    password_file: Path
    central_publisher_username: str
    replay_after_seconds: float = 60.0
    replay_initial_retry_seconds: float = 5.0
    replay_max_retry_seconds: float = 300.0
    replay_min_interval_seconds: float = 0.2
    catch_up_window: int = 50
    catch_up_max_rows_per_second: float = 200.0

    @property
    def receipt_topic(self) -> str:
        return f"nexolab/v1/{self.organization_id}/{self.node_id}/receipts"

    @property
    def telemetry_topic(self) -> str:
        return f"nexolab/v1/{self.organization_id}/{self.node_id}/telemetry"


def _positive_seconds(
    values: Mapping[str, str],
    name: str,
    default: float,
    problems: list[str],
) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        problems.append(f"{name} must be a number of seconds")
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        problems.append(f"{name} must be a positive finite number of seconds")
        return default
    return parsed


def parse_committed_receipt_config(
    *,
    organization_id: str | None,
    node_id: str,
    mqtt_auth_required: bool,
    telemetry_username: str | None,
    telemetry_client_id: str,
    read_secret: Callable[..., str],
    environment: Mapping[str, str] | None = None,
) -> CommittedReceiptConfig | None:
    """Return ``None`` when disabled; otherwise a fully validated config.

    Raises ``ValueError`` naming only the setting names that are wrong. Secret
    values and identities are never put into the error text.
    """

    values = os.environ if environment is None else environment
    mode = values.get(FLAG, "disabled").strip().casefold() or "disabled"
    if mode == "disabled":
        return None
    if mode != "enabled":
        raise ValueError(f"{FLAG} must be disabled or enabled")

    problems: list[str] = []
    if organization_id is None:
        problems.append("NEXOLAB_ORGANIZATION_ID is required")
    else:
        try:
            canonical = str(uuid.UUID(organization_id))
        except (ValueError, AttributeError, TypeError):
            canonical = None
        if canonical != organization_id:
            problems.append("NEXOLAB_ORGANIZATION_ID must be a canonical lowercase UUID")
    if not values.get("NEXOLAB_NODE_ID", "").strip():
        problems.append("NEXOLAB_NODE_ID must be set explicitly")
    elif not NODE_ID.fullmatch(node_id):
        problems.append("NEXOLAB_NODE_ID is not a valid receipt node identity")
    if not mqtt_auth_required:
        problems.append("MQTT_AUTH_REQUIRED=true is required (org-scoped telemetry identity)")

    username = values.get("DEVICE_AGENT_RECEIPT_MQTT_USERNAME", "").strip()
    password_file_value = values.get("DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE", "").strip()
    default_client_id = (
        f"nexolab-{organization_id}-{node_id}-receipts" if organization_id else ""
    )
    client_id = (
        values.get("DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID", "").strip() or default_client_id
    )
    central_publisher = values.get("DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME", "").strip()
    attestation = values.get("DEVICE_AGENT_RECEIPT_BROKER_ACL", "").strip()

    if not username:
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_USERNAME is required")
    elif not _IDENTITY_TOKEN.fullmatch(username):
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_USERNAME must not contain whitespace")
    elif telemetry_username is not None and username == telemetry_username:
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_USERNAME must differ from MQTT_USERNAME")
    if not client_id or not _IDENTITY_TOKEN.fullmatch(client_id):
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID must be a non-empty token")
    elif client_id == telemetry_client_id:
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID must differ from MQTT_CLIENT_ID")
    if not password_file_value:
        problems.append("DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE is required")
    if not central_publisher:
        problems.append("DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME is required")
    elif not CENTRAL_PUBLISHER_NAMESPACE.fullmatch(central_publisher):
        problems.append(
            "DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME must use the dedicated "
            "nexolab-central-receipts-* namespace"
        )
    elif central_publisher in {username, telemetry_username}:
        problems.append(
            "DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME must differ from the Edge identities"
        )
    if attestation != BROKER_ACL_ATTESTATION:
        problems.append(
            f"DEVICE_AGENT_RECEIPT_BROKER_ACL must be {BROKER_ACL_ATTESTATION} "
            "(installed broker ACL restricts receipt publishing to the central identity)"
        )

    replay_after = _positive_seconds(
        values, "DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS", 60.0, problems
    )
    initial = _positive_seconds(
        values, "DEVICE_AGENT_RECEIPT_REPLAY_INITIAL_RETRY_SECONDS", 5.0, problems
    )
    maximum = _positive_seconds(
        values, "DEVICE_AGENT_RECEIPT_REPLAY_MAX_RETRY_SECONDS", 300.0, problems
    )
    min_interval = _positive_seconds(
        values, "DEVICE_AGENT_RECEIPT_REPLAY_MIN_INTERVAL_SECONDS", 0.2, problems
    )
    window_raw = values.get("DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW", "").strip()
    catch_up_window = 50
    if window_raw:
        try:
            catch_up_window = int(window_raw)
        except ValueError:
            catch_up_window = 0
        if not 1 <= catch_up_window <= CATCH_UP_WINDOW_LIMIT:
            problems.append(
                "DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW must be an integer from 1 to "
                f"{CATCH_UP_WINDOW_LIMIT}"
            )
            catch_up_window = 50
    catch_up_rate = _positive_seconds(
        values, "DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND", 200.0, problems
    )
    if catch_up_rate > CATCH_UP_RATE_LIMIT:
        problems.append(
            "DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND must be at most "
            f"{CATCH_UP_RATE_LIMIT:g}"
        )
    if maximum < initial:
        problems.append(
            "DEVICE_AGENT_RECEIPT_REPLAY_MAX_RETRY_SECONDS must be >= "
            "DEVICE_AGENT_RECEIPT_REPLAY_INITIAL_RETRY_SECONDS"
        )

    if not problems and password_file_value:
        try:
            read_secret(Path(password_file_value), label="Receipt MQTT password")
        except ValueError as exc:
            problems.append(str(exc))

    if problems:
        raise ValueError(
            f"{FLAG}=enabled is misconfigured: " + "; ".join(problems)
        )
    assert organization_id is not None
    return CommittedReceiptConfig(
        organization_id=organization_id,
        node_id=node_id,
        username=username,
        client_id=client_id,
        password_file=Path(password_file_value),
        central_publisher_username=central_publisher,
        replay_after_seconds=replay_after,
        replay_initial_retry_seconds=initial,
        replay_max_retry_seconds=maximum,
        replay_min_interval_seconds=min_interval,
        catch_up_window=catch_up_window,
        catch_up_max_rows_per_second=catch_up_rate,
    )


class CommittedReceiptRuntime:
    """Receipt subscriber, PUBACK-without-delete flush and bounded catch-up.

    * ``flush_pending`` sends each queued row once per process lifetime, in
      SQLite id order, and advances an in-memory cursor on PUBACK. It never
      deletes. After a restart the cursor starts at zero, so every retained row
      is sent once again (central deduplicates by ``event_id``).
    * ``replay_tick`` runs one step of the windowed catch-up
      (``CommittedReceiptCatchUp``, #1762 slice 4): pending rows first sent
      more than ``replay_after_seconds`` ago are re-published in FIFO windows,
      with at most ``catch_up_window`` rows in flight and at most
      ``catch_up_max_rows_per_second``. It pauses while telemetry is
      disconnected.
    * ``handle_receipt`` applies a receipt through the atomic ledger. A valid
      receipt prunes exactly the pending row it names (exact-row binding).
    """

    def __init__(
        self,
        config: CommittedReceiptConfig,
        queue: Any,
        *,
        receipt_client: Any,
        publish_client: Any,
        telemetry_connected: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        publish_timeout_seconds: float = 5.0,
    ) -> None:
        from receipt_replay import CommittedReceiptCatchUp

        self.config = config
        self.queue = queue
        self.receipt_client = receipt_client
        self.publish_client = publish_client
        self._telemetry_connected = telemetry_connected
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._publish_timeout = publish_timeout_seconds
        self._catch_up = CommittedReceiptCatchUp(
            queue,
            organization_id=config.organization_id,
            node_id=config.node_id,
            replay_after_seconds=config.replay_after_seconds,
            window=config.catch_up_window,
            max_rows_per_second=config.catch_up_max_rows_per_second,
            initial_retry_seconds=config.replay_initial_retry_seconds,
            max_retry_seconds=config.replay_max_retry_seconds,
        )
        # Trust is configuration-derived (validated broker ACL attestation and
        # central publisher identity), never message-derived.
        self._publisher_authorized = (
            CENTRAL_PUBLISHER_NAMESPACE.fullmatch(config.central_publisher_username)
            is not None
        )
        self._lock = threading.Lock()
        self._cursor = 0
        # (highest row id sent, monotonic time) per first-transmission flush,
        # ascending in row id; pruned below the outbox head.
        self._sent_batches: list[tuple[int, float]] = []
        self._receipt_connected = False
        self._subscribe_acknowledged = False
        self._applied_final_total = 0
        self._informational_total = 0
        self._rejected_total = 0
        self._rejected_by_reason: dict[str, int] = {}
        self._first_transmissions_total = 0
        self._replay_outcomes: dict[str, int] = {}
        self._replay_errors_total = 0
        self._head_blocked_reason: str | None = None
        self._head_problem: tuple[int, str] | None = None
        self._last_capacity: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

        receipt_client.on_connect = self._on_receipt_connect
        receipt_client.on_disconnect = self._on_receipt_disconnect
        receipt_client.on_subscribe = self._on_receipt_subscribe
        receipt_client.on_message = self._on_receipt_message

    # ------------------------------------------------------------------ MQTT
    def _on_receipt_connect(self, client: Any, userdata: Any, flags: Any,
                            reason_code: Any, properties: Any = None) -> None:
        connected = reason_code == 0
        with self._lock:
            self._receipt_connected = connected
            self._subscribe_acknowledged = False
        if connected:
            client.subscribe(self.config.receipt_topic, qos=1)
        LOG.info("Receipt subscriber connection result: %s", reason_code)

    def _on_receipt_disconnect(self, client: Any, userdata: Any, flags: Any = None,
                               reason_code: Any = None, properties: Any = None) -> None:
        with self._lock:
            self._receipt_connected = False
            self._subscribe_acknowledged = False
        LOG.warning("Receipt subscriber disconnected: %s", reason_code)

    def _on_receipt_subscribe(self, client: Any, userdata: Any, mid: Any,
                              reason_codes: Any = None, properties: Any = None) -> None:
        # SUBACK is not ACL proof (a denied subscription can still look
        # granted); it is reported only as a diagnostic.
        granted = False
        try:
            granted = bool(reason_codes) and all(
                int(getattr(code, "value", code)) < 128 for code in reason_codes
            )
        except (TypeError, ValueError):
            granted = False
        with self._lock:
            self._subscribe_acknowledged = granted

    def _on_receipt_message(self, client: Any, userdata: Any, message: Any) -> None:
        self.handle_receipt(str(message.topic), bytes(message.payload))

    # -------------------------------------------------------------- receipts
    def _reject(self, reason: str) -> str:
        with self._lock:
            self._rejected_total += 1
            key = reason if (
                reason in self._rejected_by_reason
                or len(self._rejected_by_reason) < MAX_REASON_KEYS
            ) else "other"
            self._rejected_by_reason[key] = self._rejected_by_reason.get(key, 0) + 1
        return "rejected"

    def handle_receipt(self, topic: str, payload: bytes) -> str:
        """Return ``pruned``, ``informational`` or ``rejected``. Never raises."""

        if topic != self.config.receipt_topic:
            return self._reject("unexpected_receipt_topic")
        try:
            decision = self.queue.apply_committed_receipt(
                payload,
                topic=topic,
                organization_id=self.config.organization_id,
                node_id=self.config.node_id,
                central_publisher_authorized=self._publisher_authorized,
                now=self._wall_clock(),
            )
        except ReceiptProtocolError as exc:
            return self._reject(str(exc) or "receipt_protocol_error")
        except sqlite3.Error:
            LOG.exception("Receipt ledger SQLite failure; row retained")
            return self._reject("sqlite_error")
        except Exception:  # noqa: BLE001 - never kill the MQTT network thread
            LOG.exception("Receipt handling failed; row retained")
            return self._reject("internal_error")
        if decision == "prune_allowed":
            with self._lock:
                self._applied_final_total += 1
            self._catch_up.note_progress()
            self._wake.set()
            return "pruned"
        with self._lock:
            self._informational_total += 1
        return "informational"

    # ----------------------------------------------------------------- flush
    def _publish_qos1(self, topic: str, payload: str) -> bool:
        import paho.mqtt.client as mqtt

        result = self.publish_client.publish(topic, payload, qos=1)
        result.wait_for_publish(timeout=self._publish_timeout)
        return result.rc == mqtt.MQTT_ERR_SUCCESS and result.is_published() is True

    def _publish_window(self, items: list[tuple[str, str]]) -> int:
        """Publish a window with QoS 1; return the PUBACKed leading count.

        All messages are handed to Paho first, then each PUBACK is awaited
        against one shared deadline. A PUBACK is broker acceptance only.
        """
        import paho.mqtt.client as mqtt

        pending = []
        for topic, payload in items:
            try:
                result = self.publish_client.publish(topic, payload, qos=1)
            except (RuntimeError, ValueError, OSError):
                break
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                break
            pending.append(result)
        deadline = self._monotonic_real() + self._publish_timeout
        acknowledged = 0
        for result in pending:
            try:
                result.wait_for_publish(
                    timeout=max(0.0, deadline - self._monotonic_real())
                )
            except (RuntimeError, ValueError, OSError):
                break
            if result.is_published() is not True:
                break
            acknowledged += 1
        return acknowledged

    @staticmethod
    def _monotonic_real() -> float:
        return time.monotonic()

    def flush_pending(self, on_puback: Callable[[], None] | None = None) -> bool:
        """Send never-sent rows in FIFO order. Return True when all were PUBACKed.

        Each row is sent at most once per process lifetime by this method; the
        bounded head replay is the only resend path.
        """

        with self._lock:
            start_cursor = self._cursor
        try:
            while True:
                with self._lock:
                    cursor = self._cursor
                rows = self.queue.pending_after(cursor, limit=FLUSH_BATCH_LIMIT)
                for record_id, topic, payload in rows:
                    try:
                        acknowledged = self._publish_qos1(topic, payload)
                    except (RuntimeError, ValueError, OSError) as exc:
                        LOG.warning("MQTT receipt-mode flush deferred: %s", exc)
                        return False
                    if not acknowledged:
                        LOG.warning(
                            "MQTT receipt-mode flush deferred: no QoS 1 acknowledgement"
                        )
                        return False
                    # PUBACK is broker acceptance only. The row stays until a
                    # postgres_committed receipt prunes it.
                    with self._lock:
                        self._cursor = max(self._cursor, record_id)
                        self._first_transmissions_total += 1
                    if on_puback is not None:
                        on_puback()
                if len(rows) < FLUSH_BATCH_LIMIT:
                    return True
        finally:
            with self._lock:
                if self._cursor > start_cursor:
                    self._sent_batches.append((self._cursor, self._monotonic()))

    def _sent_at(self, row_id: int) -> float | None:
        """When ``row_id`` was first sent in this process (read-only lookup)."""
        with self._lock:
            index = bisect.bisect_left(self._sent_batches, (row_id, float("-inf")))
            if index >= len(self._sent_batches):
                return None
            return self._sent_batches[index][1]

    def _forget_sent_below(self, head_row_id: int) -> None:
        """Drop first-transmission marks for rows already pruned."""
        with self._lock:
            index = bisect.bisect_left(
                self._sent_batches, (head_row_id, float("-inf"))
            )
            if index:
                del self._sent_batches[:index]

    # ---------------------------------------------------------------- replay
    def replay_tick(self) -> str:
        """One bounded catch-up step; never deletes, pauses while disconnected."""

        if not self._telemetry_connected():
            return self._count_replay("telemetry_disconnected")
        candidate = self.queue.oldest_receipt_replay_candidate()
        if candidate is None:
            with self._lock:
                self._head_blocked_reason = None
            return self._count_replay("empty")
        head_id, _event_id, topic, _payload = candidate
        self._forget_sent_below(head_id)
        if topic != self.config.telemetry_topic:
            # A foreign row is never resent or pruned by a receipt. It no
            # longer blocks scoped catch-up, but the outbox can never drain
            # while it is there, so health stays degraded.
            with self._lock:
                self._head_blocked_reason = "foreign_topic_row"
        with self._lock:
            cursor = self._cursor
        if head_id > cursor:
            if topic == self.config.telemetry_topic:
                with self._lock:
                    self._head_problem = None
                    self._head_blocked_reason = None
            return self._count_replay("awaiting_first_transmission")
        outcome = self._catch_up.tick(
            self._publish_window,
            now_monotonic=self._monotonic(),
            first_transmission_cursor=cursor,
            first_sent_at=self._sent_at,
        )
        if topic == self.config.telemetry_topic:
            # A corrupt local head row is skipped (never resent, never
            # pruned) and reported until it is no longer the head.
            for row_id, reason in self._catch_up.last_skipped():
                if row_id == head_id:
                    self._head_problem = (head_id, reason)
            with self._lock:
                if self._head_problem is not None and self._head_problem[0] == head_id:
                    self._head_blocked_reason = self._head_problem[1]
                else:
                    self._head_problem = None
                    self._head_blocked_reason = None
        return self._count_replay(outcome)

    def _count_replay(self, outcome: str) -> str:
        with self._lock:
            self._replay_outcomes[outcome] = self._replay_outcomes.get(outcome, 0) + 1
        return outcome

    def _replay_loop(self) -> None:
        busy = False
        while not self._stop.is_set():
            if not busy:
                # Idle: wait for a receipt (wake) or at most one second.
                self._wake.wait(timeout=1.0)
            self._wake.clear()
            if self._stop.is_set():
                break
            outcome = "error"
            try:
                outcome = self.replay_tick()
            except Exception:  # noqa: BLE001 - keep the loop alive, rows retained
                with self._lock:
                    self._replay_errors_total += 1
                LOG.exception("Committed-receipt replay tick failed; rows retained")
            # A catch-up in progress ticks every replay_min_interval_seconds;
            # the window and token bucket bound what each tick may send.
            busy = outcome in {"resent", "rate_limited", "skipped_rows"}
            self._stop.wait(self.config.replay_min_interval_seconds)

    # ------------------------------------------------------------- lifecycle
    def start(self, host: str, port: int) -> None:
        self.receipt_client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.receipt_client.connect_async(host, port, keepalive=30)
        self.receipt_client.loop_start()
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._replay_loop,
                name="committed-receipt-replay",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        try:
            self.receipt_client.disconnect()
            self.receipt_client.loop_stop()
        except Exception:  # noqa: BLE001
            LOG.warning("Receipt subscriber stop failed", exc_info=True)

    # --------------------------------------------------------------- metrics
    def snapshot(self) -> dict[str, Any]:
        capacity_stale = False
        try:
            capacity = self.queue.replay_capacity_snapshot(now=self._wall_clock())
            self._last_capacity = capacity
        except (sqlite3.Error, OSError):
            capacity = self._last_capacity or {}
            capacity_stale = True
        catch_up = self._catch_up.snapshot(now_monotonic=self._monotonic())
        with self._lock:
            return {
                "schema_version": 1,
                "mode": "enabled",
                "receipt_topic": self.config.receipt_topic,
                "publisher_authorization": "broker_acl_configured",
                "receipt_subscriber_connected": self._receipt_connected,
                "subscribe_acknowledged": self._subscribe_acknowledged,
                "pending_count": capacity.get("pending_count"),
                "pending_payload_bytes": capacity.get("pending_payload_bytes"),
                "oldest_pending_age_seconds": capacity.get("oldest_pending_age_seconds"),
                "sqlite_file_bytes": capacity.get("sqlite_file_bytes"),
                "filesystem_free_bytes": capacity.get("filesystem_free_bytes"),
                "capacity_stale": capacity_stale,
                "retention_guaranteed": False,
                "first_transmission_cursor": self._cursor,
                "first_transmissions_total": self._first_transmissions_total,
                "receipts_applied_total": self._applied_final_total,
                "receipts_informational_total": self._informational_total,
                "receipts_rejected_total": self._rejected_total,
                "receipts_rejected_by_reason": dict(self._rejected_by_reason),
                "replay_attempts_total": (
                    catch_up["resent_total"] + catch_up["publish_failures_total"]
                ),
                "replay_pubacks_total": catch_up["resent_total"],
                "replay_failures_total": catch_up["publish_failures_total"],
                "replay_next_retry_seconds": catch_up["next_attempt_seconds"],
                "catch_up": catch_up,
                "replay_outcomes": dict(self._replay_outcomes),
                "replay_errors_total": self._replay_errors_total,
                "head_blocked_reason": self._head_blocked_reason,
            }


def build_runtime(
    config: CommittedReceiptConfig,
    queue: Any,
    *,
    publish_client: Any,
    telemetry_connected: Callable[[], bool],
    read_secret: Callable[..., str],
    tls_config: Any,
    client_factory: Callable[[str], Any] | None = None,
) -> CommittedReceiptRuntime:
    """Create the dedicated receipt subscriber client and the runtime.

    The receipt client uses its own username, password file and client id. With
    TLS it trusts the same CA but never presents the telemetry client
    certificate, so ``use_identity_as_username`` cannot map it to the telemetry
    identity.
    """

    if client_factory is None:
        import paho.mqtt.client as mqtt

        def client_factory(client_id: str) -> Any:
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)

    client = client_factory(config.client_id)
    password = read_secret(config.password_file, label="Receipt MQTT password")
    client.username_pw_set(config.username, password)
    del password
    if getattr(tls_config, "enabled", False):
        from mqtt_tls import MQTTTLSConfig

        MQTTTLSConfig(enabled=True, ca_file=tls_config.ca_file).apply(client)
    return CommittedReceiptRuntime(
        config,
        queue,
        receipt_client=client,
        publish_client=publish_client,
        telemetry_connected=telemetry_connected,
    )
