from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from main import (
    AgentState,
    DeviceAgent,
    Settings,
    TelemetryRecord,
    mode_uses_le01mp,
    mode_uses_xjp60d,
    parse_unit_ids,
    parse_xjp60d_points,
)


class SettingsTests(unittest.TestCase):
    def test_parses_and_deduplicates_xjp60d_points(self) -> None:
        self.assertEqual(
            parse_xjp60d_points("106:3, 106:4,106:3"),
            ((106, 3), (106, 4)),
        )

    def test_parses_and_deduplicates_meter_unit_ids(self) -> None:
        self.assertEqual(
            parse_unit_ids("200, 201,200,203", label="LE-01MP"),
            (200, 201, 203),
        )

    def test_simulator_remains_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.device_mode, "simulator")
        self.assertEqual(settings.xjp60d_points, ())
        self.assertEqual(settings.le01mp_unit_ids, ())

    def test_xjp60d_mode_requires_points(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "xjp60d"}, clear=True):
            with self.assertRaisesRegex(ValueError, "XJP60D_POINTS"):
                Settings.from_env()

    def test_le01mp_mode_requires_units(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "le01mp"}, clear=True):
            with self.assertRaisesRegex(ValueError, "LE01MP_UNIT_IDS"):
                Settings.from_env()

    def test_combined_mode_accepts_both_sources(self) -> None:
        environment = {
            "DEVICE_MODE": "modbus",
            "XJP60D_POINTS": "106:3,106:4",
            "LE01MP_UNIT_IDS": "200,201,202,203",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.device_mode, "modbus")
        self.assertEqual(settings.xjp60d_points, ((106, 3), (106, 4)))
        self.assertEqual(settings.le01mp_unit_ids, (200, 201, 202, 203))

    def test_combined_mode_requires_at_least_one_source(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "modbus"}, clear=True):
            with self.assertRaisesRegex(ValueError, "At least one"):
                Settings.from_env()


class DriverModeGatingTests(unittest.TestCase):
    @staticmethod
    def _settings(device_mode: str) -> Settings:
        environment = {
            "DEVICE_MODE": device_mode,
            "XJP60D_POINTS": "106:3,106:4",
            "LE01MP_UNIT_IDS": "201",
        }
        with patch.dict(os.environ, environment, clear=True):
            return Settings.from_env()

    @staticmethod
    def _record(source: str) -> TelemetryRecord:
        return TelemetryRecord(
            event_id="test-event",
            node_id="edge-01",
            captured_at="2026-07-23T00:00:00+00:00",
            metric="test.metric",
            value=1.0,
            unit="test",
            quality="valid",
            source=source,
        )

    def test_mode_helpers(self) -> None:
        self.assertTrue(mode_uses_xjp60d("xjp60d"))
        self.assertTrue(mode_uses_xjp60d("modbus"))
        self.assertFalse(mode_uses_xjp60d("le01mp"))
        self.assertTrue(mode_uses_le01mp("le01mp"))
        self.assertTrue(mode_uses_le01mp("modbus"))
        self.assertFalse(mode_uses_le01mp("xjp60d"))

    def test_health_hides_inactive_driver_inventory(self) -> None:
        meter_settings = self._settings("le01mp")
        meter_snapshot = AgentState().snapshot(0, meter_settings)
        self.assertEqual(meter_snapshot["configured_points"], [])
        self.assertEqual(meter_snapshot["configured_devices"], ["LE01MP-201"])

        xjp_settings = self._settings("xjp60d")
        xjp_snapshot = AgentState().snapshot(0, xjp_settings)
        self.assertEqual(xjp_snapshot["configured_points"], ["106-03", "106-04"])
        self.assertEqual(xjp_snapshot["configured_devices"], [])

    def test_le01mp_mode_does_not_call_xjp60d_poller(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.settings = self._settings("le01mp")
        agent._sample_xjp60d = Mock()
        agent._sample_le01mp = Mock(
            side_effect=lambda _captured_at, records, _errors: records.append(
                self._record("f-and-f-le-01mp")
            )
        )

        records, error = DeviceAgent.sample_batch(agent)

        agent._sample_xjp60d.assert_not_called()
        agent._sample_le01mp.assert_called_once()
        self.assertEqual([record.source for record in records], ["f-and-f-le-01mp"])
        self.assertIsNone(error)

    def test_xjp60d_mode_does_not_call_le01mp_poller(self) -> None:
        agent = object.__new__(DeviceAgent)
        agent.settings = self._settings("xjp60d")
        agent._sample_xjp60d = Mock(
            side_effect=lambda _captured_at, records, _errors: records.append(
                self._record("dixell-xjp60d")
            )
        )
        agent._sample_le01mp = Mock()

        records, error = DeviceAgent.sample_batch(agent)

        agent._sample_xjp60d.assert_called_once()
        agent._sample_le01mp.assert_not_called()
        self.assertEqual([record.source for record in records], ["dixell-xjp60d"])
        self.assertIsNone(error)


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


if __name__ == "__main__":
    unittest.main()
