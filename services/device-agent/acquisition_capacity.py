from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from acquisition_cadence import CADENCE_MAX_SECONDS
from acquisition_registry import AcquisitionRegistry, RegistryTarget

DEFAULT_MAX_UTILIZATION = 0.75
DEFAULT_RETRY_RESERVE_FRACTION = 0.10
SCHEDULER_OVERHEAD_SECONDS_PER_TARGET = 0.002


@dataclass(frozen=True)
class BusCapacityProfile:
    bus_id: str
    baudrate: int
    parity: str
    stopbits: int
    timeout_seconds: float
    retries: int
    observed_p95_seconds: float | None = None
    observed_retry_rate: float | None = None
    observed_sample_count: int = 0

    def inter_frame_seconds(self) -> float:
        parity_bits = 0 if self.parity == "N" else 1
        bits_per_character = 1 + 8 + parity_bits + self.stopbits
        return 3.5 * bits_per_character / self.baudrate

    def request_budget_seconds(self) -> tuple[float, str]:
        if self.observed_p95_seconds is not None and self.observed_p95_seconds > 0:
            base = min(self.timeout_seconds, self.observed_p95_seconds)
            source = "measured_p95"
        else:
            base = self.timeout_seconds
            source = "serial_timeout_fallback"
        retry_fraction = max(
            DEFAULT_RETRY_RESERVE_FRACTION if self.retries else 0.0,
            min(1.0, self.observed_retry_rate or 0.0),
        )
        retry_reserve = self.retries * self.timeout_seconds * retry_fraction
        return base + retry_reserve + self.inter_frame_seconds(), source


class CapacityValidationError(ValueError):
    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        overloaded = [
            item for item in summary.get("buses", []) if not item.get("safe", False)
        ]
        rendered = ", ".join(str(item.get("bus_id")) for item in overloaded)
        super().__init__(f"Requested acquisition cadence exceeds RS-485 capacity: {rendered}")

    def payload(self) -> dict[str, Any]:
        return {
            "code": "acquisition_capacity_exceeded",
            "detail": str(self),
            "capacity": self.summary,
        }


def physical_requests_per_target(target: RegistryTarget) -> int:
    if target.device_id.startswith("xjp60d-"):
        # XJP60D read_channel performs one FC03 for value and one FC03 for status.
        return 2
    if target.device_id.startswith("le01mp-"):
        # LE-01MP scalar and two-register cumulative values are each one FC03.
        return 1
    raise ValueError(f"Unsupported capacity device target: {target.target_id}")


def _recommend_uniform_changed_interval(
    *,
    allowed_utilization: float,
    fixed_utilization: float,
    changed_work_seconds: float,
) -> int | None:
    remaining = allowed_utilization - fixed_utilization
    if remaining <= 0 or changed_work_seconds <= 0:
        return None
    required = max(10, math.ceil(changed_work_seconds / remaining))
    return required if required <= CADENCE_MAX_SECONDS else None


def evaluate_capacity(
    registry: AcquisitionRegistry,
    profiles: Mapping[str, BusCapacityProfile],
    *,
    changed_device_ids: Iterable[str] = (),
    max_utilization: float = DEFAULT_MAX_UTILIZATION,
) -> dict[str, Any]:
    if not 0 < max_utilization < 1:
        raise ValueError("max_utilization must be between zero and one")

    changed = set(changed_device_ids)
    devices = {item.device_id: item for item in registry.document.devices}
    device_requests: dict[str, int] = {}
    for target in registry.eligible_targets():
        device_requests[target.device_id] = (
            device_requests.get(target.device_id, 0)
            + physical_requests_per_target(target)
        )

    buses: list[dict[str, Any]] = []
    for bus_id in sorted({item.bus_id for item in registry.document.buses}):
        bus_devices = [
            device
            for device in registry.document.devices
            if device.bus_id == bus_id and device.device_id in device_requests
        ]
        if not bus_devices:
            buses.append(
                {
                    "bus_id": bus_id,
                    "safe": True,
                    "active_device_count": 0,
                    "active_target_count": 0,
                    "estimated_utilization_percent": 0.0,
                    "maximum_allowed_utilization_percent": round(max_utilization * 100, 3),
                    "recommended_minimum_interval_seconds": None,
                    "request_budget_source": "not_required",
                    "cooldown_capacity_credit": False,
                }
            )
            continue

        profile = profiles.get(bus_id)
        if profile is None:
            raise ValueError(f"Missing RS-485 capacity profile for active bus: {bus_id}")
        if profile.bus_id != bus_id:
            raise ValueError(f"RS-485 capacity profile bus mismatch: {bus_id}")
        if profile.baudrate <= 0 or profile.timeout_seconds <= 0 or profile.retries < 0:
            raise ValueError(f"Invalid RS-485 capacity profile for bus: {bus_id}")
        if profile.parity not in {"N", "E", "O"} or profile.stopbits not in {1, 2}:
            raise ValueError(f"Invalid RS-485 serial framing for bus: {bus_id}")

        request_budget, budget_source = profile.request_budget_seconds()
        utilization = 0.0
        fixed_utilization = 0.0
        changed_work = 0.0
        active_targets = 0
        device_rows: list[dict[str, Any]] = []
        for device in sorted(bus_devices, key=lambda item: item.device_id):
            request_count = device_requests[device.device_id]
            active_targets += sum(
                1
                for target in registry.eligible_targets()
                if target.device_id == device.device_id
            )
            interval, cadence_source = registry.effective_cadence_for_device(device.device_id)
            work_seconds = (
                request_count * request_budget
                + SCHEDULER_OVERHEAD_SECONDS_PER_TARGET * request_count
            )
            contribution = work_seconds / interval
            utilization += contribution
            if device.device_id in changed:
                changed_work += work_seconds
            else:
                fixed_utilization += contribution
            device_rows.append(
                {
                    "device_id": device.device_id,
                    "device_family": device.device_family,
                    "physical_requests_per_pass": request_count,
                    "effective_interval_seconds": interval,
                    "cadence_source": cadence_source,
                    "estimated_work_seconds_per_pass": round(work_seconds, 6),
                    "estimated_utilization_percent": round(contribution * 100, 3),
                }
            )

        safe = utilization <= max_utilization + 1e-9
        recommendation = None
        recommendation_scope = None
        if not safe:
            recommendation = _recommend_uniform_changed_interval(
                allowed_utilization=max_utilization,
                fixed_utilization=(fixed_utilization if changed else 0.0),
                changed_work_seconds=(changed_work if changed else sum(
                    item["estimated_work_seconds_per_pass"] for item in device_rows
                )),
            )
            recommendation_scope = (
                "changed_devices_uniform_interval" if changed else "all_active_devices_uniform_interval"
            )

        buses.append(
            {
                "bus_id": bus_id,
                "safe": safe,
                "active_device_count": len(bus_devices),
                "active_target_count": active_targets,
                "estimated_utilization_percent": round(utilization * 100, 3),
                "maximum_allowed_utilization_percent": round(max_utilization * 100, 3),
                "recommended_minimum_interval_seconds": recommendation,
                "recommendation_scope": recommendation_scope,
                "request_budget_seconds": round(request_budget, 6),
                "request_budget_source": budget_source,
                "observed_sample_count": profile.observed_sample_count,
                "serial_timeout_seconds": profile.timeout_seconds,
                "retry_allowance": profile.retries,
                "retry_reserve_fraction": round(
                    max(
                        DEFAULT_RETRY_RESERVE_FRACTION if profile.retries else 0.0,
                        min(1.0, profile.observed_retry_rate or 0.0),
                    ),
                    6,
                ),
                "inter_frame_seconds": round(profile.inter_frame_seconds(), 6),
                "cooldown_capacity_credit": False,
                "devices": device_rows,
            }
        )

    return {
        "schema_version": 1,
        "model": "heterogeneous_device_utilization_v1",
        "safe": all(item["safe"] for item in buses),
        "maximum_allowed_utilization_percent": round(max_utilization * 100, 3),
        "safety_margin_percent": round((1.0 - max_utilization) * 100, 3),
        "cooldown_capacity_credit": False,
        "buses": buses,
    }


def validate_capacity(
    registry: AcquisitionRegistry,
    profiles: Mapping[str, BusCapacityProfile],
    *,
    changed_device_ids: Iterable[str] = (),
    max_utilization: float = DEFAULT_MAX_UTILIZATION,
) -> dict[str, Any]:
    summary = evaluate_capacity(
        registry,
        profiles,
        changed_device_ids=changed_device_ids,
        max_utilization=max_utilization,
    )
    if not summary["safe"]:
        raise CapacityValidationError(summary)
    return summary
