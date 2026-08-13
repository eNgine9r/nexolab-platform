from __future__ import annotations

import logging
import os
import signal
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import Any

from adaptive_scheduler import (
    AdaptiveAcquisitionScheduler,
    ScheduledResult,
    SchedulerPolicy,
    SchedulerTarget,
)
from latest_values import LatestValueStore
from main import Settings, TelemetryRecord
from managed_main import LOG
from modbus_rtu import ModbusError
from registry_main import (
    RegistryManagedDeviceAgent,
    RegistryManagedHealthHandler,
)

LATEST_PATH = "/api/v1/acquisition-latest"


class AdaptiveRegistryDeviceAgent(RegistryManagedDeviceAgent):
    """Registry-managed Device Agent with adaptive per-target scheduling."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._publish_lock = threading.Lock()
        self.latest_values = LatestValueStore(settings.database_path)
        self.scheduler_policy = SchedulerPolicy.from_environment(
            legacy_interval_seconds=self.settings.sample_interval_seconds
        )
        self.scheduler = AdaptiveAcquisitionScheduler(
            self._registry_snapshot(),
            policy=self.scheduler_policy,
            latest_store=self.latest_values,
            read_target=self._read_scheduled_target,
            record_result=self._record_scheduled_result,
            stop_event=self.stop_event,
            bus_locks={
                bus.bus_id: self._bus_operation_lock
                for bus in self._registry_snapshot().document.buses
            },
        )

    def acquisition_snapshot(self) -> dict[str, Any]:
        payload = super().acquisition_snapshot()
        payload["polling_policy"] = "priority_adaptive_v1"
        payload["scheduler"] = self.scheduler.snapshot()
        return payload

    def health_snapshot(self) -> dict[str, Any]:
        payload = super().health_snapshot()
        payload["latest_values"] = self.scheduler.latest_summary()
        return payload

    def replace_active_points(
        self,
        points: tuple[tuple[int, int], ...],
    ) -> dict[str, Any]:
        super().replace_active_points(points)
        self.scheduler.reconcile(self._registry_snapshot())
        return self.configuration()

    def discover_xjp60d(self) -> dict[str, Any]:
        result = super().discover_xjp60d()
        self.scheduler.reconcile(self._registry_snapshot())
        return {**self.configuration(), "last_discovery": result["last_discovery"]}

    def update_registry(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        result = super().update_registry(payload, actor=actor)
        self.scheduler.reconcile(self._registry_snapshot())
        return result

    def configuration(self) -> dict[str, Any]:
        payload = super().configuration()
        scheduler = getattr(self, "scheduler", None)
        payload["target_diagnostics"] = (
            scheduler.target_diagnostics(device_family="xjp60d")
            if scheduler is not None
            else []
        )
        return payload

    @staticmethod
    def _source_for(target: SchedulerTarget) -> str:
        if target.device_family == "xjp60d":
            return "dixell-xjp60d"
        if target.device_family == "le01mp":
            return "f-and-f-le-01mp"
        raise RuntimeError(
            f"Unsupported scheduled device family: {target.device_family}"
        )

    @staticmethod
    def _equipment_for(target: SchedulerTarget) -> str:
        if target.device_family == "xjp60d":
            return f"K{target.unit_id}"
        if target.device_family == "le01mp":
            return f"LE01MP-{target.unit_id}"
        raise RuntimeError(
            f"Unsupported scheduled device family: {target.device_family}"
        )

    def _read_scheduled_target(
        self,
        target: SchedulerTarget,
    ) -> ScheduledResult:
        if self.modbus_client is None:
            raise RuntimeError("Modbus client was not initialized")
        captured_at = datetime.now(timezone.utc).isoformat()
        source = self._source_for(target)
        equipment_id = self._equipment_for(target)

        try:
            with self.modbus_client.instrumentation_scope(
                device_family=target.device_family,
                target_id=target.target_id,
                operation="normal",
            ):
                if target.device_family == "xjp60d":
                    if self.xjp60d_reader is None:
                        raise RuntimeError(
                            "XJP60D reader was not initialized"
                        )
                    channel = int(
                        target.key.removeprefix("channel-")
                    )
                    reading = self.xjp60d_reader.read_channel(
                        target.unit_id,
                        channel,
                    )
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
                    if self.le01mp_reader is None:
                        raise RuntimeError(
                            "LE-01MP reader was not initialized"
                        )
                    reading = self.le01mp_reader.read_metric(
                        target.unit_id,
                        target.key,
                    )
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
                "Scheduled read failed for %s: %s",
                target.target_id,
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

    def _record_scheduled_result(
        self,
        target: SchedulerTarget,
        result: ScheduledResult,
    ) -> None:
        del target
        record = result.record
        with self._publish_lock:
            publish_ok = self.publish_or_queue(record)
            errors = [
                value
                for value in (
                    result.error,
                    self.scheduler.current_error(),
                    (
                        "MQTT unavailable; telemetry queued locally"
                        if not publish_ok
                        else None
                    ),
                )
                if value
            ]
            self.state.update(
                last_sample_at=record.captured_at,
                samples_total=self.state.samples_total + 1,
                last_error="; ".join(dict.fromkeys(errors)) or None,
            )
            if (
                self.operational is not None
                and self.state.mqtt_connected
                and self.operational.publish_health_if_due() is False
            ):
                self.state.update(last_error="node health publish failed")

    def run(self) -> None:
        if self.settings.device_mode == "simulator":
            super().run()
            return

        self.connect()
        self.scheduler.start()
        LOG.info(
            "Starting adaptive device agent for %s with %s target(s)",
            self.settings.node_id,
            self._configured_logical_targets(),
        )
        try:
            while not self.stop_event.is_set():
                with self._publish_lock:
                    queue_size = self.queue.size()
                    flush_ok = self.flush_queue()
                    errors = [
                        value
                        for value in (
                            self.scheduler.current_error(),
                            (
                                "MQTT unavailable; telemetry queued locally"
                                if queue_size > 0 and not flush_ok
                                else None
                            ),
                        )
                        if value
                    ]
                    self.state.update(
                        last_error="; ".join(errors) or None
                    )
                    if (
                        self.operational is not None
                        and self.state.mqtt_connected
                        and self.operational.publish_health_if_due() is False
                    ):
                        self.state.update(
                            last_error="node health publish failed"
                        )
                self.stop_event.wait(1.0)
        finally:
            self.scheduler.stop()
            if self.modbus_client is not None:
                self.modbus_client.close()
            if self.operational is not None and self.state.mqtt_connected:
                self.operational.publish_graceful_offline()
            self.client.disconnect()
            self.client.loop_stop()


class AdaptiveRegistryHealthHandler(RegistryManagedHealthHandler):
    agent: AdaptiveRegistryDeviceAgent

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path == LATEST_PATH:
            self._send_json(
                HTTPStatus.OK,
                self.agent.scheduler.latest_snapshot(),
            )
            return
        super().do_GET()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = AdaptiveRegistryDeviceAgent(settings)
    AdaptiveRegistryHealthHandler.agent = agent
    server = ThreadingHTTPServer(
        (settings.health_host, settings.health_port),
        AdaptiveRegistryHealthHandler,
    )

    def stop(signum: int, frame: Any) -> None:
        del frame
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()
        threading.Thread(
            target=server.shutdown,
            daemon=True,
        ).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker = threading.Thread(
        target=agent.run,
        name="device-agent",
        daemon=True,
    )
    worker.start()
    LOG.info(
        "Adaptive health endpoint listening on %s:%s",
        settings.health_host,
        settings.health_port,
    )
    server.serve_forever(poll_interval=0.5)
    worker.join(timeout=10)


if __name__ == "__main__":
    main()
