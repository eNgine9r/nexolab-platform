from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from typing import Any

from acquisition_capacity import BusCapacityProfile
from adaptive_main import (
    AdaptiveRegistryDeviceAgent,
    AdaptiveRegistryHealthHandler,
)
from adaptive_scheduler import (
    AdaptiveAcquisitionScheduler,
    ScheduledResult,
    SchedulerTarget,
)
from dual_bus_registry import TopologyAwareEnrollmentStore
from embraco import EmbracoSyncReader
from le01mp import LE01MPReader
from main import (
    Settings,
    TelemetryRecord,
    mode_uses_embraco,
    mode_uses_le01mp,
    mode_uses_xjp60d,
    run_agent_with_health_server,
)
from managed_main import (
    DiscoveryAlreadyRunningError,
    LOG,
    XJP60DDiscoveryScanner,
)
from modbus_rtu import ModbusError, ModbusRTUClient, ModbusRequestMeasurement
from rs485_bus_metrics import RS485BusRequestMetrics
from rs485_buses import RS485BusTopology
from xjp60d import XJP60DReader


class _AllBusOperationLock:
    """Acquire every configured physical bus lock in deterministic order."""

    def __init__(self, locks: dict[str, threading.Lock]) -> None:
        self._locks = tuple(locks[bus_id] for bus_id in sorted(locks))

    def __enter__(self) -> "_AllBusOperationLock":
        acquired: list[threading.Lock] = []
        try:
            for lock in self._locks:
                lock.acquire()
                acquired.append(lock)
        except BaseException:
            for lock in reversed(acquired):
                lock.release()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        for lock in reversed(self._locks):
            lock.release()


class DualBusAdaptiveRegistryDeviceAgent(AdaptiveRegistryDeviceAgent):
    """Adaptive Device Agent with one transport and operation lock per RS-485 bus."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.rs485_topology = RS485BusTopology.from_environment(
            self.settings,
            self._registry_snapshot(),
        )
        self.rs485_bus_metrics = RS485BusRequestMetrics()
        self._bus_clients: dict[str, ModbusRTUClient] = {}
        self._bus_xjp60d_readers: dict[str, XJP60DReader] = {}
        self._bus_le01mp_readers: dict[str, LE01MPReader] = {}
        self._bus_embraco_readers: dict[str, EmbracoSyncReader] = {}
        self._bus_operation_locks: dict[str, threading.Lock] = {}
        self._topology_enrollment_store: TopologyAwareEnrollmentStore | None = None

        if not self.rs485_topology.explicit:
            return

        with self._registry_lock:
            self._registry = self.rs485_topology.bind_registry(self._registry)

        self._bus_operation_locks = {
            binding.bus_id: threading.Lock()
            for binding in self.rs485_topology.bindings
        }
        self._bus_operation_lock = _AllBusOperationLock(  # type: ignore[assignment]
            self._bus_operation_locks
        )
        self._topology_enrollment_store = TopologyAwareEnrollmentStore(
            settings.database_path,
            bus_for_unit=self.rs485_topology.bus_for_unit,
        )

        for binding in self.rs485_topology.bindings:
            client = ModbusRTUClient(
                binding.serial_device,
                baudrate=binding.baudrate,
                parity=binding.parity,
                stopbits=binding.stopbits,
                timeout=binding.timeout_seconds,
                retries=binding.retries,
                request_observer=self._logical_bus_observer(binding.bus_id),
            )
            self._bus_clients[binding.bus_id] = client
            if mode_uses_xjp60d(self.settings.device_mode):
                self._bus_xjp60d_readers[binding.bus_id] = XJP60DReader(
                    client,
                    scale=self.settings.xjp60d_scale,
                    unit="degC",
                )
            if mode_uses_le01mp(self.settings.device_mode):
                self._bus_le01mp_readers[binding.bus_id] = LE01MPReader(client)
            if mode_uses_embraco(self.settings.device_mode):
                self._bus_embraco_readers[binding.bus_id] = EmbracoSyncReader(
                    client,
                    temperature_scale=self.settings.embraco_temperature_scale,
                    control_scale=self.settings.embraco_control_scale,
                )

        if self.modbus_client is not None:
            self.modbus_client.close()
        self.modbus_client = None
        self.xjp60d_reader = None
        self.le01mp_reader = None
        self.embraco_reader = None

        self.scheduler = AdaptiveAcquisitionScheduler(
            self._registry_snapshot(),
            policy=self.scheduler_policy,
            latest_store=self.latest_values,
            read_target=self._read_scheduled_target,
            record_result=self._record_scheduled_result,
            stop_event=self.stop_event,
            bus_locks=self._bus_operation_locks,
        )

    def capacity_profiles(
        self,
        registry: Any = None,
    ) -> dict[str, BusCapacityProfile]:
        topology = getattr(self, "rs485_topology", None)
        metrics = getattr(self, "rs485_bus_metrics", None)
        if topology is None or metrics is None or not topology.explicit:
            return super().capacity_profiles(registry)

        profiles: dict[str, BusCapacityProfile] = {}
        for binding in topology.bindings:
            snapshot = metrics.snapshot(binding.bus_id)
            latency = snapshot["latency_ms"]
            sample_count = int(latency["sample_count"])
            physical_requests = int(snapshot["physical_requests_total"])
            retry_attempts = int(snapshot["retry_attempts_total"])
            profiles[binding.bus_id] = BusCapacityProfile(
                bus_id=binding.bus_id,
                baudrate=binding.baudrate,
                parity=binding.parity,
                stopbits=binding.stopbits,
                timeout_seconds=binding.timeout_seconds,
                retries=binding.retries,
                observed_p95_seconds=(
                    float(latency["p95"]) / 1000.0
                    if sample_count > 0
                    else None
                ),
                observed_retry_rate=(
                    retry_attempts / physical_requests
                    if physical_requests > 0
                    else None
                ),
                observed_sample_count=sample_count,
            )
        return profiles

    def _logical_bus_observer(self, bus_id: str):  # type: ignore[no-untyped-def]
        def observe(measurement: ModbusRequestMeasurement) -> None:
            logical = replace(measurement, bus=bus_id)
            self.acquisition_metrics.observe(logical)
            self.rs485_bus_metrics.observe(logical)

        return observe

    def acquisition_snapshot(self) -> dict[str, Any]:
        payload = super().acquisition_snapshot()
        topology = getattr(self, "rs485_topology", None)
        if topology is None:
            return payload
        scheduler = payload.get("scheduler")
        buses = topology.diagnostics(
            self._registry_snapshot(),
            scheduler_snapshot=(scheduler if isinstance(scheduler, dict) else None),
        )
        if topology.explicit:
            for bus in buses:
                bus["requests"] = self.rs485_bus_metrics.snapshot(bus["bus_id"])
        payload["rs485_buses"] = buses
        return payload

    def health_snapshot(self) -> dict[str, Any]:
        payload = super().health_snapshot()
        topology = getattr(self, "rs485_topology", None)
        if topology is None or not topology.explicit:
            return payload
        acquisition = payload.get("acquisition")
        buses = (
            acquisition.get("rs485_buses", [])
            if isinstance(acquisition, dict)
            else []
        )
        missing_active = [
            item["bus_id"]
            for item in buses
            if isinstance(item, dict)
            and item.get("active_target_count", 0) > 0
            and item.get("device_path_present") is False
        ]
        if missing_active:
            payload["status"] = "error"
            bus_error = (
                "active RS-485 bus device unavailable: "
                + ", ".join(sorted(missing_active))
            )
            current_error = payload.get("last_error")
            payload["last_error"] = "; ".join(
                dict.fromkeys(
                    value
                    for value in (bus_error, current_error)
                    if isinstance(value, str) and value
                )
            )
        return payload

    def _read_scheduled_target(
        self,
        target: SchedulerTarget,
    ) -> ScheduledResult:
        topology = getattr(self, "rs485_topology", None)
        if topology is None or not topology.explicit:
            return super()._read_scheduled_target(target)

        client = self._bus_clients.get(target.bus_id)
        if client is None:
            raise RuntimeError(
                f"RS-485 bus {target.bus_id} has no configured transport"
            )
        captured_at = datetime.now(timezone.utc).isoformat()
        source = self._source_for(target)
        equipment_id = self._equipment_for(target)

        try:
            with client.instrumentation_scope(
                device_family=target.device_family,
                target_id=target.target_id,
                operation="normal",
            ):
                if target.device_family == "xjp60d":
                    reader = self._bus_xjp60d_readers.get(target.bus_id)
                    if reader is None:
                        raise RuntimeError(
                            f"XJP60D reader is unavailable for {target.bus_id}"
                        )
                    channel = int(target.key.removeprefix("channel-"))
                    reading = reader.read_channel(target.unit_id, channel)
                    record = TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric="temperature.probe",
                        value=reading.value,
                        unit=reading.unit,
                        quality=reading.quality,
                        source=source,
                        equipment_id=equipment_id,
                        channel_id=target.telemetry_channel_id,
                        alarm=reading.alarm,
                        raw_value=reading.raw_value,
                        raw_status=reading.raw_status,
                    )
                elif target.device_family == "le01mp":
                    reader = self._bus_le01mp_readers.get(target.bus_id)
                    if reader is None:
                        raise RuntimeError(
                            f"LE-01MP reader is unavailable for {target.bus_id}"
                        )
                    reading = reader.read_metric(target.unit_id, target.key)
                    record = TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric=reading.metric,
                        value=reading.value,
                        unit=reading.unit,
                        quality=reading.quality,
                        source=source,
                        equipment_id=equipment_id,
                        channel_id=target.telemetry_channel_id,
                        raw_value=reading.raw_value,
                    )
                elif target.device_family == "embraco":
                    reader = self._bus_embraco_readers.get(target.bus_id)
                    if reader is None:
                        raise RuntimeError(
                            f"Embraco Sync reader is unavailable for {target.bus_id}"
                        )
                    reading = reader.read_metric(target.unit_id, target.key)
                    record = TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric=reading.metric,
                        value=reading.value,
                        unit=reading.unit,
                        quality=reading.quality,
                        source=source,
                        equipment_id=equipment_id,
                        channel_id=target.telemetry_channel_id,
                        raw_value=reading.raw_value,
                    )
                else:
                    raise RuntimeError(
                        "Unsupported scheduled device family: "
                        f"{target.device_family}"
                    )
        except (ModbusError, OSError, RuntimeError) as error:
            LOG.warning(
                "Scheduled read failed for %s on %s: %s",
                target.target_id,
                target.bus_id,
                error,
            )
            return ScheduledResult(
                record=TelemetryRecord(
                    event_id=str(uuid.uuid4()),
                    node_id=self.settings.node_id,
                    captured_at=captured_at,
                    metric=target.metric,
                    value=None,
                    unit=target.unit,
                    quality="communication_error",
                    source=source,
                    equipment_id=equipment_id,
                    channel_id=target.telemetry_channel_id,
                ),
                communication_failed=True,
                error=f"{target.telemetry_channel_id}: {error}"[:500],
            )

        return ScheduledResult(
            record=record,
            communication_failed=False,
        )

    @staticmethod
    def _responsive_bus_assignments(
        discovery: dict[str, Any],
    ) -> dict[int, str]:
        assignments: dict[int, str] = {}
        for key in ("available_points", "unavailable_points"):
            points = discovery.get(key, [])
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                unit_id = point.get("unit_id")
                bus_id = point.get("bus_id")
                raw_status = point.get("raw_status")
                if (
                    not isinstance(unit_id, int)
                    or isinstance(unit_id, bool)
                    or not isinstance(bus_id, str)
                    or not bus_id
                    or raw_status is None
                ):
                    continue
                previous = assignments.get(unit_id)
                if previous is not None and previous != bus_id:
                    raise ValueError(
                        f"Discovery returned Unit ID {unit_id} on multiple buses"
                    )
                assignments[unit_id] = bus_id
        return assignments

    def discover_xjp60d(self) -> dict[str, Any]:
        if not self.rs485_topology.explicit:
            return super().discover_xjp60d()
        if not mode_uses_xjp60d(self.settings.device_mode):
            raise RuntimeError("XJP60D discovery is unavailable in this device mode")
        if not self._discovery_lock.acquire(blocking=False):
            raise DiscoveryAlreadyRunningError

        started = time.monotonic()
        scanned_at = datetime.now(timezone.utc).isoformat()
        available_points: list[dict[str, Any]] = []
        unavailable_points: list[dict[str, Any]] = []
        controller_errors: list[dict[str, Any]] = []
        bus_results: list[dict[str, Any]] = []
        try:
            for binding in self.rs485_topology.bindings:
                units = tuple(
                    unit_id
                    for unit_id in self.discovery_units
                    if unit_id in binding.unit_ids
                )
                if not units:
                    continue
                client = self._bus_clients[binding.bus_id]
                reader = self._bus_xjp60d_readers[binding.bus_id]
                with self._bus_operation_locks[binding.bus_id]:
                    with client.instrumentation_scope(
                        device_family="xjp60d",
                        target_id=f"catalog-discovery:{binding.bus_id}",
                        operation="discovery",
                    ):
                        result = XJP60DDiscoveryScanner(reader, units).scan()

                bus_available = [
                    {**item, "bus_id": binding.bus_id}
                    for item in result["available_points"]
                ]
                bus_unavailable = [
                    {**item, "bus_id": binding.bus_id}
                    for item in result["unavailable_points"]
                ]
                bus_errors = [
                    {**item, "bus_id": binding.bus_id}
                    for item in result["controller_errors"]
                ]
                available_points.extend(bus_available)
                unavailable_points.extend(bus_unavailable)
                controller_errors.extend(bus_errors)
                bus_results.append(
                    {
                        "bus_id": binding.bus_id,
                        "controller_count": result["controller_count"],
                        "reachable_controller_count": result[
                            "reachable_controller_count"
                        ],
                        "duration_ms": result["duration_ms"],
                    }
                )

            result = {
                "scanned_at": scanned_at,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "controller_count": sum(
                    item["controller_count"] for item in bus_results
                ),
                "reachable_controller_count": len(
                    {
                        (item["bus_id"], item["unit_id"])
                        for item in available_points + unavailable_points
                    }
                ),
                "available_points": available_points,
                "unavailable_points": unavailable_points,
                "controller_errors": controller_errors,
                "buses": bus_results,
            }
            self._point_store.save_last_discovery(result)

            assignments = self._responsive_bus_assignments(result)
            changed = False
            enrollment_store = self._topology_enrollment_store
            if assignments and enrollment_store is not None:
                with self._bus_operation_lock, self._registry_lock:
                    current = self._registry
                    enrolled = enrollment_store.enroll_xjp60d(
                        current,
                        expected_revision=current.revision,
                        unit_ids=tuple(sorted(assignments)),
                        actor="service:xjp60d-discovery",
                        reason=(
                            "Enroll responsive XJP60D units on explicit read-only RS-485 buses"
                        ),
                    )
                    changed = enrolled.revision != current.revision
                    if changed:
                        self._registry = enrolled
                        self._sync_legacy_xjp60d_state(enrolled)
            if changed:
                self.scheduler.reconcile(self._registry_snapshot())
            return {**self.configuration(), "last_discovery": result}
        finally:
            self._discovery_lock.release()

    def run(self) -> None:
        try:
            super().run()
        finally:
            for client in self._bus_clients.values():
                client.close()


class DualBusAdaptiveRegistryHealthHandler(AdaptiveRegistryHealthHandler):
    agent: DualBusAdaptiveRegistryDeviceAgent


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = DualBusAdaptiveRegistryDeviceAgent(settings)
    DualBusAdaptiveRegistryHealthHandler.agent = agent
    server = ThreadingHTTPServer(
        (settings.health_host, settings.health_port),
        DualBusAdaptiveRegistryHealthHandler,
    )

    def stop(signum: int, frame: Any) -> None:
        del frame
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    run_agent_with_health_server(
        agent,
        server,
        endpoint_label="Dual-bus adaptive health endpoint",
    )


if __name__ == "__main__":
    main()
