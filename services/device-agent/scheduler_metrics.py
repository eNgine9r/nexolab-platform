from __future__ import annotations

from collections import deque
from typing import Any

from scheduler_policy import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
)


class BusSchedulerMetrics:
    """Bounded per-bus scheduler counters and rolling utilization evidence."""

    def __init__(self) -> None:
        self.executions_total = 0
        self.successes_total = 0
        self.communication_failures_total = 0
        self.callback_errors_total = 0
        self.missed_deadline_total = 0
        self.deadline_skipped_total = 0
        self.overrun_total = 0
        self.deferred_total = 0
        self.cooldown_entered_total = 0
        self.fairness_forced_total = 0
        self.fairness_forced_low_total = 0
        self.max_queue_depth = 0
        self.lag_last = 0.0
        self.lag_max = 0.0
        self.consecutive_high = 0
        self.consecutive_non_low = 0
        self.by_priority = {
            PRIORITY_HIGH: 0,
            PRIORITY_MEDIUM: 0,
            PRIORITY_LOW: 0,
        }
        self.busy: deque[tuple[float, float]] = deque()

    def observe_queue(self, queue_depth: int) -> None:
        self.max_queue_depth = max(self.max_queue_depth, queue_depth)

    def observe_lag(self, lag: float, tolerance: float) -> None:
        self.lag_last = lag
        self.lag_max = max(self.lag_max, lag)
        if lag > tolerance:
            self.missed_deadline_total += 1

    def force_fairness(self, *, low: bool, deferred: int) -> None:
        self.fairness_forced_total += 1
        if low:
            self.fairness_forced_low_total += 1
        self.deferred_total += max(0, deferred)

    def observe_completion(
        self,
        *,
        priority: str,
        completed: float,
        duration: float,
        interval_seconds: float,
        failed: bool,
        callback_error: bool,
    ) -> None:
        self.executions_total += 1
        self.by_priority[priority] += 1
        if failed:
            self.communication_failures_total += 1
        else:
            self.successes_total += 1
        if callback_error:
            self.callback_errors_total += 1
        self.consecutive_high = (
            self.consecutive_high + 1
            if priority == PRIORITY_HIGH
            else 0
        )
        self.consecutive_non_low = (
            self.consecutive_non_low + 1
            if priority != PRIORITY_LOW
            else 0
        )
        if duration > interval_seconds:
            self.overrun_total += 1
        self.busy.append((completed, duration))

    def observe_callback_error(self) -> None:
        self.callback_errors_total += 1

    def observe_cooldown(self, *, deferred: int) -> None:
        self.cooldown_entered_total += 1
        self.deferred_total += max(0, deferred)

    def observe_skipped(self, count: int) -> None:
        self.deadline_skipped_total += max(0, count)

    def snapshot(
        self,
        *,
        now: float,
        load_window_seconds: float,
        worker_count: int,
        configured_targets: int,
        queue_depth: int,
    ) -> dict[str, Any]:
        cutoff = now - load_window_seconds
        while self.busy and self.busy[0][0] < cutoff:
            self.busy.popleft()
        busy_seconds = sum(duration for _, duration in self.busy)
        skipped = self.deadline_skipped_total
        return {
            "worker_count": worker_count,
            "configured_targets": configured_targets,
            "queue_depth": queue_depth,
            "max_queue_depth": self.max_queue_depth,
            "executions_total": self.executions_total,
            "successes_total": self.successes_total,
            "communication_failures_total": (
                self.communication_failures_total
            ),
            "callback_errors_total": self.callback_errors_total,
            "missed_deadline_total": self.missed_deadline_total,
            "deadline_skipped_total": skipped,
            "skipped_total": skipped,
            "overrun_total": self.overrun_total,
            "deferred_total": self.deferred_total,
            "cooldown_entered_total": self.cooldown_entered_total,
            "fairness_forced_total": self.fairness_forced_total,
            "fairness_forced_low_total": self.fairness_forced_low_total,
            "scheduler_lag_seconds": {
                "last": round(self.lag_last, 6),
                "maximum": round(self.lag_max, 6),
            },
            "bus_load_percent": round(
                min(
                    100.0,
                    busy_seconds / load_window_seconds * 100,
                ),
                3,
            ),
            "executions_by_priority": dict(self.by_priority),
        }
