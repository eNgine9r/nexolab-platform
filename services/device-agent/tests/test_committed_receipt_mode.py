"""#1762 slice 2: Edge committed-receipt wiring behind a default-OFF flag.

MQTT is faked; SQLite is real. Synthetic receipts here prove the Edge
behaviour only, not the installed broker ACL or any site/hardware path.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from committed_receipt_mode import (
    FLAG,
    CommittedReceiptRuntime,
    parse_committed_receipt_config,
)
from main import DeviceAgent, OfflineQueue, Settings, TelemetryRecord, read_mounted_secret
from receipt_retention import CommittedReceiptQueue

ORG = "00000000-0000-0000-0000-000000000001"
NODE = "edge-01"
TELEMETRY_USERNAME = f"node:{ORG}:{NODE}"
TELEMETRY_CLIENT_ID = f"nexolab-{ORG}-{NODE}"
TELEMETRY_TOPIC = f"nexolab/v1/{ORG}/{NODE}/telemetry"
RECEIPT_TOPIC = f"nexolab/v1/{ORG}/{NODE}/receipts"
RECEIPT_USERNAME = f"edge-receipts:{ORG}:{NODE}"
PUBLISHER = "nexolab-central-receipts-site"
TELEMETRY_SECRET = "nxl_edge_telemetry_secret"
RECEIPT_SECRET = "nxl_edge_receipt_secret"


class FakeResult:

    def __init__(self, acknowledged: bool) -> None:
        self.rc = 0
        self._acknowledged = acknowledged

    def wait_for_publish(self, timeout: float | None = None) -> None:
        del timeout

    def is_published(self) -> bool:
        return self._acknowledged


class FakeClient:
    """Minimal Paho stand-in: records publishes, subscriptions and identity."""

    def __init__(self, client_id: str = "") -> None:
        self.client_id = client_id
        self.published: list[tuple[str, str]] = []
        self.subscriptions: list[tuple[str, int]] = []
        self.credentials: tuple[str, str] | None = None
        self.acknowledge = True
        self.started = False
        self.on_connect = self.on_disconnect = None
        self.on_subscribe = self.on_message = None

    def publish(self, topic: str, payload: str, qos: int = 0) -> FakeResult:
        assert qos == 1
        self.published.append((topic, payload))
        return FakeResult(self.acknowledge)

    def subscribe(self, topic: str, qos: int = 0) -> tuple[int, int]:
        self.subscriptions.append((topic, qos))
        return (0, 1)

    def username_pw_set(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def tls_set_context(self, context: object) -> None:
        del context

    def enable_logger(self, logger: object) -> None:
        del logger

    def reconnect_delay_set(self, **_: object) -> None:
        pass

    def connect_async(self, *_: object, **__: object) -> None:
        pass

    def loop_start(self) -> None:
        self.started = True

    def loop_stop(self) -> None:
        self.started = False

    def disconnect(self) -> None:
        pass


class Clock:

    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def receipt(
    event_id: str,
    sequence: int,
    *,
    level: str = "postgres_committed",
    overrides: dict[str, object] | None = None,
) -> bytes:
    message: dict[str, object] = {
        "contract_version": 1,
        "receipt_id": str(uuid.uuid4()),
        "event_id": event_id,
        "organization_id": ORG,
        "node_id": NODE,
        "stream": "telemetry",
        "node_sequence": sequence,
        "receipt_level": level,
        "accepted_at": datetime.now(timezone.utc).isoformat(),
    }
    message.update(overrides or {})
    return json.dumps(message).encode("utf-8")


class Fixture(unittest.TestCase):

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_password = self.root / "telemetry-password"
        self.telemetry_password.write_text(TELEMETRY_SECRET, encoding="utf-8")
        self.receipt_password = self.root / "receipt-password"
        self.receipt_password.write_text(RECEIPT_SECRET, encoding="utf-8")
        self.database = self.root / "edge.db"

    def environment(self, **extra: str) -> dict[str, str]:
        values = {
            "NEXOLAB_NODE_ID": NODE,
            "NEXOLAB_ORGANIZATION_ID": ORG,
            "MQTT_AUTH_REQUIRED": "true",
            "MQTT_PASSWORD_FILE": str(self.telemetry_password),
            "DATABASE_PATH": str(self.database),
        }
        values.update(extra)
        return values

    def enabled_environment(self, **extra: str) -> dict[str, str]:
        values = self.environment(
            **{
                FLAG: "enabled",
                "DEVICE_AGENT_RECEIPT_MQTT_USERNAME": RECEIPT_USERNAME,
                "DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE": str(self.receipt_password),
                "DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME": PUBLISHER,
                "DEVICE_AGENT_RECEIPT_BROKER_ACL": "broker-enforced",
                "DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS": "30",
                "DEVICE_AGENT_RECEIPT_REPLAY_INITIAL_RETRY_SECONDS": "5",
                "DEVICE_AGENT_RECEIPT_REPLAY_MAX_RETRY_SECONDS": "40",
            }
        )
        values.update(extra)
        return values

    def settings(self, environment: dict[str, str]) -> Settings:
        with patch.dict(os.environ, environment, clear=True):
            return Settings.from_env()

    def agent(self, environment: dict[str, str]) -> tuple[DeviceAgent, dict[str, FakeClient]]:
        settings = self.settings(environment)
        clients: dict[str, FakeClient] = {}

        def factory(*_: object, client_id: str = "", **__: object) -> FakeClient:
            clients[client_id] = FakeClient(client_id)
            return clients[client_id]

        with patch.dict(os.environ, environment, clear=True), patch(
            "main.mqtt.Client", side_effect=factory
        ), patch("main.NodeOperationalPublisher"):
            agent = DeviceAgent(settings)
        self.addCleanup(agent.queue._connection.close)
        agent.state.update(mqtt_connected=True)
        return agent, clients

    @staticmethod
    def record() -> TelemetryRecord:
        return TelemetryRecord(
            event_id=str(uuid.uuid4()),
            node_id=NODE,
            captured_at=datetime.now(timezone.utc).isoformat(),
            metric="temperature.air",
            value=4.2,
            unit="degC",
            quality="valid",
            source="simulator",
        )


class ConfigurationTests(Fixture):

    def test_flag_defaults_to_disabled(self) -> None:
        settings = self.settings(self.environment())
        self.assertIsNone(settings.committed_receipts)
        # Receipt-only settings are ignored while the flag is off.
        settings = self.settings(
            self.environment(DEVICE_AGENT_RECEIPT_MQTT_USERNAME=RECEIPT_USERNAME)
        )
        self.assertIsNone(settings.committed_receipts)
        settings = self.settings(self.environment(**{FLAG: "disabled"}))
        self.assertIsNone(settings.committed_receipts)

    def test_unknown_flag_value_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be disabled or enabled"):
            self.settings(self.environment(**{FLAG: "on"}))

    def test_valid_enabled_configuration(self) -> None:
        config = self.settings(self.enabled_environment()).committed_receipts
        assert config is not None
        self.assertEqual(config.receipt_topic, RECEIPT_TOPIC)
        self.assertEqual(config.telemetry_topic, TELEMETRY_TOPIC)
        self.assertEqual(config.client_id, f"nexolab-{ORG}-{NODE}-receipts")
        self.assertEqual(config.replay_after_seconds, 30.0)
        self.assertEqual(config.catch_up_window, 50)
        self.assertEqual(config.catch_up_max_rows_per_second, 200.0)

    def test_catch_up_window_and_rate_are_validated(self) -> None:
        config = self.settings(self.enabled_environment(
            DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW="8",
            DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND="40",
        )).committed_receipts
        assert config is not None
        self.assertEqual((config.catch_up_window, config.catch_up_max_rows_per_second), (8, 40.0))
        for value in ("0", "501", "1.5", "many"):
            with self.subTest(window=value):
                self.assert_config_error(
                    self.enabled_environment(DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW=value),
                    "DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW must be an integer",
                )
        for value in ("0", "-1", "inf", "1001"):
            with self.subTest(rate=value):
                self.assert_config_error(
                    self.enabled_environment(
                        DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND=value
                    ),
                    "DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND",
                )

    def assert_config_error(self, environment: dict[str, str], fragment: str) -> None:
        with self.assertRaises(ValueError) as caught:
            self.settings(environment)
        message = str(caught.exception)
        self.assertIn(fragment, message)
        for secret in (TELEMETRY_SECRET, RECEIPT_SECRET):
            self.assertNotIn(secret, message)

    def test_enabled_requires_strict_org_scoped_identity(self) -> None:
        environment = self.enabled_environment()
        environment.pop("NEXOLAB_NODE_ID")
        self.assert_config_error(environment, "NEXOLAB_NODE_ID must be set explicitly")

        unscoped = self.enabled_environment()
        for key in ("NEXOLAB_ORGANIZATION_ID", "MQTT_AUTH_REQUIRED", "MQTT_PASSWORD_FILE"):
            unscoped.pop(key)
        self.assert_config_error(unscoped, "NEXOLAB_ORGANIZATION_ID is required")
        self.assert_config_error(unscoped, "MQTT_AUTH_REQUIRED=true is required")

    def test_enabled_rejects_noncanonical_organization(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical lowercase UUID"):
            parse_committed_receipt_config(
                organization_id="AAAAAAAA-0000-0000-0000-000000000001",
                node_id=NODE,
                mqtt_auth_required=True,
                telemetry_username="x",
                telemetry_client_id="y",
                read_secret=read_mounted_secret,
                environment=self.enabled_environment(),
            )

    def test_receipt_identity_must_differ_from_telemetry_identity(self) -> None:
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_MQTT_USERNAME=TELEMETRY_USERNAME),
            "DEVICE_AGENT_RECEIPT_MQTT_USERNAME must differ from MQTT_USERNAME",
        )
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID=TELEMETRY_CLIENT_ID),
            "DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID must differ from MQTT_CLIENT_ID",
        )

    def test_missing_receipt_settings_are_named(self) -> None:
        environment = self.environment(**{FLAG: "enabled"})
        with self.assertRaises(ValueError) as caught:
            self.settings(environment)
        message = str(caught.exception)
        for name in (
            "DEVICE_AGENT_RECEIPT_MQTT_USERNAME is required",
            "DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE is required",
            "DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME is required",
            "DEVICE_AGENT_RECEIPT_BROKER_ACL must be broker-enforced",
        ):
            self.assertIn(name, message)

    def test_unreadable_receipt_password_file_fails_closed(self) -> None:
        self.assert_config_error(
            self.enabled_environment(
                DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE=str(self.root / "missing")
            ),
            "Receipt MQTT password file is not readable",
        )

    def test_publisher_identity_and_acl_attestation_are_strict(self) -> None:
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME="central"),
            "nexolab-central-receipts-* namespace",
        )
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_BROKER_ACL="true"),
            "DEVICE_AGENT_RECEIPT_BROKER_ACL must be broker-enforced",
        )

    def test_replay_budget_is_validated(self) -> None:
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS="0"),
            "DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS must be a positive",
        )
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_REPLAY_MAX_RETRY_SECONDS="1"),
            "DEVICE_AGENT_RECEIPT_REPLAY_MAX_RETRY_SECONDS must be >=",
        )
        self.assert_config_error(
            self.enabled_environment(DEVICE_AGENT_RECEIPT_REPLAY_MIN_INTERVAL_SECONDS="nan"),
            "DEVICE_AGENT_RECEIPT_REPLAY_MIN_INTERVAL_SECONDS",
        )


class DisabledPathTests(Fixture):

    def test_disabled_keeps_legacy_queue_and_deletes_on_puback(self) -> None:
        agent, clients = self.agent(self.environment())
        self.assertIs(type(agent.queue), OfflineQueue)
        self.assertIsNone(agent.committed_receipts)
        self.assertEqual(list(clients), [TELEMETRY_CLIENT_ID])

        self.assertTrue(agent.publish_or_queue(self.record()))
        self.assertEqual(agent.queue.size(), 0)
        self.assertEqual(len(clients[TELEMETRY_CLIENT_ID].published), 1)
        self.assertNotIn("committed_receipts", agent._state_snapshot_for_health())

    def test_disabled_unacknowledged_row_stays_like_today(self) -> None:
        agent, clients = self.agent(self.environment())
        clients[TELEMETRY_CLIENT_ID].acknowledge = False
        self.assertFalse(agent.publish_or_queue(self.record()))
        self.assertEqual(agent.queue.size(), 1)


class EnabledPathTests(Fixture):

    def setUp(self) -> None:
        super().setUp()
        self.clock = Clock()

    def enabled_agent(self, **extra: str) -> tuple[DeviceAgent, FakeClient, FakeClient]:
        agent, clients = self.agent(self.enabled_environment(**extra))
        runtime: CommittedReceiptRuntime = agent.committed_receipts
        runtime._monotonic = self.clock
        runtime._sent_batches.clear()
        return (
            agent,
            clients[TELEMETRY_CLIENT_ID],
            clients[f"nexolab-{ORG}-{NODE}-receipts"],
        )

    def queued(self, agent: DeviceAgent) -> list[tuple[int, str, int]]:
        return [
            (row_id, json.loads(payload)["event_id"], json.loads(payload)["node_sequence"])
            for row_id, _topic, payload in agent.queue.oldest()
        ]

    def test_enabled_uses_receipt_queue_and_separate_identity(self) -> None:
        agent, telemetry, receipts = self.enabled_agent()
        self.assertIsInstance(agent.queue, CommittedReceiptQueue)
        self.assertEqual(telemetry.credentials, (TELEMETRY_USERNAME, TELEMETRY_SECRET))
        self.assertEqual(receipts.credentials, (RECEIPT_USERNAME, RECEIPT_SECRET))
        self.assertIsNot(agent.committed_receipts.publish_client, receipts)

        receipts.on_connect(receipts, None, None, 0, None)
        self.assertEqual(receipts.subscriptions, [(RECEIPT_TOPIC, 1)])
        receipts.on_subscribe(receipts, None, 1, [0], None)
        snapshot = agent._state_snapshot_for_health()["committed_receipts"]
        self.assertTrue(snapshot["receipt_subscriber_connected"])
        self.assertTrue(snapshot["subscribe_acknowledged"])
        serialized = json.dumps(snapshot)
        for value in (RECEIPT_SECRET, RECEIPT_USERNAME, PUBLISHER, str(self.receipt_password)):
            self.assertNotIn(value, serialized)

    def test_puback_does_not_delete_and_rows_are_sent_once(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        for _ in range(3):
            self.assertTrue(agent.publish_or_queue(self.record()))
        self.assertEqual(agent.queue.size(), 3)
        self.assertEqual(len(telemetry.published), 3)
        self.assertTrue(agent.flush_queue())
        self.assertTrue(agent.flush_queue())
        # No re-send by the normal flush; only the bounded head replay resends.
        self.assertEqual(len(telemetry.published), 3)
        self.assertEqual(
            [json.loads(p)["node_sequence"] for _, p in telemetry.published], [1, 2, 3]
        )

    def test_valid_committed_receipt_prunes_exactly_one_row(self) -> None:
        agent, _, receipts = self.enabled_agent()
        agent.publish_or_queue(self.record())
        agent.publish_or_queue(self.record())
        (first_id, first_event, first_seq), second = self.queued(agent)

        message = Mock(topic=RECEIPT_TOPIC, payload=receipt(first_event, first_seq))
        receipts.on_message(receipts, None, message)

        self.assertEqual(self.queued(agent), [second])
        snapshot = agent._state_snapshot_for_health()["committed_receipts"]
        self.assertEqual(snapshot["receipts_applied_total"], 1)
        self.assertEqual(snapshot["pending_count"], 1)

    def test_durably_spooled_never_prunes(self) -> None:
        agent, _, _ = self.enabled_agent()
        agent.publish_or_queue(self.record())
        [(_, event, seq)] = self.queued(agent)
        outcome = agent.committed_receipts.handle_receipt(
            RECEIPT_TOPIC, receipt(event, seq, level="durably_spooled")
        )
        self.assertEqual(outcome, "informational")
        self.assertEqual(agent.queue.size(), 1)

    def test_forged_wrong_node_duplicate_and_stale_receipts_are_rejected(self) -> None:
        agent, _, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        agent.publish_or_queue(self.record())
        agent.publish_or_queue(self.record())
        (_, event, seq), (_, second_event, second_seq) = self.queued(agent)

        other_node_topic = f"nexolab/v1/{ORG}/edge-02/receipts"
        cases = {
            "unexpected_receipt_topic": (other_node_topic, receipt(event, seq)),
            "receipt_identity_mismatch": (
                RECEIPT_TOPIC,
                receipt(event, seq, overrides={"node_id": "edge-02"}),
            ),
            "stale_receipt_timestamp": (
                RECEIPT_TOPIC,
                receipt(
                    event,
                    seq,
                    overrides={
                        "accepted_at": (
                            datetime.now(timezone.utc) - timedelta(days=8)
                        ).isoformat()
                    },
                ),
            ),
            "invalid_receipt_json": (RECEIPT_TOPIC, b"{not json"),
            # Exact-row binding: a receipt naming one row with another row's
            # sequence never prunes either row.
            "receipt_sequence_mismatch": (RECEIPT_TOPIC, receipt(second_event, seq)),
            # An unknown (or already pruned) event never prunes anything.
            "no_matching_pending_telemetry": (
                RECEIPT_TOPIC,
                receipt(str(uuid.uuid4()), second_seq),
            ),
        }
        for reason, (topic, payload) in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(runtime.handle_receipt(topic, payload), "rejected")
        self.assertEqual(agent.queue.size(), 2)

        # Out of order is accepted for its exact pending row only.
        valid = receipt(second_event, second_seq)
        self.assertEqual(runtime.handle_receipt(RECEIPT_TOPIC, valid), "pruned")
        # Exact duplicate (same receipt_id) is rejected by the durable ledger.
        self.assertEqual(runtime.handle_receipt(RECEIPT_TOPIC, valid), "rejected")
        self.assertEqual([row[1] for row in self.queued(agent)], [event])
        self.assertEqual(runtime.handle_receipt(RECEIPT_TOPIC, receipt(event, seq)), "pruned")
        self.assertEqual(agent.queue.size(), 0)

        reasons = runtime.snapshot()["receipts_rejected_by_reason"]
        for reason in cases:
            self.assertEqual(reasons[reason], 1, reason)
        self.assertEqual(reasons["receipt_id_already_processed"], 1)
        self.assertEqual(runtime.snapshot()["receipts_rejected_total"], 7)
        self.assertEqual(runtime.snapshot()["receipts_applied_total"], 2)

    def test_publisher_authorization_never_comes_from_message(self) -> None:
        agent, _, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        agent.publish_or_queue(self.record())
        [(_, event, seq)] = self.queued(agent)
        # Simulate a config that was not validated as broker-enforced.
        runtime._publisher_authorized = False
        outcome = runtime.handle_receipt(RECEIPT_TOPIC, receipt(event, seq))
        self.assertEqual(outcome, "rejected")
        self.assertEqual(
            runtime.snapshot()["receipts_rejected_by_reason"],
            {"central_publisher_not_authenticated": 1},
        )
        self.assertEqual(agent.queue.size(), 1)

    def test_catch_up_waits_for_age_then_resends_fifo_with_stall_backoff(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        for _ in range(3):
            agent.publish_or_queue(self.record())
        payloads = [payload for _, _, payload in agent.queue.oldest()]
        sent = len(telemetry.published)

        for _ in range(100):
            self.assertEqual(runtime.replay_tick(), "waiting_receipt")
        self.assertEqual(len(telemetry.published), sent)

        self.clock.value += 30
        outcomes = [runtime.replay_tick() for _ in range(1000)]
        self.assertEqual(outcomes.count("resent"), 1)
        self.assertEqual(outcomes.count("waiting_receipt"), 999)
        # One FIFO window with every eligible row, in SQLite id order.
        self.assertEqual(
            telemetry.published[sent:], [(TELEMETRY_TOPIC, p) for p in payloads]
        )

        resends = []
        for step in range(1, 200):  # 199 simulated seconds
            self.clock.value += 1
            before = len(telemetry.published)
            if runtime.replay_tick() == "resent":
                resends.append(step)
                self.assertEqual(
                    telemetry.published[before:], [(TELEMETRY_TOPIC, p) for p in payloads]
                )
        # No receipt ever came back (central down): each expired window adds
        # an exponential stall backoff 5, 10, 20, 40 (capped at 40).
        self.assertEqual(resends, [35, 75, 125, 195])
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["replay_pubacks_total"], 15)
        self.assertEqual(snapshot["catch_up"]["stalls_total"], 4)
        self.assertEqual(agent.queue.size(), 3)

    def test_applied_receipt_ends_stall_backoff(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        for _ in range(3):
            agent.publish_or_queue(self.record())
        (_, event, seq), *_rest = self.queued(agent)
        self.clock.value += 30
        self.assertEqual(runtime.replay_tick(), "resent")
        self.clock.value += 30
        self.assertEqual(runtime.replay_tick(), "deferred")
        self.assertEqual(runtime.handle_receipt(RECEIPT_TOPIC, receipt(event, seq)), "pruned")
        before = len(telemetry.published)
        # The expired sweep ends, then a new one starts without the backoff.
        self.assertEqual(runtime.replay_tick(), "waiting_receipt")
        self.assertEqual(runtime.replay_tick(), "resent")
        self.assertEqual(len(telemetry.published) - before, 2)

    def test_window_bounds_in_flight_rows_and_rate(self) -> None:
        agent, telemetry, _ = self.enabled_agent(DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW="2")
        runtime = agent.committed_receipts
        for _ in range(5):
            agent.publish_or_queue(self.record())
        rows = self.queued(agent)
        sent = len(telemetry.published)
        self.clock.value += 31

        def resent_sequences() -> list[int]:
            return [json.loads(p)["node_sequence"] for _, p in telemetry.published[sent:]]

        self.assertEqual(runtime.replay_tick(), "resent")
        self.assertEqual(resent_sequences(), [1, 2])
        for _ in range(50):
            self.assertEqual(runtime.replay_tick(), "window_full")
        # An out-of-order exact-row receipt frees one slot in the window.
        _, second_event, second_seq = rows[1]
        self.assertEqual(
            runtime.handle_receipt(RECEIPT_TOPIC, receipt(second_event, second_seq)),
            "pruned",
        )
        self.assertTrue(runtime._wake.is_set())
        # The token bucket is empty until time passes (bounded rate).
        self.assertEqual(runtime.replay_tick(), "rate_limited")
        self.clock.value += 0.01
        self.assertEqual(runtime.replay_tick(), "resent")
        self.assertEqual(resent_sequences(), [1, 2, 3])
        self.assertEqual(runtime.replay_tick(), "window_full")
        self.assertEqual(runtime.snapshot()["catch_up"]["in_flight"], 2)
        self.assertEqual(agent.queue.size(), 4)

    def test_publish_failure_keeps_rows_and_backs_off(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        for _ in range(2):
            agent.publish_or_queue(self.record())
        self.clock.value += 31
        telemetry.acknowledge = False
        self.assertEqual(runtime.replay_tick(), "retry_scheduled")
        self.assertEqual(runtime.replay_tick(), "deferred")
        telemetry.acknowledge = True
        self.clock.value += 5
        self.assertEqual(runtime.replay_tick(), "resent")
        self.assertEqual(agent.queue.size(), 2)
        self.assertEqual(runtime.snapshot()["replay_failures_total"], 1)

    def test_corrupt_local_head_row_is_skipped_and_reported(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        runtime = agent.committed_receipts
        for _ in range(2):
            agent.publish_or_queue(self.record())
        (head_id, _, _), (_, second_event, _) = self.queued(agent)
        with agent.queue._connection:
            agent.queue._connection.execute(
                "UPDATE outbound_queue SET payload=? WHERE id=?",
                (json.dumps({"event_id": str(uuid.uuid4()), "node_id": NODE}), head_id),
            )
        sent = len(telemetry.published)
        self.clock.value += 31
        self.assertEqual(runtime.replay_tick(), "resent")
        self.assertEqual(
            [json.loads(p)["event_id"] for _, p in telemetry.published[sent:]],
            [second_event],
        )
        health = agent._state_snapshot_for_health()
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(
            health["committed_receipts"]["head_blocked_reason"],
            "invalid_local_replay_identity",
        )
        self.assertEqual(agent.queue.size(), 2)

    def test_replay_never_runs_while_telemetry_disconnected(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        agent.publish_or_queue(self.record())
        agent.state.update(mqtt_connected=False)
        self.clock.value += 1000
        self.assertEqual(agent.committed_receipts.replay_tick(), "telemetry_disconnected")
        self.assertEqual(len(telemetry.published), 1)

    def test_unacknowledged_first_send_is_not_replayed_until_resent(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        telemetry.acknowledge = False
        self.assertFalse(agent.publish_or_queue(self.record()))
        self.clock.value += 1000
        self.assertEqual(
            agent.committed_receipts.replay_tick(), "awaiting_first_transmission"
        )
        telemetry.acknowledge = True
        self.assertTrue(agent.flush_queue())
        self.assertEqual(len(telemetry.published), 2)
        self.assertEqual(agent.queue.size(), 1)

    def test_restart_mid_replay_keeps_rows_and_resends_fifo(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        for _ in range(3):
            agent.publish_or_queue(self.record())
        before = self.queued(agent)
        self.clock.value += 31
        self.assertEqual(agent.committed_receipts.replay_tick(), "resent")
        agent.stop_committed_receipts()
        agent.queue._connection.close()

        restarted, telemetry2, _ = self.enabled_agent()
        self.assertEqual(self.queued(restarted), before)
        self.assertTrue(restarted.flush_queue())
        self.assertEqual(
            [json.loads(p)["event_id"] for _, p in telemetry2.published],
            [event for _, event, _ in before],
        )
        # Receipt replay ledger is durable across the restart too.
        _, event, seq = before[0]
        valid = receipt(event, seq)
        self.assertEqual(
            restarted.committed_receipts.handle_receipt(RECEIPT_TOPIC, valid), "pruned"
        )
        restarted.stop_committed_receipts()
        restarted.queue._connection.close()
        third, _, _ = self.enabled_agent()
        self.assertEqual(
            third.committed_receipts.handle_receipt(RECEIPT_TOPIC, valid), "rejected"
        )
        self.assertEqual(len(self.queued(third)), 2)

    def test_foreign_head_row_is_never_resent_and_degrades_health(self) -> None:
        agent, telemetry, _ = self.enabled_agent()
        agent.queue.enqueue("nexolab/telemetry", json.dumps({"event_id": "x"}), "legacy-1")
        agent.publish_or_queue(self.record())
        agent.flush_queue()
        sent = len(telemetry.published)
        self.clock.value += 1000
        # The scoped row behind it still catches up (exact-row receipts).
        self.assertEqual(agent.committed_receipts.replay_tick(), "resent")
        self.assertTrue(
            all(topic == TELEMETRY_TOPIC for topic, _ in telemetry.published[sent:])
        )
        self.assertEqual(agent.queue.size(), 2)
        health = agent._state_snapshot_for_health()
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(
            health["committed_receipts"]["head_blocked_reason"], "foreign_topic_row"
        )
        self.assertEqual(
            health["committed_receipts"]["catch_up"]["skipped_rows_by_reason"],
            {"foreign_topic_row": 1},
        )

    def test_health_reports_capacity_and_replay_metrics(self) -> None:
        agent, _, _ = self.enabled_agent()
        agent.publish_or_queue(self.record())
        snapshot = agent._state_snapshot_for_health()["committed_receipts"]
        for key in (
            "pending_count",
            "oldest_pending_age_seconds",
            "pending_payload_bytes",
            "sqlite_file_bytes",
            "filesystem_free_bytes",
            "receipts_applied_total",
            "receipts_rejected_by_reason",
            "replay_attempts_total",
            "first_transmissions_total",
        ):
            self.assertIn(key, snapshot)
        self.assertEqual(snapshot["pending_count"], 1)
        self.assertFalse(snapshot["retention_guaranteed"])

    def test_start_and_stop_drive_dedicated_receipt_client(self) -> None:
        agent, telemetry, receipts = self.enabled_agent()
        runtime = agent.committed_receipts
        runtime.config = runtime.config.__class__(
            **{**runtime.config.__dict__, "replay_min_interval_seconds": 0.01}
        )
        agent.connect()
        self.assertTrue(receipts.started)
        self.assertTrue(runtime._thread.is_alive())
        agent.stop_committed_receipts()
        self.assertFalse(runtime._thread.is_alive())
        self.assertFalse(receipts.started)


if __name__ == "__main__":
    unittest.main()
