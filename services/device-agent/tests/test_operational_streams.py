from __future__ import annotations

import json
import unittest
from collections import defaultdict
from typing import Any

from operational_streams import NodeOperationalPublisher


class FakePublishResult:
    rc = 0

    def wait_for_publish(self, timeout: float | None = None) -> None:
        self.timeout = timeout


class FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], int, bool]] = []
        self.wills: list[tuple[str, dict[str, Any], int, bool]] = []

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> FakePublishResult:
        self.published.append((topic, json.loads(payload), qos, retain))
        return FakePublishResult()

    def will_set(
        self,
        topic: str,
        payload: str | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        assert payload is not None
        self.wills.append((topic, json.loads(payload), qos, retain))


class SequenceStore:
    def __init__(self) -> None:
        self.values: defaultdict[str, int] = defaultdict(int)

    def next(self, stream: str) -> int:
        self.values[stream] += 1
        return self.values[stream]


class NodeOperationalPublisherTests(unittest.TestCase):
    def build_publisher(self, *, last_error: str | None = None):
        client = FakeMqttClient()
        sequences = SequenceStore()
        publisher = NodeOperationalPublisher(
            client,
            organization_id="org-a",
            node_id="edge-01",
            software_version="0.15.0",
            device_mode="simulator",
            health_interval_seconds=30,
            next_sequence=sequences.next,
            state_snapshot=lambda: {
                "uptime_seconds": 120,
                "queue_depth": 4,
                "samples_total": 25,
                "last_sample_at": "2026-07-27T06:00:00+00:00",
                "last_publish_at": "2026-07-27T06:00:01+00:00",
                "last_error": last_error,
            },
        )
        return publisher, client, sequences

    def test_connection_reserves_monotonic_online_and_will_pairs(self) -> None:
        publisher, client, sequences = self.build_publisher()

        publisher.prepare_connection()
        self.assertEqual(len(client.wills), 1)
        initial_will = client.wills[0][1]
        self.assertEqual(initial_will["status"], "offline")
        self.assertEqual(initial_will["node_sequence"], 2)
        self.assertFalse(initial_will["graceful"])
        self.assertTrue(client.wills[0][3])

        self.assertTrue(publisher.on_connected())
        online = client.published[0][1]
        self.assertEqual(online["status"], "online")
        self.assertEqual(online["node_sequence"], 1)
        self.assertTrue(client.published[0][3])

        self.assertEqual(len(client.wills), 2)
        reconnect_will = client.wills[1][1]
        self.assertEqual(reconnect_will["node_sequence"], 4)
        self.assertEqual(sequences.values["status"], 4)

    def test_health_snapshot_is_non_retained_and_classified(self) -> None:
        publisher, client, sequences = self.build_publisher(
            last_error="MQTT backlog is growing"
        )

        self.assertTrue(publisher.publish_health_if_due(force=True))
        topic, payload, qos, retained = client.published[0]
        self.assertEqual(topic, "nexolab/v1/org-a/edge-01/health")
        self.assertEqual(payload["health"], "degraded")
        self.assertEqual(payload["last_error"], "MQTT backlog is growing")
        self.assertEqual(payload["queue_depth"], 4)
        self.assertEqual(payload["node_sequence"], 1)
        self.assertEqual(qos, 1)
        self.assertFalse(retained)
        self.assertEqual(sequences.values["health"], 1)
        self.assertIsNone(publisher.publish_health_if_due())

    def test_graceful_shutdown_publishes_new_retained_offline_event(self) -> None:
        publisher, client, sequences = self.build_publisher()
        publisher.prepare_connection()
        publisher.on_connected()

        self.assertTrue(publisher.publish_graceful_offline())
        offline = client.published[-1]
        self.assertEqual(offline[0], "nexolab/v1/org-a/edge-01/status")
        self.assertEqual(offline[1]["status"], "offline")
        self.assertEqual(offline[1]["reason"], "device agent stopped")
        self.assertTrue(offline[1]["graceful"])
        self.assertEqual(offline[1]["node_sequence"], 5)
        self.assertTrue(offline[3])
        self.assertEqual(sequences.values["status"], 5)


if __name__ == "__main__":
    unittest.main()
