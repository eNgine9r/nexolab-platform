from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from modbus_rtu import ModbusRequestMeasurement


@dataclass
class _BusWindow:
    physical_requests_total: int = 0
    retry_attempts_total: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    samples: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=4096)
    )


class RS485BusRequestMetrics:
    """Thread-safe bounded physical-request evidence keyed by logical bus_id."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = 60.0,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._clock = clock
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._buses: dict[str, _BusWindow] = {}

    def observe(self, measurement: ModbusRequestMeasurement) -> None:
        bus_id = measurement.bus.strip()
        if not bus_id:
            return
        now = self._clock()
        duration_ms = max(0.0, measurement.duration_seconds) * 1000.0
        with self._lock:
            bus = self._buses.setdefault(bus_id, _BusWindow())
            bus.physical_requests_total += 1
            if measurement.attempt > 1:
                bus.retry_attempts_total += 1
            bus.outcomes[measurement.outcome] = (
                bus.outcomes.get(measurement.outcome, 0) + 1
            )
            bus.samples.append((now, duration_ms))
            self._trim(bus, now)

    def snapshot(self, bus_id: str) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            bus = self._buses.get(bus_id)
            if bus is None:
                return self._empty_snapshot()
            self._trim(bus, now)
            durations = [duration for _, duration in bus.samples]
            average = (
                sum(durations) / len(durations)
                if durations
                else 0.0
            )
            ordered = sorted(durations)
            p95 = (
                ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
                if ordered
                else 0.0
            )
            maximum = max(ordered) if ordered else 0.0
            requests_per_minute = (
                len(durations) * 60.0 / self._window_seconds
            )
            return {
                "window_seconds": self._window_seconds,
                "physical_requests_total": bus.physical_requests_total,
                "retry_attempts_total": bus.retry_attempts_total,
                "timeouts_total": bus.outcomes.get("timeout", 0),
                "protocol_errors_total": bus.outcomes.get("protocol_error", 0),
                "io_errors_total": bus.outcomes.get("io_error", 0),
                "exception_responses_total": bus.outcomes.get(
                    "exception_response", 0
                ),
                "outcomes": dict(sorted(bus.outcomes.items())),
                "request_rate_per_minute": round(requests_per_minute, 3),
                "latency_ms": {
                    "sample_count": len(durations),
                    "average": round(average, 3),
                    "p95": round(p95, 3),
                    "maximum": round(maximum, 3),
                },
            }

    def _trim(self, bus: _BusWindow, now: float) -> None:
        cutoff = now - self._window_seconds
        while bus.samples and bus.samples[0][0] < cutoff:
            bus.samples.popleft()

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "window_seconds": self._window_seconds,
            "physical_requests_total": 0,
            "retry_attempts_total": 0,
            "timeouts_total": 0,
            "protocol_errors_total": 0,
            "io_errors_total": 0,
            "exception_responses_total": 0,
            "outcomes": {},
            "request_rate_per_minute": 0.0,
            "latency_ms": {
                "sample_count": 0,
                "average": 0.0,
                "p95": 0.0,
                "maximum": 0.0,
            },
        }
