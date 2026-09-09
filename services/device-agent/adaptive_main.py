from __future__ import annotations

import logging
import os
import signal
import sqlite3
import threading
import time
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
from acquisition_registry import AcquisitionRegistryStore
from latest_values import LatestValueStore
from main import (
    Settings,
    TelemetryRecord,
    run_agent_with_health_server,
)
from managed_main import LOG
from modbus_rtu import ModbusError
from registry_main import (
    RegistryManagedDeviceAgent,
    RegistryManagedHealthHandler,
)

LATEST_PATH = "/api/v1/acquisition-latest"
SQLITE_BUSY_SUPERVISOR_GRACE_CYCLES = 3


def _is_sqlite_busy_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).casefold()
    return "locked" in message or "busy" in message


class AdaptiveRegistryDeviceAgent(RegistryManagedDeviceAgent):
    """Registry-managed Device Agent with adaptive per-target scheduling."""

    def __init__(
        self,
        settings: Settings,
        *,
        registry_store: AcquisitionRegistryStore | None = None,
    ) -> None:
        super().__init__(settings, registry_store=registry_store)
        self._publish_lock = threading.Lock()
        self._sqlite_busy_supervisor_consecutive = 0
        self._sqlite_busy_supervisor_limit = SQLITE_BUSY_SUPERVISOR_GRACE_CYCLES
        self._sqlite_busy_supervisor_delay_seconds = 1.0
        self._fatal_persistence_error: Exception | None = None
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
            persistence_error_handler=self._handle_latest_persistence_error,
            latest_persistence_retry_attempts=SQLITE_BUSY_SUPERVISOR_GRACE_CYCLES,
            latest_persistence_retry_delay_seconds=self._sqlite_busy_supervisor_delay_seconds,
            bus_locks={
                bus.bus_id: self._bus_operation_lock
                for bus in self._registry_snapshot().document.buses
            },
        )

    def acquisition_snapshot(self) -> dict[str, Any]:
        payload = super().acquisition_snapshot()
        payload["polling_policy"] = "persisted_device_cadence_v2"
        payload["cadence_policy_revision"] = self._registry_snapshot().revision
        payload["capacity_validation"] = self.capacity_configuration()
        payload["scheduler"] = self.scheduler.snapshot()
        return payload

    def health_snapshot(self) -> dict[str, Any]:
        payload = super().health_snapshot()
        latest_summary, latest_summary_stale = self.latest_values.health_summary()
        payload["latest_values"] = latest_summary
        base_contention = payload.get("sqlite_contention", {})
        queue_contention = (
            base_contention.get("queue", self.queue.contention_snapshot())
            if isinstance(base_contention, dict)
            else self.queue.contention_snapshot()
        )
        queue_depth_stale = (
            bool(base_contention.get("queue_depth_stale", False))
            if isinstance(base_contention, dict)
            else False
        )
        latest_contention = self.latest_values.contention_snapshot()
        supervisor_consecutive = int(
            getattr(self, "_sqlite_busy_supervisor_consecutive", 0)
        )
        supervisor_limit = int(
            getattr(
                self,
                "_sqlite_busy_supervisor_limit",
                SQLITE_BUSY_SUPERVISOR_GRACE_CYCLES,
            )
        )
        payload["sqlite_contention"] = {
            "schema_version": 1,
            "queue_depth_stale": queue_depth_stale,
            "latest_summary_stale": latest_summary_stale,
            "queue": queue_contention,
            "latest_values": latest_contention,
            "supervisor": {
                "consecutive_busy_cycles": supervisor_consecutive,
                "fail_closed_after_cycles": supervisor_limit,
            },
        }

        errors = [payload.get("last_error")]
        scheduler = payload["acquisition"]["scheduler"]
        if not scheduler.get("workers_healthy", False):
            payload["status"] = "error"
            errors.insert(0, self.scheduler.current_error())
        if latest_summary_stale or int(
            latest_contention.get("consecutive_exhaustions", 0)
        ) > 0:
            if payload.get("status") == "ok":
                payload["status"] = "degraded"
            errors.insert(0, "SQLite latest-value store is lock-contended")
        if supervisor_consecutive > 0:
            if payload.get("status") == "ok":
                payload["status"] = "degraded"
            errors.insert(0, "SQLite queue persistence is lock-contended")
        payload["last_error"] = "; ".join(
            dict.fromkeys(value for value in errors if value)
        ) or None
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

    def update_cadence(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        result = super().update_cadence(payload, actor=actor)
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
        if target.device_family == "embraco":
            return "embraco-sync"
        raise RuntimeError(
            f"Unsupported scheduled device family: {target.device_family}"
        )

    @staticmethod
    def _equipment_for(target: SchedulerTarget) -> str:
        if target.device_family == "xjp60d":
            return f"K{target.unit_id}"
        if target.device_family == "le01mp":
            return f"LE01MP-{target.unit_id}"
        if target.device_family == "embraco":
            return f"EMBRACO-{target.unit_id}"
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
                elif target.device_family == "embraco":
                    if self.embraco_reader is None:
                        raise RuntimeError(
                            "Embraco Sync reader was not initialized"
                        )
                    reading = self.embraco_reader.read_metric(
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

    def _raise_fatal_persistence_error(self) -> None:
        error = getattr(self, "_fatal_persistence_error", None)
        if error is not None:
            raise error

    def _mark_fatal_persistence_error(
        self,
        error: Exception,
        *,
        operation: str,
    ) -> None:
        self._fatal_persistence_error = error
        self.state.update(
            last_error=f"SQLite {operation} persistence failed: {error}"
        )
        self.stop_event.set()

    def _handle_latest_persistence_error(
        self,
        error: Exception,
        attempt: int,
        limit: int,
    ) -> bool:
        if isinstance(error, sqlite3.OperationalError) and _is_sqlite_busy_error(error):
            if attempt < limit:
                message = (
                    "SQLite latest-value lock contention; "
                    f"outer retry {attempt}/{limit}"
                )
                self.state.update(last_error=message)
                LOG.warning("%s; retaining scheduled result before publication", message)
                return True
            self._mark_fatal_persistence_error(error, operation="latest-value")
            LOG.error(
                "SQLite latest-value lock contention exhausted outer retry %s/%s; "
                "failing closed before telemetry publication",
                attempt,
                limit,
            )
            return False
        self._mark_fatal_persistence_error(error, operation="latest-value")
        return False

    def _register_busy_supervisor_cycle(
        self,
        error: sqlite3.OperationalError,
        *,
        operation: str,
    ) -> bool:
        consecutive = int(
            getattr(self, "_sqlite_busy_supervisor_consecutive", 0)
        ) + 1
        limit = int(
            getattr(
                self,
                "_sqlite_busy_supervisor_limit",
                SQLITE_BUSY_SUPERVISOR_GRACE_CYCLES,
            )
        )
        self._sqlite_busy_supervisor_consecutive = consecutive
        message = (
            f"SQLite {operation} lock contention; "
            f"supervisor cycle {consecutive}/{limit}"
        )
        self.state.update(last_error=message)
        if consecutive >= limit:
            self._mark_fatal_persistence_error(error, operation=operation)
            LOG.error("%s; failing closed after bounded grace", message)
            return False
        LOG.warning("%s; keeping runtime alive", message)
        return True

    def _reset_busy_supervisor(self) -> None:
        consecutive = int(
            getattr(self, "_sqlite_busy_supervisor_consecutive", 0)
        )
        if consecutive:
            LOG.info(
                "SQLite persistence contention recovered after %s supervisor cycle(s)",
                consecutive,
            )
        self._sqlite_busy_supervisor_consecutive = 0

    def _publish_scheduled_record(self, record: TelemetryRecord) -> bool:
        while True:
            self._raise_fatal_persistence_error()
            try:
                published = self.publish_or_queue(record)
            except sqlite3.OperationalError as error:
                if not _is_sqlite_busy_error(error):
                    self._mark_fatal_persistence_error(
                        error, operation="telemetry queue"
                    )
                    raise
                if not self._register_busy_supervisor_cycle(
                    error, operation="telemetry queue"
                ):
                    raise
                delay = float(
                    getattr(self, "_sqlite_busy_supervisor_delay_seconds", 1.0)
                )
                if delay:
                    time.sleep(delay)
                continue
            self._reset_busy_supervisor()
            return published

    def _record_scheduled_result(
        self,
        target: SchedulerTarget,
        result: ScheduledResult,
    ) -> None:
        del target
        record = result.record
        with self._publish_lock:
            publish_ok = self._publish_scheduled_record(record)
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
                self._raise_fatal_persistence_error()
                self.scheduler.supervise_workers()
                with self._publish_lock:
                    self._raise_fatal_persistence_error()
                    try:
                        queue_size = self.queue.size()
                        flush_ok = self.flush_queue()
                    except sqlite3.OperationalError as error:
                        if not _is_sqlite_busy_error(error):
                            self._mark_fatal_persistence_error(
                                error, operation="queue supervisor"
                            )
                            raise
                        if not self._register_busy_supervisor_cycle(
                            error, operation="queue supervisor"
                        ):
                            raise
                        self.stop_event.wait(1.0)
                        continue
                    self._reset_busy_supervisor()
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
            self._raise_fatal_persistence_error()
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

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    run_agent_with_health_server(
        agent,
        server,
        endpoint_label="Adaptive health endpoint",
    )

if __name__ == "__main__":
    main()
