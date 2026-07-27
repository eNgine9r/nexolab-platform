from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from main import AgentState, DeviceAgent, Settings, TelemetryRecord


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class MQTTBacklogOrderingTests(unittest.TestCase):
    @staticmethod
    def settings() -> Settings:
        with patch.dict(
            os.environ,
            {
                "NEXOLAB_NODE_ID": "edge-01",
                "NEXOLAB_ORGANIZATION_ID": ORGANIZATION_ID,
            },
            clear=True,
        ):
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

    def test_new_sample_is_appended_when_backlog_exists(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.settings = self.settings()
        agent.state = AgentState()
        agent.state.update(mqtt_connected=True)
        agent.client = Mock()
        agent.queue = Mock()
        agent.queue.size.return_value = 3
        agent.queue.next_sequence.return_value = 4

        published = DeviceAgent.publish_or_queue(agent, self.record("event-4"))

        self.assertFalse(published)
        agent.client.publish.assert_not_called()
        agent.queue.enqueue.assert_called_once()
        topic, payload, event_id = agent.queue.enqueue.call_args.args
        self.assertEqual(
            topic,
            f"nexolab/v1/{ORGANIZATION_ID}/edge-01/telemetry",
        )
        self.assertEqual(event_id, "event-4")
        self.assertEqual(json.loads(payload)["node_sequence"], 4)

    def test_direct_publish_remains_available_without_backlog(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.settings = self.settings()
        agent.state = AgentState()
        agent.state.update(mqtt_connected=True)
        agent.client = Mock()
        agent.queue = Mock()
        agent.queue.size.return_value = 0
        agent.queue.next_sequence.return_value = 1
        publish_result = Mock(rc=0)
        agent.client.publish.return_value = publish_result

        published = DeviceAgent.publish_or_queue(agent, self.record("event-1"))

        self.assertTrue(published)
        agent.queue.enqueue.assert_not_called()
        publish_result.wait_for_publish.assert_called_once_with(timeout=5)

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
        agent.client.publish.return_value = Mock(rc=0)

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


if __name__ == "__main__":
    unittest.main()
