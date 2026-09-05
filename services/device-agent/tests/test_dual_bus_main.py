from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from adaptive_scheduler import ScheduledResult, SchedulerTarget
from acquisition_registry import (
    AcquisitionRegistryStore,
    DeviceLifecycleMutation,
)
from commissioning_activation import CommissioningActivationRequest
from commissioning_preflight import PROFILES, PreflightBus, PreflightExecutionError
from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent
from main import Settings, TelemetryRecord
from rs485_buses import BUS_CONFIG_ENV


def settings(database_path: Path) -> Settings:
    return Settings(
        node_id="edge-01",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=5,
        database_path=database_path,
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="xjp60d",
        serial_device="/dev/serial/by-id/legacy-test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (126, 3)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(),
    )


def bus_payload() -> list[dict[str, object]]:
    return [
        {
            "bus_id": "rs485-kk1",
            "serial_device": "/host/dev/serial/by-id/usb-kk1",
            "unit_ids": [126],
        },
        {
            "bus_id": "rs485-kk2",
            "serial_device": "/host/dev/serial/by-id/usb-kk2",
            "unit_ids": [106],
        },
    ]


def embraco_bus_payload(
    *,
    embraco_units: list[int] | None = None,
) -> list[dict[str, object]]:
    return [
        {
            "bus_id": "rs485-main",
            "serial_device": "/host/dev/serial/by-id/usb-main",
            "unit_ids": [106, 126, 201],
        },
        {
            "bus_id": "rs485-embraco",
            "serial_device": "/host/dev/serial/by-id/usb-embraco",
            "unit_ids": [2] if embraco_units is None else embraco_units,
            "stopbits": 2,
        },
    ]


def persisted_document(database_path: Path) -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT document FROM acquisition_registry_state WHERE singleton = 1"
        ).fetchone()
    if row is None:
        raise AssertionError("Acquisition registry was not persisted")
    payload = json.loads(str(row[0]))
    if not isinstance(payload, dict):
        raise AssertionError("Persisted acquisition registry is not an object")
    return payload


def success_result(target: SchedulerTarget) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"event-{target.target_id}",
            node_id="edge-01",
            captured_at=datetime.now(timezone.utc).isoformat(),
            metric=target.metric,
            value=4.2,
            unit=target.unit,
            quality="valid",
            source="test",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=False,
    )


class DualBusAdaptiveRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.environment = patch.dict(
            os.environ,
            {
                BUS_CONFIG_ENV: json.dumps(bus_payload()),
                "XJP60D_DISCOVERY_UNITS": "106,126",
            },
            clear=False,
        )
        self.environment.start()
        self.agent = DualBusAdaptiveRegistryDeviceAgent(
            settings(self.database_path)
        )

    def tearDown(self) -> None:
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.close()
        self.environment.stop()
        self.temporary.cleanup()

    def test_commissioning_preflight_bus_lock_wait_is_bounded(self) -> None:
        agent = object.__new__(DualBusAdaptiveRegistryDeviceAgent)
        topology = Mock()
        topology.explicit = True
        agent.rs485_topology = topology
        client = Mock()
        lock = Mock()
        lock.acquire.return_value = False
        agent._bus_clients = {"rs485-main": client}
        agent._bus_operation_locks = {"rs485-main": lock}
        agent._bus_xjp60d_readers = {}
        agent._bus_le01mp_readers = {}
        agent._bus_embraco_readers = {}

        with self.assertRaises(PreflightExecutionError) as context:
            agent.preflight_read_profile(
                PROFILES["embraco-sync"],
                bus_id="rs485-main",
                unit_id=2,
                deadline_monotonic=time.monotonic() + 0.1,
            )

        self.assertEqual(context.exception.code, "bus_busy")
        lock.acquire.assert_called_once()
        client.instrumentation_scope.assert_not_called()

    def test_composition_uses_distinct_clients_locks_and_registry_bus_ids(self) -> None:
        self.assertIsNone(self.agent.modbus_client)
        self.assertEqual(
            set(self.agent._bus_clients),  # noqa: SLF001
            {"rs485-kk1", "rs485-kk2"},
        )
        self.assertIsNot(
            self.agent._bus_operation_locks["rs485-kk1"],  # noqa: SLF001
            self.agent._bus_operation_locks["rs485-kk2"],  # noqa: SLF001
        )
        self.assertEqual(
            self.agent._bus_clients["rs485-kk1"].port,  # noqa: SLF001
            "/host/dev/serial/by-id/usb-kk1",
        )
        self.assertEqual(
            self.agent._bus_clients["rs485-kk2"].port,  # noqa: SLF001
            "/host/dev/serial/by-id/usb-kk2",
        )
        devices = {
            item.device_id: item
            for item in self.agent._registry_snapshot().document.devices  # noqa: SLF001
        }
        self.assertEqual(devices["xjp60d-126"].bus_id, "rs485-kk1")
        self.assertEqual(devices["xjp60d-106"].bus_id, "rs485-kk2")
        targets = {
            item["target_id"]: item
            for item in self.agent.scheduler.snapshot()["targets"]
        }
        self.assertEqual(targets["xjp60d:126-03"]["bus_id"], "rs485-kk1")
        self.assertEqual(targets["xjp60d:106-03"]["bus_id"], "rs485-kk2")

    def test_scheduler_executes_two_due_buses_concurrently(self) -> None:
        barrier = threading.Barrier(2)
        barrier_passed: list[str] = []

        def read_target(target: SchedulerTarget) -> ScheduledResult:
            barrier.wait(timeout=1)
            barrier_passed.append(target.bus_id)
            return success_result(target)

        self.agent.scheduler._read_target = read_target  # noqa: SLF001
        self.agent.scheduler._record_result = lambda target, result: None  # noqa: SLF001
        self.agent.scheduler._latest_store = Mock()  # noqa: SLF001
        for job in self.agent.scheduler._jobs.values():  # noqa: SLF001
            job.next_deadline = 0

        results: list[bool] = []
        workers = [
            threading.Thread(
                target=lambda bus_id=bus_id: results.append(
                    self.agent.scheduler.run_once(bus_id)
                )
            )
            for bus_id in ("rs485-kk1", "rs485-kk2")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=2)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(sorted(barrier_passed), ["rs485-kk1", "rs485-kk2"])
        self.assertEqual(results, [True, True])

    def test_scheduled_target_dispatches_to_its_bus_reader(self) -> None:
        kk1_reader = Mock()
        kk2_reader = Mock()
        reading = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        kk1_reader.read_channel.return_value = reading
        kk2_reader.read_channel.return_value = reading
        self.agent._bus_xjp60d_readers = {  # noqa: SLF001
            "rs485-kk1": kk1_reader,
            "rs485-kk2": kk2_reader,
        }
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.instrumentation_scope = Mock(return_value=nullcontext())  # type: ignore[method-assign]

        targets = {
            job.target.target_id: job.target
            for job in self.agent.scheduler._jobs.values()  # noqa: SLF001
        }
        kk1 = self.agent._read_scheduled_target(targets["xjp60d:126-03"])
        kk2 = self.agent._read_scheduled_target(targets["xjp60d:106-03"])

        self.assertFalse(kk1.communication_failed)
        self.assertFalse(kk2.communication_failed)
        kk1_reader.read_channel.assert_called_once_with(126, 3)
        kk2_reader.read_channel.assert_called_once_with(106, 3)

    def test_explicit_discovery_scans_only_units_owned_by_each_bus(self) -> None:
        kk1_reader = Mock()
        kk2_reader = Mock()
        reading = Mock(
            value=4.2,
            unit="degC",
            quality="valid",
            alarm=None,
            raw_value=42,
            raw_status=0,
        )
        kk1_reader.read_channel.return_value = reading
        kk2_reader.read_channel.return_value = reading
        self.agent._bus_xjp60d_readers = {  # noqa: SLF001
            "rs485-kk1": kk1_reader,
            "rs485-kk2": kk2_reader,
        }
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.instrumentation_scope = Mock(return_value=nullcontext())  # type: ignore[method-assign]

        result = self.agent.discover_xjp60d()["last_discovery"]

        self.assertEqual(kk1_reader.read_channel.call_count, 6)
        self.assertEqual(kk2_reader.read_channel.call_count, 6)
        self.assertTrue(
            all(call.args[0] == 126 for call in kk1_reader.read_channel.call_args_list)
        )
        self.assertTrue(
            all(call.args[0] == 106 for call in kk2_reader.read_channel.call_args_list)
        )
        self.assertEqual(
            {item["bus_id"] for item in result["buses"]},
            {"rs485-kk1", "rs485-kk2"},
        )
        self.assertEqual(result["controller_count"], 2)

    def test_bus_diagnostics_never_claim_hardware_acceptance(self) -> None:
        payload = self.agent.acquisition_snapshot()
        buses = {item["bus_id"]: item for item in payload["rs485_buses"]}

        self.assertEqual(buses["rs485-kk1"]["acceptance_state"], "hardware_unverified")
        self.assertEqual(buses["rs485-kk2"]["acceptance_state"], "hardware_unverified")
        self.assertIn(
            buses["rs485-kk1"]["hardware_state"],
            {"present_unverified", "configured_unavailable"},
        )
        self.assertIsNotNone(buses["rs485-kk1"]["scheduler"])
        self.assertIsNotNone(buses["rs485-kk2"]["scheduler"])


class EmbracoBusPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.settings = replace(
            settings(self.database_path),
            device_mode="modbus",
            le01mp_unit_ids=(201,),
            embraco_unit_ids=(),
        )
        store = AcquisitionRegistryStore(self.database_path)
        registry = store.load_or_migrate(
            self.settings,
            discovery_units=(106, 126),
            legacy_active_points=self.settings.xjp60d_points,
        )
        self.baseline = store.update(
            registry,
            expected_revision=registry.revision,
            actor="test:fixture",
            reason="Preserve externally owned Unit 201 as disabled",
            device_mutations=(DeviceLifecycleMutation("le01mp-201", "disabled"),),
            target_mutations=(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def configured_settings(self) -> Settings:
        return replace(self.settings, embraco_unit_ids=(2,))

    @staticmethod
    def close_agent(agent: DualBusAdaptiveRegistryDeviceAgent) -> None:
        for client in agent._bus_clients.values():  # noqa: SLF001
            client.close()

    def test_explicit_embraco_bus_is_persisted_on_first_load_and_restart(self) -> None:
        environment = {
            BUS_CONFIG_ENV: json.dumps(embraco_bus_payload()),
            "XJP60D_DISCOVERY_UNITS": "106,126",
        }
        with patch.dict(os.environ, environment, clear=False):
            first = DualBusAdaptiveRegistryDeviceAgent(self.configured_settings())
            try:
                first_revision = first._registry_snapshot().revision  # noqa: SLF001
            finally:
                self.close_agent(first)

            first_payload = persisted_document(self.database_path)
            first_devices = {
                item["device_id"]: item
                for item in first_payload["devices"]  # type: ignore[index]
            }
            self.assertEqual(
                first_devices["embraco-2"]["bus_id"],
                "rs485-embraco",
            )
            self.assertEqual(first_devices["le01mp-201"]["lifecycle"], "disabled")
            self.assertEqual(first_devices["le01mp-201"]["bus_id"], "rs485-main")
            self.assertEqual(first_devices["xjp60d-106"]["bus_id"], "rs485-main")
            self.assertEqual(first_devices["xjp60d-126"]["bus_id"], "rs485-main")
            self.assertEqual(
                {item["bus_id"] for item in first_payload["buses"]},  # type: ignore[index]
                {"rs485-main", "rs485-embraco"},
            )

            restarted = DualBusAdaptiveRegistryDeviceAgent(
                self.configured_settings()
            )
            try:
                restarted_devices = {
                    item.device_id: item
                    for item in restarted._registry_snapshot().document.devices  # noqa: SLF001
                }
                self.assertEqual(
                    restarted_devices["embraco-2"].bus_id,
                    "rs485-embraco",
                )
                self.assertEqual(
                    restarted._registry_snapshot().revision,  # noqa: SLF001
                    first_revision,
                )
            finally:
                self.close_agent(restarted)

        restarted_payload = persisted_document(self.database_path)
        restarted_devices = {
            item["device_id"]: item
            for item in restarted_payload["devices"]  # type: ignore[index]
        }
        self.assertEqual(
            restarted_devices["embraco-2"]["bus_id"],
            "rs485-embraco",
        )
        baseline_targets = {
            item.target_id: item.lifecycle
            for item in self.baseline.document.targets
        }
        restarted_bus1_devices = {
            device_id
            for device_id, device in restarted_devices.items()
            if device["bus_id"] == "rs485-main"
        }
        restarted_bus1_targets = {
            item["target_id"]: item["lifecycle"]
            for item in restarted_payload["targets"]  # type: ignore[index]
            if item["device_id"] in restarted_bus1_devices
        }
        self.assertEqual(restarted_bus1_targets, baseline_targets)
        baseline_intervals = {
            item.device_family: item.interval_seconds
            for item in self.baseline.document.cadence.family_defaults
        }
        restarted_intervals = {
            item["device_family"]: item["interval_seconds"]
            for item in restarted_payload["cadence"]["family_defaults"]  # type: ignore[index]
            if item["bus_id"] == "rs485-main"
        }
        self.assertEqual(restarted_intervals, baseline_intervals)

    def test_missing_embraco_bus_ownership_rolls_back_registry_mutation(self) -> None:
        before = persisted_document(self.database_path)
        environment = {
            BUS_CONFIG_ENV: json.dumps(
                embraco_bus_payload(embraco_units=[])
            ),
            "XJP60D_DISCOVERY_UNITS": "106,126",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(
                ValueError,
                "Unit ID 2 has no configured physical bus",
            ):
                DualBusAdaptiveRegistryDeviceAgent(self.configured_settings())

        self.assertEqual(persisted_document(self.database_path), before)

    def test_conflicting_explicit_unit_ownership_fails_before_registry_mutation(self) -> None:
        before = persisted_document(self.database_path)
        payload = embraco_bus_payload()
        payload[0]["unit_ids"] = [2, 106, 126, 201]
        environment = {
            BUS_CONFIG_ENV: json.dumps(payload),
            "XJP60D_DISCOVERY_UNITS": "106,126",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(
                ValueError,
                "Unit ID 2 is assigned to both",
            ):
                DualBusAdaptiveRegistryDeviceAgent(self.configured_settings())

        self.assertEqual(persisted_document(self.database_path), before)


class CommissioningActivationRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"
        self.environment = patch.dict(
            os.environ,
            {
                BUS_CONFIG_ENV: json.dumps(bus_payload()),
                "XJP60D_DISCOVERY_UNITS": "106,126",
            },
            clear=False,
        )
        self.environment.start()
        self.agent = DualBusAdaptiveRegistryDeviceAgent(settings(self.database_path))

    def tearDown(self) -> None:
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.close()
        self.environment.stop()
        self.temporary.cleanup()

    def _activation_request(self, *, action: str = "activate") -> CommissioningActivationRequest:
        return CommissioningActivationRequest(
            activation_id="activation-xjp-125",
            action=action,
            node_id="edge-01",
            bus_id="rs485-kk1",
            stable_transport_identifier="/dev/serial/by-id/usb-kk1",
            unit_id=125,
            profile_id="dixell-xjp60d",
            profile_version="dixell-xjp60d-fc03-v1",
        )

    def _allow_activation_adapter(self) -> None:
        self.agent.preflight_bus = lambda bus_id: PreflightBus(
            bus_id=bus_id,
            serial_device="/host/dev/serial/by-id/usb-kk1",
            path_present=True,
        )

    def test_commissioning_activation_enrolls_new_unit_on_verified_bus_and_is_idempotent(self) -> None:
        self._allow_activation_adapter()
        first = self.agent.commissioning_activation(self._activation_request())
        repeated = self.agent.commissioning_activation(self._activation_request())

        self.assertEqual(first["state"], "active")
        self.assertEqual(repeated["state"], "active")
        self.assertEqual(first["registry_revision"], repeated["registry_revision"])
        self.assertEqual(first["modbus_writes"], "none")
        self.assertEqual(first["hardware_writes"], "none")
        registry = self.agent._registry_snapshot()  # noqa: SLF001
        devices = {item.device_id: item for item in registry.document.devices}
        self.assertEqual(devices["xjp60d-125"].bus_id, "rs485-kk1")
        self.assertEqual(devices["xjp60d-125"].lifecycle, "active")
        targets = [item for item in registry.document.targets if item.device_id == "xjp60d-125"]
        self.assertEqual(len(targets), 6)
        self.assertTrue(all(item.lifecycle == "active" and item.function == 3 for item in targets))

    def test_commissioning_activation_rollback_restores_non_polling_state(self) -> None:
        self._allow_activation_adapter()
        self.agent.commissioning_activation(self._activation_request())
        rolled = self.agent.commissioning_activation(self._activation_request(action="rollback"))

        self.assertEqual(rolled["state"], "rolled_back")
        registry = self.agent._registry_snapshot()  # noqa: SLF001
        devices = {item.device_id: item for item in registry.document.devices}
        self.assertEqual(devices["xjp60d-125"].lifecycle, "discovery_only")
        targets = [item for item in registry.document.targets if item.device_id == "xjp60d-125"]
        self.assertTrue(all(item.lifecycle == "discovery_only" for item in targets))
        self.assertFalse(any(item.device_id == "xjp60d-125" for item in registry.eligible_targets()))

    def test_dynamic_commissioning_bus_assignment_survives_restart(self) -> None:
        self._allow_activation_adapter()
        self.agent.commissioning_activation(self._activation_request())
        for client in self.agent._bus_clients.values():  # noqa: SLF001
            client.close()
        restarted = DualBusAdaptiveRegistryDeviceAgent(settings(self.database_path))
        try:
            devices = {
                item.device_id: item
                for item in restarted._registry_snapshot().document.devices  # noqa: SLF001
            }
            self.assertEqual(devices["xjp60d-125"].bus_id, "rs485-kk1")
            self.assertEqual(devices["xjp60d-125"].lifecycle, "active")
            self.assertEqual(restarted.preflight_unit_owner(125), "rs485-kk1")
        finally:
            for client in restarted._bus_clients.values():  # noqa: SLF001
                client.close()

if __name__ == "__main__":
    unittest.main()
