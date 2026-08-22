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

from adaptive_main import (
    AdaptiveRegistryDeviceAgent,
    AdaptiveRegistryHealthHandler,
)
from adaptive_scheduler import (
    AdaptiveAcquisitionScheduler,
    ScheduledResult,
    SchedulerTarget,
)
from le01mp import LE01MPReader
from main import (
    Settings,
    TelemetryRecord,
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
from rs485_buses import RS485BusTopology
from xjp60d import XJP60DReader


class DualBusAdaptiveRegistryDeviceAgent(AdaptiveRegistryDeviceAgent):
    """Adaptive Device Agent with one transport and operation lock per RS-485 bus."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.rs485_topology = RS485BusTopology.from_environment(
            self.settings,
            self._registry_snapshot(),
        )
        self._bus_clients: dict[str, ModbusRTUClient] = {}
        self._bus_xjp60d_readers: dict[str, XJP60DReader] = {}
        self._bus_le01mp_readers: dict[str, LE01MPReader] = {}
        self._bus_operation_locks: dict[str, threading.Lock] = {}

        # No explicit topology means exact legacy behavior: the superclass owns
        # the existing singular client, reader and scheduler path.
        if not self.rs485_topology.explicit:
            return

        with self._registry_lock:
            self._registry = self.rs485_topology.bind_registry(self._registry)

        self._bus_operation_locks = {
            binding.bus_id: threading.Lock()
            for binding in self.rs485_topology.bindings
        }
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

        # The base client is deliberately retired in explicit multi-bus mode so
        # no code path can accidentally serialize both buses through one port.
        if self.modbus_client is not None:
            self.modbus_client.close()
        self.modbus_client = None
        self.xjp60d_reader = None
        self.le01mp_reader = None

        self.scheduler = AdaptiveAcquisitionScheduler(
            self._registry_snapshot(),
            policy=self.scheduler_policy,
            latest_store=self.latest_values,
            read_target=self._read_scheduled_target,
            record_result=self._record_scheduled_result,
            stop_event=self.stop_event,
            bus_locks=self._bus_operation_locks,
        )

    def _logical_bus_observer(self, bus_id: str):  # type: ignore[no-untyped-def]
        def observe(measurement: ModbusRequestMeasurement) -> None:
            self.acquisition_metrics.observe(
                replace(measurement, bus=bus_id)
            )

        return observe

    def acquisition_snapshot(self) -> dict[str, Any]:
        payload = super().acquisition_snapshot()
        topology = getattr(self, "rs485_topology", None)
        if topology is None:
            return payload
        scheduler = payload.get("scheduler")
        payload["rs485_buses"] = topology.diagnostics(
            self._registry_snapshot(),
            scheduler_snapshot=(scheduler if isinstance(scheduler, dict) else None),
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
                        item["unit_id"]
                        for item in available_points + unavailable_points
                    }
                ),
                "available_points": available_points,
                "unavailable_points": unavailable_points,
                "controller_errors": controller_errors,
                "buses": bus_results,
            }
            # Explicit topology owns bus assignment. Discovery remains read-only
            # evidence and never performs a hidden cross-bus enrollment/rebind.
            self._point_store.save_last_discovery(result)
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
