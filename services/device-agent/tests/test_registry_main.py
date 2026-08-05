from __future__ import annotations

import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from acquisition_registry import (
    AcquisitionRegistry,
    LifecycleMutation,
    build_initial_document,
)
from main import Settings
from registry_main import RegistryManagedDeviceAgent


def settings() -> Settings:
    return Settings(
        node_id="edge-01",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=5,
        database_path=Path("edge.db"),
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="modbus",
        serial_device="/dev/serial/by-id/test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (106, 4)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(200,),
    )


def registry() -> AcquisitionRegistry:
    return AcquisitionRegistry(
        build_initial_document(
            settings(),
            discovery_units=(106,),
            legacy_active_points=((106, 3), (106, 4)),
        )
    )


def agent_with_registry(value: AcquisitionRegistry) -> RegistryManagedDeviceAgent:
    agent = object.__new__(RegistryManagedDeviceAgent)
    agent._registry = value
    agent._registry_lock = threading.Lock()
    agent._bus_operation_lock = threading.Lock()
    agent.settings = settings()
    agent.acquisition_metrics = Mock()
    return agent


class RegistryPollingTests(unittest.TestCase):
    def test_xjp_sampling_calls_only_registry_eligible_points(self) -> None:
        current = registry()
        document, _ = current.with_mutations(
            device_mutations=(),
            target_mutations=(
                LifecycleMutation("xjp60d:106-04", "reserve"),
            ),
        )
        agent = agent_with_registry(AcquisitionRegistry(document))
        agent.xjp60d_reader = Mock()
        agent.xjp60d_reader.read_channel.return_value = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        records = []
        errors = []

        agent._sample_xjp60d("2026-08-05T00:00:00+00:00", records, errors)

        agent.xjp60d_reader.read_channel.assert_called_once_with(106, 3)
        self.assertEqual(errors, [])
        self.assertEqual([record.channel_id for record in records], ["106-03"])
        self.assertEqual([record.equipment_id for record in records], ["K106"])

    def test_le_sampling_calls_only_registry_eligible_metrics(self) -> None:
        current = registry()
        document, _ = current.with_mutations(
            device_mutations=(),
            target_mutations=(
                LifecycleMutation("le01mp:200-active-power", "disabled"),
                LifecycleMutation("le01mp:200-reactive-power", "retired"),
                LifecycleMutation("le01mp:200-apparent-power", "uninstalled"),
                LifecycleMutation("le01mp:200-power-factor", "discovery_only"),
            ),
        )
        agent = agent_with_registry(AcquisitionRegistry(document))
        agent.le01mp_reader = Mock()
        agent.le01mp_reader.read_metric.side_effect = lambda unit_id, key: Mock(
            metric=f"metric.{key}",
            value=1.0,
            unit="unit",
            quality="valid",
            raw_value=1,
        )
        records = []
        errors = []

        agent._sample_le01mp("2026-08-05T00:00:00+00:00", records, errors)

        requested = [call.args for call in agent.le01mp_reader.read_metric.call_args_list]
        self.assertIn((200, "voltage"), requested)
        self.assertIn((200, "current"), requested)
        self.assertNotIn((200, "active_power"), requested)
        self.assertNotIn((200, "reactive_power"), requested)
        self.assertNotIn((200, "apparent_power"), requested)
        self.assertNotIn((200, "power_factor"), requested)
        self.assertEqual(
            [record.channel_id for record in records],
            [f"{unit_id}-{key.replace('_', '-')}" for unit_id, key in requested],
        )

    def test_zero_eligible_targets_produces_zero_driver_calls(self) -> None:
        current = registry()
        target_mutations = tuple(
            LifecycleMutation(target.target_id, "disabled")
            for target in current.document.targets
            if target.lifecycle == "active"
        )
        document, _ = current.with_mutations(
            device_mutations=(),
            target_mutations=target_mutations,
        )
        agent = agent_with_registry(AcquisitionRegistry(document))
        agent.xjp60d_reader = Mock()
        agent.le01mp_reader = Mock()

        records, error = agent.sample_batch()

        self.assertEqual(records, [])
        self.assertIsNone(error)
        agent.xjp60d_reader.read_channel.assert_not_called()
        agent.le01mp_reader.read_metric.assert_not_called()
        agent.acquisition_metrics.begin_cycle.assert_called_once()
        agent.acquisition_metrics.complete_cycle.assert_called_once_with(
            interval_seconds=5,
            failed=False,
        )

    def test_registry_summary_separates_inventory_from_eligible_targets(self) -> None:
        current = registry()
        document, _ = current.with_mutations(
            device_mutations=(),
            target_mutations=(
                LifecycleMutation("xjp60d:106-04", "reserve"),
            ),
        )
        agent = agent_with_registry(AcquisitionRegistry(document))

        summary = agent.registry_summary()

        self.assertGreater(summary["inventory_targets"], summary["poll_eligible_targets"])
        self.assertEqual(summary["lifecycle_counts"]["reserve"], 1)


if __name__ == "__main__":
    unittest.main()
