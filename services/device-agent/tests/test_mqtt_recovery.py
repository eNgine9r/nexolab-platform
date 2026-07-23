from __future__ import annotations

import unittest
from unittest.mock import Mock

from main import AgentState, DeviceAgent


class MQTTQueueRecoveryTests(unittest.TestCase):
    @staticmethod
    def _agent() -> DeviceAgent:
        agent = object.__new__(DeviceAgent)
        agent.state = AgentState()
        agent.state.update(mqtt_connected=True)
        agent.client = Mock()
        agent.queue = Mock()
        agent.queue.oldest.return_value = [
            (1, "nexolab/telemetry", '{"event_id":"queued"}')
        ]
        return agent

    def test_flush_queue_defers_runtime_error_without_deleting_record(self) -> None:
        agent = self._agent()
        publish_result = Mock()
        publish_result.wait_for_publish.side_effect = RuntimeError(
            "Message publish failed: client not connected"
        )
        agent.client.publish.return_value = publish_result

        with self.assertLogs("nexolab.device_agent", level="WARNING") as logs:
            result = DeviceAgent.flush_queue(agent)

        self.assertFalse(result)
        agent.queue.delete.assert_not_called()
        self.assertTrue(
            any("MQTT queue flush deferred" in line for line in logs.output)
        )

    def test_flush_queue_deletes_record_after_successful_publish(self) -> None:
        agent = self._agent()
        publish_result = Mock()
        publish_result.rc = 0
        agent.client.publish.return_value = publish_result

        result = DeviceAgent.flush_queue(agent)

        self.assertTrue(result)
        publish_result.wait_for_publish.assert_called_once_with(timeout=5)
        agent.queue.delete.assert_called_once_with(1)

    def test_flush_queue_keeps_record_after_non_success_result(self) -> None:
        agent = self._agent()
        publish_result = Mock()
        publish_result.rc = 4
        agent.client.publish.return_value = publish_result

        with self.assertLogs("nexolab.device_agent", level="WARNING"):
            result = DeviceAgent.flush_queue(agent)

        self.assertFalse(result)
        agent.queue.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
