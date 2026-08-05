from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from acquisition_registry import RegistryTarget
from main import TelemetryRecord

PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"
PRIORITY_ON_DEMAND = "on_demand"
PRIORITY_CLASSES = (
    PRIORITY_HIGH,
    PRIORITY_MEDIUM,
    PRIORITY_LOW,
    PRIORITY_ON_DEMAND,
)
PRIORITY_RANK = {
    PRIORITY_HIGH: 0,
    PRIORITY_MEDIUM: 1,
    PRIORITY_LOW: 2,
}
_MEDIUM_LE_KEYS = frozenset(
    {
        "voltage",
        "current",
        "frequency",
        "active_power",
        "power_factor",
    }
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    value = default if not raw else float(raw)
    if not 1.0 <= value <= 3600.0:
        raise ValueError(f"{name} must be between 1 and 3600 seconds")
    return value


def _env_int(name: str, default: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    value = default if not raw else int(raw)
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class SchedulerPolicy:
    high_interval_seconds: float
    medium_interval_seconds: float
    low_interval_seconds: float
    startup_spread_seconds: float = 5.0
    failure_threshold: int = 3
    cooldown_initial_seconds: float = 30.0
    cooldown_max_seconds: float = 300.0
    fairness_high_burst: int = 8
    fairness_low_burst: int = 12
    deadline_tolerance_seconds: float = 0.05
    bus_load_window_seconds: float = 60.0

    @classmethod
    def from_environment(
        cls,
        *,
        legacy_interval_seconds: float,
    ) -> SchedulerPolicy:
        high = _env_float(
            "ACQUISITION_HIGH_INTERVAL_SECONDS",
            max(5.0, legacy_interval_seconds),
        )
        medium = _env_float(
            "ACQUISITION_MEDIUM_INTERVAL_SECONDS",
            max(10.0, high),
        )
        low = _env_float(
            "ACQUISITION_LOW_INTERVAL_SECONDS",
            max(30.0, medium),
        )
        if not high <= medium <= low:
            raise ValueError(
                "Adaptive intervals must satisfy high <= medium <= low"
            )

        cooldown_initial = _env_float(
            "ACQUISITION_COOLDOWN_INITIAL_SECONDS",
            30.0,
        )
        cooldown_max = _env_float(
            "ACQUISITION_COOLDOWN_MAX_SECONDS",
            300.0,
        )
        if cooldown_initial > cooldown_max:
            raise ValueError(
                "Initial cooldown must not exceed maximum cooldown"
            )

        fairness_high_burst = _env_int(
            "ACQUISITION_FAIRNESS_HIGH_BURST",
            8,
            100,
        )
        fairness_low_burst = _env_int(
            "ACQUISITION_FAIRNESS_LOW_BURST",
            12,
            200,
        )
        if fairness_low_burst < fairness_high_burst:
            raise ValueError(
                "ACQUISITION_FAIRNESS_LOW_BURST must be greater than or "
                "equal to ACQUISITION_FAIRNESS_HIGH_BURST"
            )

        return cls(
            high_interval_seconds=high,
            medium_interval_seconds=medium,
            low_interval_seconds=low,
            startup_spread_seconds=_env_float(
                "ACQUISITION_STARTUP_SPREAD_SECONDS",
                min(5.0, high),
            ),
            failure_threshold=_env_int(
                "ACQUISITION_FAILURE_THRESHOLD",
                3,
                20,
            ),
            cooldown_initial_seconds=cooldown_initial,
            cooldown_max_seconds=cooldown_max,
            fairness_high_burst=fairness_high_burst,
            fairness_low_burst=fairness_low_burst,
        )

    def priority_for(self, target: RegistryTarget) -> str:
        if target.metric == "temperature.probe":
            return PRIORITY_HIGH
        if (
            target.device_id.startswith("le01mp-")
            and target.key in _MEDIUM_LE_KEYS
        ):
            return PRIORITY_MEDIUM
        return PRIORITY_LOW

    def interval_for(self, priority: str) -> float:
        try:
            return {
                PRIORITY_HIGH: self.high_interval_seconds,
                PRIORITY_MEDIUM: self.medium_interval_seconds,
                PRIORITY_LOW: self.low_interval_seconds,
            }[priority]
        except KeyError as error:
            raise ValueError(
                f"Unsupported normal acquisition priority: {priority}"
            ) from error

    def sanitized(self) -> dict[str, Any]:
        return {
            "priority_classes": list(PRIORITY_CLASSES),
            "normal_priority_classes": [
                PRIORITY_HIGH,
                PRIORITY_MEDIUM,
                PRIORITY_LOW,
            ],
            "on_demand_service_operations": True,
            "interval_seconds": {
                PRIORITY_HIGH: self.high_interval_seconds,
                PRIORITY_MEDIUM: self.medium_interval_seconds,
                PRIORITY_LOW: self.low_interval_seconds,
            },
            "startup_spread_seconds": self.startup_spread_seconds,
            "failure_threshold": self.failure_threshold,
            "cooldown_initial_seconds": self.cooldown_initial_seconds,
            "cooldown_max_seconds": self.cooldown_max_seconds,
            "fairness_high_burst": self.fairness_high_burst,
            "fairness_low_burst": self.fairness_low_burst,
        }


@dataclass(frozen=True)
class SchedulerTarget:
    target_id: str
    bus_id: str
    device_id: str
    device_family: str
    unit_id: int
    key: str
    telemetry_channel_id: str
    metric: str
    unit: str
    priority: str
    interval_seconds: float


@dataclass(frozen=True)
class ScheduledResult:
    record: TelemetryRecord
    communication_failed: bool
    error: str | None = None
