from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from typing import Any

from acquisition_capacity import BusCapacityProfile
from acquisition_registry import AcquisitionRegistry, DeviceLifecycleMutation, LifecycleMutation
from commissioning_activation import (
    CommissioningActivationJournal,
    CommissioningActivationRequest,
    activation_fingerprint,
    parse_activation_request,
)
from commissioning_preflight import (
    CommissioningPreflightRequest,
    PROFILES,
    PreflightBus,
    PreflightExecutionError,
    PreflightObservation,
    PreflightProfile,
    canonical_serial_identifier,
    execute_preflight,
    parse_preflight_request,
)
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
from modbus_rtu import (
    ModbusError,
    ModbusExceptionResponse,
    ModbusProtocolError,
    ModbusRTUClient,
    ModbusRequestMeasurement,
    ModbusTimeoutError,
)
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
        configured_topology = RS485BusTopology.explicit_from_environment(settings)
        topology_store = (
            TopologyAwareEnrollmentStore(
                settings.database_path,
                bus_for_unit=configured_topology.bus_for_unit,
                bind_registry=configured_topology.bind_registry,
            )
            if configured_topology is not None
            else None
        )
        super().__init__(settings, registry_store=topology_store)
        self.rs485_topology = configured_topology or RS485BusTopology.from_environment(
            self.settings,
            self._registry_snapshot(),
        )
        self.rs485_bus_metrics = RS485BusRequestMetrics()
        self._bus_clients: dict[str, ModbusRTUClient] = {}
        self._bus_xjp60d_readers: dict[str, XJP60DReader] = {}
        self._bus_le01mp_readers: dict[str, LE01MPReader] = {}
        self._bus_embraco_readers: dict[str, EmbracoSyncReader] = {}
        self._bus_operation_locks: dict[str, threading.Lock] = {}
        self._topology_enrollment_store = topology_store
        self._commissioning_activation_journal = CommissioningActivationJournal(settings.database_path)

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

    @property
    def node_id(self) -> str:
        return self.settings.node_id

    def preflight_bus(self, bus_id: str) -> PreflightBus:
        topology = self.rs485_topology
        binding = topology.binding(bus_id)
        return PreflightBus(
            bus_id=binding.bus_id,
            serial_device=binding.serial_device,
            path_present=Path(binding.serial_device).exists(),
        )

    def preflight_unit_owner(self, unit_id: int) -> str | None:
        try:
            return self.rs485_topology.bus_for_unit(unit_id)
        except ValueError:
            pass
        matches = [
            device.bus_id
            for device in self._registry_snapshot().document.devices
            if device.unit_id == unit_id
        ]
        if len(matches) > 1:
            raise PreflightExecutionError(
                "unit_id_conflict",
                f"Unit ID {unit_id} has multiple persisted acquisition bus owners",
            )
        return matches[0] if matches else None

    def preflight_registry_identity(
        self,
        bus_id: str,
        unit_id: int,
    ) -> tuple[str, str] | None:
        matches = [
            device
            for device in self._registry_snapshot().document.devices
            if device.bus_id == bus_id and device.unit_id == unit_id
        ]
        if len(matches) > 1:
            raise PreflightExecutionError(
                "unit_id_conflict",
                f"Unit ID {unit_id} has multiple acquisition registry identities",
            )
        if not matches:
            return None
        device = matches[0]
        return device.device_family, device.profile_version

    def preflight_read_profile(
        self,
        profile: PreflightProfile,
        *,
        bus_id: str,
        unit_id: int,
        deadline_monotonic: float,
    ) -> tuple[PreflightObservation, ...]:
        topology = self.rs485_topology
        if topology.explicit:
            client = self._bus_clients.get(bus_id)
            lock = self._bus_operation_locks.get(bus_id)
            xjp60d = self._bus_xjp60d_readers.get(bus_id)
            le01mp = self._bus_le01mp_readers.get(bus_id)
            embraco = self._bus_embraco_readers.get(bus_id)
        else:
            if bus_id != topology.bindings[0].bus_id:
                raise PreflightExecutionError("bus_unavailable", f"Unknown RS-485 bus {bus_id}")
            client = self.modbus_client
            lock = self._bus_operation_lock
            xjp60d = self.xjp60d_reader
            le01mp = self.le01mp_reader
            embraco = self.embraco_reader
        if client is None or lock is None:
            raise PreflightExecutionError("bus_unavailable", f"RS-485 bus {bus_id} has no active transport")

        observations: list[PreflightObservation] = []
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0 or not lock.acquire(timeout=remaining):
            raise PreflightExecutionError(
                "bus_busy",
                f"RS-485 bus {bus_id} did not become available before the preflight deadline",
            )
        try:
            with client.instrumentation_scope(
                device_family=profile.device_family,
                target_id=f"commissioning-preflight:{unit_id}",
                operation="commissioning_preflight",
                deadline_monotonic=deadline_monotonic,
            ):
                if profile.profile_id == "dixell-xjp60d":
                    if xjp60d is None:
                        raise PreflightExecutionError("profile_unavailable", "XJP60D reader is unavailable")
                    reading = xjp60d.read_channel(unit_id, 1)
                    observations.append(
                        PreflightObservation(
                            key="channel-01",
                            quality=reading.quality,
                            semantic=reading.alarm,
                        )
                    )
                elif profile.profile_id == "f-and-f-le01mp":
                    if le01mp is None:
                        raise PreflightExecutionError("profile_unavailable", "LE-01MP reader is unavailable")
                    reading = le01mp.read_metric(unit_id, "voltage")
                    observations.append(PreflightObservation(key="voltage", quality=reading.quality))
                elif profile.profile_id == "embraco-sync":
                    if embraco is None:
                        raise PreflightExecutionError("profile_unavailable", "Embraco Sync reader is unavailable")
                    for key in ("control_state", "relay_state_bits", "compressor_speed", "alarm_state_bits"):
                        reading = embraco.read_metric(unit_id, key)
                        observations.append(
                            PreflightObservation(
                                key=key,
                                quality=reading.quality,
                                semantic=reading.semantic,
                            )
                        )
                else:
                    raise PreflightExecutionError("unsupported_profile", "Preflight profile is unsupported")
        except ModbusTimeoutError as error:
            raise PreflightExecutionError("timeout", "Bounded FC03 preflight timed out") from error
        except ModbusExceptionResponse as error:
            raise PreflightExecutionError(
                "profile_mismatch",
                "Target rejected the fixed profile-approved FC03 verification read",
            ) from error
        except ModbusProtocolError as error:
            raise PreflightExecutionError("malformed_response", "Target returned a malformed FC03 response") from error
        except OSError as error:
            raise PreflightExecutionError("adapter_unavailable", "RS-485 adapter became unavailable") from error
        except ModbusError as error:
            raise PreflightExecutionError("read_failed", "Profile-approved FC03 verification failed") from error
        finally:
            lock.release()
        return tuple(observations)

    def commissioning_activation(self, request: CommissioningActivationRequest) -> dict[str, Any]:
        fingerprint = activation_fingerprint(request)
        journal = self._commissioning_activation_journal.load(request.activation_id)
        if journal is not None and journal["fingerprint_sha256"] != fingerprint:
            raise ValueError("activation_id was already used for a different commissioning identity")
        if request.action == "rollback":
            return self._rollback_commissioning_activation(request, journal, fingerprint)
        if journal is not None and journal["state"] in {"active", "rolled_back", "recovery_required"}:
            return self._activation_response(request, journal)

        if request.node_id != self.settings.node_id:
            raise ValueError("activation node does not match this Device Agent")
        profile = PROFILES.get(request.profile_id)
        if profile is None or profile.profile_version != request.profile_version:
            raise ValueError("activation profile/version is unsupported")
        bus = self.preflight_bus(request.bus_id)
        if canonical_serial_identifier(bus.serial_device) != canonical_serial_identifier(request.stable_transport_identifier):
            raise ValueError("activation stable adapter identity does not match configured bus")
        if not bus.path_present:
            raise ValueError("activation stable serial adapter is unavailable")
        owner = self.preflight_unit_owner(request.unit_id)
        if owner is not None and owner != request.bus_id:
            raise ValueError("activation Unit ID belongs to another physical bus")

        actor = f"commissioning:{request.activation_id}"
        reason = "Activate repository-owned read-only commissioning target"
        with self._bus_operation_lock, self._registry_lock:
            current = self._registry
            if journal is not None and journal["state"] == "prepared":
                state = self._prepared_activation_state(current, journal)
                if state == "active":
                    completed = {**journal, "registry_revision_after": current.revision}
                    self._commissioning_activation_journal.save(request.activation_id, fingerprint, "active", completed)
                    return self._activation_response(request, {**completed, "state": "active"})
                if state != "rollback":
                    recovery = {**journal, "reason": "affected registry lifecycle changed after prepared activation"}
                    self._commissioning_activation_journal.save(request.activation_id, fingerprint, "recovery_required", recovery)
                    return self._activation_response(request, {**recovery, "state": "recovery_required"})
            else:
                current = self._ensure_commissioning_inventory(current, request, profile.device_family, actor)
                self._registry = current

            device = self._commissioning_device(current, request, profile.device_family)
            targets = tuple(target for target in current.document.targets if target.device_id == device.device_id)
            if not targets:
                raise ValueError("activation profile has no repository-owned acquisition targets")
            rollback = {
                "device_lifecycle": device.lifecycle,
                "target_lifecycles": {target.target_id: target.lifecycle for target in targets},
            }
            prepared = {
                "device_id": device.device_id,
                "target_ids": [target.target_id for target in targets],
                "rollback": rollback,
                "registry_revision_before": current.revision,
                "profile_id": request.profile_id,
                "profile_version": request.profile_version,
                "bus_id": request.bus_id,
                "unit_id": request.unit_id,
            }
            self._commissioning_activation_journal.save(request.activation_id, fingerprint, "prepared", prepared)
            device_mutations = () if device.lifecycle == "active" else (DeviceLifecycleMutation(device.device_id, "active"),)
            target_mutations = tuple(
                LifecycleMutation(target.target_id, "active") for target in targets if target.lifecycle != "active"
            )
            if device_mutations or target_mutations:
                candidate_document, _ = current.with_mutations(
                    device_mutations=device_mutations, target_mutations=target_mutations
                )
                candidate = AcquisitionRegistry(candidate_document)
                self._validate_new_eligibility(current, candidate)
                current = self._registry_store.update(
                    current,
                    expected_revision=current.revision,
                    actor=actor,
                    reason=reason,
                    device_mutations=device_mutations,
                    target_mutations=target_mutations,
                )
                self._registry = current
                self._sync_legacy_xjp60d_state(current)

        self.scheduler.reconcile(self._registry_snapshot())
        completed = {**prepared, "registry_revision_after": current.revision}
        self._commissioning_activation_journal.save(request.activation_id, fingerprint, "active", completed)
        return self._activation_response(request, {**completed, "state": "active"})

    def _ensure_commissioning_inventory(self, current: AcquisitionRegistry, request: CommissioningActivationRequest, family: str, actor: str) -> AcquisitionRegistry:
        matches = [device for device in current.document.devices if device.unit_id == request.unit_id]
        if matches:
            if len(matches) != 1:
                raise ValueError("activation Unit ID has ambiguous acquisition inventory")
            device = matches[0]
            if device.bus_id != request.bus_id or device.device_family != family or device.profile_version != request.profile_version:
                raise ValueError("activation identity conflicts with acquisition registry")
            return current
        kwargs = dict(
            expected_revision=current.revision,
            unit_ids=(request.unit_id,),
            actor=actor,
            reason="Enroll verified commissioning target in safe non-polling state",
            bus_for_unit=lambda _unit_id: request.bus_id,
        )
        if family == "xjp60d":
            return self._registry_store.enroll_xjp60d(current, **kwargs)
        if family == "le01mp":
            return self._registry_store.enroll_le01mp(current, **kwargs)
        if family == "embraco":
            return self._registry_store.enroll_embraco(current, **kwargs)
        raise ValueError("unsupported commissioning activation family")

    @staticmethod
    def _commissioning_device(current: AcquisitionRegistry, request: CommissioningActivationRequest, family: str):
        matches = [
            device for device in current.document.devices
            if device.unit_id == request.unit_id and device.bus_id == request.bus_id
            and device.device_family == family and device.profile_version == request.profile_version
        ]
        if len(matches) != 1:
            raise ValueError("activation registry device identity is unavailable or ambiguous")
        return matches[0]

    @staticmethod
    def _prepared_activation_state(current: AcquisitionRegistry, journal: dict[str, Any]) -> str:
        device_id = str(journal.get("device_id", ""))
        target_ids = tuple(str(value) for value in journal.get("target_ids", []))
        rollback = journal.get("rollback", {})
        devices = {item.device_id: item.lifecycle for item in current.document.devices}
        targets = {item.target_id: item.lifecycle for item in current.document.targets}
        if devices.get(device_id) == "active" and all(targets.get(item) == "active" for item in target_ids):
            return "active"
        expected_device = rollback.get("device_lifecycle") if isinstance(rollback, dict) else None
        expected_targets = rollback.get("target_lifecycles", {}) if isinstance(rollback, dict) else {}
        if devices.get(device_id) == expected_device and all(targets.get(item) == expected_targets.get(item) for item in target_ids):
            return "rollback"
        return "conflict"

    def _rollback_commissioning_activation(
        self, request: CommissioningActivationRequest, journal: dict[str, Any] | None, fingerprint: str
    ) -> dict[str, Any]:
        if journal is None:
            raise ValueError("activation rollback journal was not found")
        if journal["state"] == "rolled_back":
            return self._activation_response(request, journal)
        if journal["state"] == "recovery_required":
            return self._activation_response(request, journal)
        with self._bus_operation_lock, self._registry_lock:
            current = self._registry
            state = self._prepared_activation_state(current, journal)
            if state == "rollback":
                rolled = {**journal, "registry_revision_rollback": current.revision}
                self._commissioning_activation_journal.save(request.activation_id, fingerprint, "rolled_back", rolled)
                return self._activation_response(request, {**rolled, "state": "rolled_back"})
            if state != "active":
                recovery = {**journal, "reason": "affected registry lifecycle changed before rollback"}
                self._commissioning_activation_journal.save(request.activation_id, fingerprint, "recovery_required", recovery)
                return self._activation_response(request, {**recovery, "state": "recovery_required"})
            rollback = journal.get("rollback", {})
            target_lifecycles = rollback.get("target_lifecycles", {}) if isinstance(rollback, dict) else {}
            device_id = str(journal["device_id"])
            device_lifecycle = str(rollback.get("device_lifecycle", "reserve"))
            device_mutations = () if device_lifecycle == "active" else (DeviceLifecycleMutation(device_id, device_lifecycle),)
            target_mutations = tuple(
                LifecycleMutation(str(target_id), str(lifecycle))
                for target_id, lifecycle in target_lifecycles.items()
                if lifecycle != "active"
            )
            if device_mutations or target_mutations:
                current = self._registry_store.update(
                    current,
                    expected_revision=current.revision,
                    actor=f"commissioning:{request.activation_id}",
                    reason="Rollback incomplete commissioning activation to prior non-polling lifecycle",
                    device_mutations=device_mutations,
                    target_mutations=target_mutations,
                )
                self._registry = current
                self._sync_legacy_xjp60d_state(current)
        self.scheduler.reconcile(self._registry_snapshot())
        rolled = {**journal, "registry_revision_rollback": current.revision}
        self._commissioning_activation_journal.save(request.activation_id, fingerprint, "rolled_back", rolled)
        return self._activation_response(request, {**rolled, "state": "rolled_back"})

    @staticmethod
    def _activation_response(request: CommissioningActivationRequest, journal: dict[str, Any]) -> dict[str, Any]:
        profile = PROFILES[request.profile_id]
        source = {"xjp60d": "dixell-xjp60d", "le01mp": "f-and-f-le-01mp", "embraco": "embraco-sync"}[profile.device_family]
        equipment_id = {"xjp60d": f"K{request.unit_id}", "le01mp": f"LE01MP-{request.unit_id}", "embraco": f"EMBRACO-{request.unit_id}"}[profile.device_family]
        return {
            "schema_version": 1,
            "activation_id": request.activation_id,
            "state": journal["state"],
            "node_id": request.node_id,
            "bus_id": request.bus_id,
            "stable_transport_identifier": request.stable_transport_identifier,
            "unit_id": request.unit_id,
            "profile_id": request.profile_id,
            "profile_version": request.profile_version,
            "device_id": journal.get("device_id"),
            "target_ids": list(journal.get("target_ids", [])),
            "registry_revision": journal.get("registry_revision_after") or journal.get("registry_revision_rollback") or journal.get("registry_revision_before"),
            "telemetry_source": source,
            "telemetry_equipment_id": equipment_id,
            "polling_mode": "read_only_fc03",
            "modbus_writes": "none",
            "hardware_writes": "none",
            "reason": journal.get("reason"),
        }

    def commissioning_preflight(self, request: CommissioningPreflightRequest) -> dict[str, Any]:
        return execute_preflight(request, self)

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

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", maxsplit=1)[0]
        if path == "/api/v1/commissioning/preflight":
            try:
                request = parse_preflight_request(self._read_json_body())
                result = self.agent.commissioning_preflight(request)
            except (ValueError, TypeError) as error:
                self._send_json(422, {"detail": {"code": "preflight_request_invalid", "message": str(error)}})
                return
            self._send_json(200, result)
            return
        if path == "/api/v1/commissioning/activation":
            try:
                request = parse_activation_request(self._read_json_body())
                result = self.agent.commissioning_activation(request)
            except (ValueError, TypeError) as error:
                self._send_json(422, {"detail": {"code": "activation_request_invalid", "message": str(error)}})
                return
            self._send_json(200, result)
            return
        super().do_POST()


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
