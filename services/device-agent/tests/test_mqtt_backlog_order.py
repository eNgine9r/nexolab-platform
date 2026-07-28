from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from main import AgentState, DeviceAgent, OfflineQueue, Settings, TelemetryRecord


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class MQTTBacklogOrderingTests(unittest.TestCase):
    @staticmethod
    def settings(database_path: Path | None = None) -> Settings:
        environment = {
            "NEXOLAB_NODE_ID": "edge-01",
            "NEXOLAB_ORGANIZATION_ID": ORGANIZATION_ID,
        }
        if database_path is not None:
            environment["DATABASE_PATH"] = str(database_path)
        with patch.dict(os.environ, environment, clear=True):
            return Settings.from_env()

    @staticmethod
    def record(event_id: str) -> TelemetryRecord:
        return TelemetryRecord(
            event_id=event_id,
            node_id="edge-01",
            captured_at="2026-07-27T00:00:00+00:00",
            metric="temperature.air",
            value=4.2,
            unit="degC",
            quality="valid",
            source="simulator",
        )

    @staticmethod
    def publish_result(*, acknowledged: bool, rc: int = 0) -> Mock:
        result = Mock(rc=rc)
        result.is_published.return_value = acknowledged
        return result

    def make_agent(self) -> DeviceAgent:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        database_path = Path(temporary_directory.name) / "edge.db"
        agent = object.__new__(DeviceAgent)
        agent.settings = self.settings(database_path)
        agent.state = AgentState()
        agent.client = Mock()
        agent.queue = OfflineQueue(database_path)
        return agent

    def test_record_is_persisted_before_network_publish(self) -> None:
        agent = self.make_agent()
        agent.state.update(mqtt_connected=True)
        result = self.publish_result(acknowledged=True)

        def publish_after_durable_enqueue(*_args, **_kwargs):
            self.assertEqual(agent.queue.size(), 1)
            return result

        agent.client.publish.side_effect = publish_after_durable_enqueue

        published = DeviceAgent.publish_or_queue(agent, self.record("event-1"))

        self.assertTrue(published)
        self.assertEqual(agent.queue.size(), 0)
        result.wait_for_publish.assert_called_once_with(timeout=5)
        result.is_published.assert_called_once_with()

    def test_unacknowledged_qos1_publish_remains_in_outbox(self) -> None:
        agent = self.make_agent()
        agent.state.update(mqtt_connected=True)
        result = self.publish_result(acknowledged=False)
        agent.client.publish.return_value = result

        published = DeviceAgent.publish_or_queue(agent, self.record("event-1"))

        self.assertFalse(published)
        self.assertEqual(agent.queue.size(), 1)
        rows = agent.queue.oldest()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][2])["node_sequence"], 1)

    def test_disconnected_sample_is_persisted_without_publish(self) -> None:
        agent = self.make_agent()
        agent.state.update(mqtt_connected=False)

        published = DeviceAgent.publish_or_queue(agent, self.record("event-1"))

        self.assertFalse(published)
        self.assertEqual(agent.queue.size(), 1)
        agent.client.publish.assert_not_called()

    def test_flush_uses_sqlite_order_without_resequencing(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.state = AgentState()
        agent.state.update(mqtt_connected=True)
        agent.client = Mock()
        agent.queue = Mock()
        agent.queue.oldest.return_value = [
            (11, "topic", '{"node_sequence":11}'),
            (12, "topic", '{"node_sequence":12}'),
        ]
        agent.client.publish.side_effect = [
            self.publish_result(acknowledged=True),
            self.publish_result(acknowledged=True),
        ]

        self.assertTrue(DeviceAgent.flush_queue(agent))

        payloads = [call.args[1] for call in agent.client.publish.call_args_list]
        self.assertEqual(
            [json.loads(payload)["node_sequence"] for payload in payloads],
            [11, 12],
        )
        self.assertEqual(
            [call.args[0] for call in agent.queue.delete.call_args_list],
            [11, 12],
        )

    def test_flush_stops_without_deleting_unacknowledged_row(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.state = AgentState()
        agent.state.update(mqtt_connected=True)
        agent.client = Mock()
        agent.queue = Mock()
        agent.queue.oldest.return_value = [
            (11, "topic", '{"node_sequence":11}'),
            (12, "topic", '{"node_sequence":12}'),
        ]
        agent.client.publish.return_value = self.publish_result(
            acknowledged=False
        )

        self.assertFalse(DeviceAgent.flush_queue(agent))
        agent.queue.delete.assert_not_called()
        self.assertEqual(agent.client.publish.call_count, 1)


if __name__ == "__main__":
    unittest.main()
