from __future__ import annotations

import json
import logging
import os
import signal
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import Any

from acquisition_registry import (
    AcquisitionRegistry,
    AcquisitionRegistryStore,
    DeviceLifecycleMutation,
    LifecycleMutation,
    RegistryRevisionConflict,
    parse_registry_mutation,
)
from le01mp import LE01MPReader, REGISTER_BY_KEY
from main import (
    Settings,
    TelemetryRecord,
    mode_uses_le01mp,
    mode_uses_xjp60d,
    parse_unit_ids,
)
from managed_main import (
    DEFAULT_DISCOVERY_UNITS,
    LOG,
    ManagedDeviceAgent,
    ManagedHealthHandler,
    canonical_point,
)
from modbus_rtu import ModbusError
from xjp60d import XJP60DReader

REGISTRY_PATH = "/api/v1/acquisition-registry"


class RegistryManagedDeviceAgent(ManagedDeviceAgent):
    """Managed Device Agent whose normal Modbus targets come only from SQLite registry."""

    def __init__(self, settings: Settings) -> None:
        discovery_value = os.getenv("XJP60D_DISCOVERY_UNITS", "").strip()
        discovery_units = (
            parse_unit_ids(discovery_value, label="XJP60D discovery")
            if discovery_value
            else DEFAULT_DISCOVERY_UNITS
        )
        original_settings = settings
        super().__init__(settings)
        self._registry_lock = threading.Lock()
        self._registry_store = AcquisitionRegistryStore(settings.database_path)
        self._registry = self._registry_store.load_or_migrate(
            original_settings,
            discovery_units=discovery_units,
            legacy_active_points=self.settings.xjp60d_points,
        )
        self._sync_legacy_xjp60d_state(self._registry)
        if (
            mode_uses_xjp60d(self.settings.device_mode)
            and self.modbus_client is not None
            and self.xjp60d_reader is None
        ):
            self.xjp60d_reader = XJP60DReader(
                self.modbus_client,
                scale=self.settings.xjp60d_scale,
                unit="degC",
            )
        if (
            mode_uses_le01mp(self.settings.device_mode)
            and self.modbus_client is not None
            and self.le01mp_reader is None
        ):
            self.le01mp_reader = LE01MPReader(self.modbus_client)

    def _registry_snapshot(self) -> AcquisitionRegistry:
        with self._registry_lock:
            return self._registry

    def _sync_legacy_xjp60d_state(self, registry: AcquisitionRegistry) -> None:
        active_points = registry.eligible_xjp60d_points()
        self._point_store.replace_points(active_points)
        with self._configuration_lock:
            self.settings = replace(self.settings, xjp60d_points=active_points)

    def registry_configuration(self) -> dict[str, Any]:
        registry = self._registry_snapshot()
        return registry.sanitized(audit=self._registry_store.recent_audit())

    def registry_summary(self) -> dict[str, Any]:
        registry = self._registry_snapshot()
        payload = registry.sanitized()
        return {
            "schema_version": payload["schema_version"],
            "revision": payload["revision"],
            "updated_at": payload["updated_at"],
            **payload["summary"],
        }

    def _configured_logical_targets(self) -> int:
        return len(self._registry_snapshot().eligible_targets())

    def health_snapshot(self) -> dict[str, Any]:
        payload = super().health_snapshot()
        payload["acquisition_registry"] = self.registry_summary()
        return payload

    def configuration(self) -> dict[str, Any]:
        registry = self._registry_snapshot()
        return {
            "node_id": self.settings.node_id,
            "active_points": [
                canonical_point(unit_id, channel)
                for unit_id, channel in registry.eligible_xjp60d_points()
            ],
            "discovery_units": list(self.discovery_units),
            "last_discovery": self._point_store.load_last_discovery(),
            "registry_revision": registry.revision,
        }

    def replace_active_points(
        self,
        points: tuple[tuple[int, int], ...],
    ) -> dict[str, Any]:
        requested = {
            f"xjp60d:{canonical_point(unit_id, channel)}"
            for unit_id, channel in points
        }
        actor = "compatibility:xjp60d-active-points"
        reason = "Replace legacy XJP60D active point set"
        with self._bus_operation_lock, self._registry_lock:
            registry = self._registry
            inventory = {
                target.target_id: target
                for target in registry.document.targets
                if target.target_id.startswith("xjp60d:")
            }
            unknown = sorted(requested - set(inventory))
            if unknown:
                raise ValueError(
                    f"Unknown XJP60D registry targets: {', '.join(unknown)}"
                )

            target_mutations: list[LifecycleMutation] = []
            for target_id, target in inventory.items():
                desired = (
                    "active"
                    if target_id in requested
                    else (
                        "discovery_only"
                        if target.lifecycle == "active"
                        else target.lifecycle
                    )
                )
                if desired != target.lifecycle:
                    target_mutations.append(LifecycleMutation(target_id, desired))

            requested_units = {unit_id for unit_id, _ in points}
            device_mutations: list[DeviceLifecycleMutation] = []
            for device in registry.document.devices:
                if device.device_family != "xjp60d":
                    continue
                desired = (
                    "active"
                    if device.unit_id in requested_units
                    else (
                        "discovery_only"
                        if device.lifecycle == "active"
                        else device.lifecycle
                    )
                )
                if desired != device.lifecycle:
                    device_mutations.append(
                        DeviceLifecycleMutation(device.device_id, desired)
                    )

            if target_mutations or device_mutations:
                registry = self._registry_store.update(
                    registry,
                    expected_revision=registry.revision,
                    actor=actor,
                    reason=reason,
                    device_mutations=tuple(device_mutations),
                    target_mutations=tuple(target_mutations),
                )
                self._registry = registry
                self._sync_legacy_xjp60d_state(registry)
        self.state.update(last_error=None)
        if self.operational is not None and self.state.mqtt_connected:
            self.operational.publish_health_if_due(force=True)
        return self.configuration()

    def update_registry(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        expected_revision, reason, devices, targets = parse_registry_mutation(payload)
        with self._bus_operation_lock, self._registry_lock:
            registry = self._registry_store.update(
                self._registry,
                expected_revision=expected_revision,
                actor=actor,
                reason=reason,
                device_mutations=devices,
                target_mutations=targets,
            )
            self._registry = registry
            self._sync_legacy_xjp60d_state(registry)
        self.state.update(last_error=None)
        if self.operational is not None and self.state.mqtt_connected:
            self.operational.publish_health_if_due(force=True)
        return self.registry_configuration()

    def _sample_xjp60d(
        self,
        captured_at: str,
        records: list[TelemetryRecord],
        errors: list[str],
    ) -> None:
        targets = self._registry_snapshot().eligible_xjp60d_points()
        if not targets:
            return
        if self.xjp60d_reader is None:
            raise RuntimeError("XJP60D reader was not initialized")

        for unit_id, channel in targets:
            equipment_id = f"K{unit_id}"
            channel_id = canonical_point(unit_id, channel)
            try:
                reading = self.xjp60d_reader.read_channel(unit_id, channel)
            except (ModbusError, OSError, RuntimeError) as exc:
                LOG.warning("XJP60D read failed for %s: %s", channel_id, exc)
                errors.append(f"{channel_id}: {exc}")
                records.append(
                    TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric="temperature.probe",
                        value=None,
                        unit="degC",
                        quality="communication_error",
                        source="dixell-xjp60d",
                        equipment_id=equipment_id,
                        channel_id=channel_id,
                    )
                )
                continue
            records.append(
                TelemetryRecord(
                    event_id=str(uuid.uuid4()),
                    node_id=self.settings.node_id,
                    captured_at=captured_at,
                    metric="temperature.probe",
                    value=reading.value,
                    unit=reading.unit,
                    quality=reading.quality,
                    source="dixell-xjp60d",
                    equipment_id=equipment_id,
                    channel_id=channel_id,
                    alarm=reading.alarm,
                    raw_value=reading.raw_value,
                    raw_status=reading.raw_status,
                )
            )

    def _sample_le01mp(
        self,
        captured_at: str,
        records: list[TelemetryRecord],
        errors: list[str],
    ) -> None:
        targets = self._registry_snapshot().eligible_le01mp_metrics()
        if not targets:
            return
        if self.le01mp_reader is None:
            raise RuntimeError("LE-01MP reader was not initialized")

        for unit_id, key in targets:
            register = REGISTER_BY_KEY[key]
            equipment_id = f"LE01MP-{unit_id}"
            channel_id = f"{unit_id}-{key.replace('_', '-')}"
            try:
                reading = self.le01mp_reader.read_metric(unit_id, key)
            except (ModbusError, OSError, RuntimeError) as exc:
                LOG.warning("LE-01MP read failed for %s: %s", channel_id, exc)
                errors.append(f"{channel_id}: {exc}")
                records.append(
                    TelemetryRecord(
                        event_id=str(uuid.uuid4()),
                        node_id=self.settings.node_id,
                        captured_at=captured_at,
                        metric=register.metric,
                        value=None,
                        unit=register.unit,
                        quality="communication_error",
                        source="f-and-f-le-01mp",
                        equipment_id=equipment_id,
                        channel_id=channel_id,
                    )
                )
                continue
            records.append(
                TelemetryRecord(
                    event_id=str(uuid.uuid4()),
                    node_id=self.settings.node_id,
                    captured_at=captured_at,
                    metric=reading.metric,
                    value=reading.value,
                    unit=reading.unit,
                    quality=reading.quality,
                    source="f-and-f-le-01mp",
                    equipment_id=equipment_id,
                    channel_id=channel_id,
                    raw_value=reading.raw_value,
                )
            )

    def sample_batch(self) -> tuple[list[TelemetryRecord], str | None]:
        if self.settings.device_mode == "simulator":
            return super().sample_batch()

        with self._bus_operation_lock:
            self.acquisition_metrics.begin_cycle()
            failed = True
            try:
                captured_at = datetime.now(timezone.utc).isoformat()
                records: list[TelemetryRecord] = []
                errors: list[str] = []
                if mode_uses_xjp60d(self.settings.device_mode):
                    self._sample_xjp60d(captured_at, records, errors)
                if mode_uses_le01mp(self.settings.device_mode):
                    self._sample_le01mp(captured_at, records, errors)
                failed = False
                return records, "; ".join(errors) if errors else None
            finally:
                self.acquisition_metrics.complete_cycle(
                    interval_seconds=self.settings.sample_interval_seconds,
                    failed=failed,
                )


class RegistryManagedHealthHandler(ManagedHealthHandler):
    agent: RegistryManagedDeviceAgent

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path == REGISTRY_PATH:
            self._send_json(HTTPStatus.OK, self.agent.registry_configuration())
            return
        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path != REGISTRY_PATH:
            super().do_PUT()
            return
        try:
            payload = self._read_json_body()
            actor = self.headers.get(
                "X-NEXOLAB-Actor", "authorized-control-plane"
            )
            result = self.agent.update_registry(payload, actor=actor)
        except RegistryRevisionConflict as error:
            self._send_json(HTTPStatus.CONFLICT, {"detail": str(error)})
            return
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": str(error)})
            return
        self._send_json(HTTPStatus.OK, result)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    agent = RegistryManagedDeviceAgent(settings)
    RegistryManagedHealthHandler.agent = agent
    server = ThreadingHTTPServer(
        (settings.health_host, settings.health_port),
        RegistryManagedHealthHandler,
    )

    def stop(signum: int, frame: Any) -> None:
        del frame
        LOG.info("Received signal %s", signum)
        agent.stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker = threading.Thread(
        target=agent.run,
        name="device-agent",
        daemon=True,
    )
    worker.start()
    LOG.info(
        "Registry-managed health endpoint listening on %s:%s",
        settings.health_host,
        settings.health_port,
    )
    server.serve_forever(poll_interval=0.5)
    worker.join(timeout=10)


if __name__ == "__main__":
    main()
