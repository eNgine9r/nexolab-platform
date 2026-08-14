from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from acquisition_registry import AcquisitionRegistry
from latest_values import LatestValueStore
from scheduler_metrics import BusSchedulerMetrics
from scheduler_policy import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_RANK,
    ScheduledResult,
    SchedulerPolicy,
    SchedulerTarget,
)

__all__ = [
    "AdaptiveAcquisitionScheduler",
    "ScheduledResult",
    "SchedulerPolicy",
    "SchedulerTarget",
]

LOG = logging.getLogger("nexolab.device_agent.scheduler")


@dataclass
class _Job:
    target: SchedulerTarget
    next_deadline: float
    sequence: int


@dataclass
class _Endpoint:
    failure_streak: int = 0
    trip_count: int = 0
    cooldown_until: float = 0.0


class AdaptiveAcquisitionScheduler:
    """One serialized worker per bus with bounded priority and cooldown."""

    def __init__(
        self,
        registry: AcquisitionRegistry,
        *,
        policy: SchedulerPolicy,
        latest_store: LatestValueStore,
        read_target: Callable[[SchedulerTarget], ScheduledResult],
        record_result: Callable[[SchedulerTarget, ScheduledResult], None],
        stop_event: threading.Event,
        bus_locks: Mapping[str, threading.Lock] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy
        self._latest_store = latest_store
        self._read_target = read_target
        self._record_result = record_result
        self._stop_event = stop_event
        self._clock = clock
        self._wall_clock = wall_clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._condition = threading.Condition()
        self._jobs: dict[str, _Job] = {}
        self._bus_jobs: dict[str, set[str]] = {}
        self._endpoints: dict[tuple[str, int], _Endpoint] = {}
        self._bus_locks = dict(bus_locks or {})
        self._metrics: dict[str, BusSchedulerMetrics] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._worker_failures_total: dict[str, int] = {}
        self._worker_restarts_total: dict[str, int] = {}
        self._worker_last_failure_type: dict[str, str | None] = {}
        self._worker_last_failure_at: dict[str, str | None] = {}
        self._worker_last_recovered_at: dict[str, str | None] = {}
        self._sequence = 0
        self._started = False
        self._install(registry, preserve=False)

    def _specs(
        self,
        registry: AcquisitionRegistry,
    ) -> list[SchedulerTarget]:
        devices = {
            device.device_id: device
            for device in registry.document.devices
        }
        result: list[SchedulerTarget] = []
        for target in registry.eligible_targets():
            device = devices[target.device_id]
            priority = self.policy.priority_for(target)
            result.append(
                SchedulerTarget(
                    target_id=target.target_id,
                    bus_id=device.bus_id,
                    device_id=device.device_id,
                    device_family=device.device_family,
                    unit_id=device.unit_id,
                    key=target.key,
                    telemetry_channel_id=target.telemetry_channel_id,
                    metric=target.metric,
                    unit=target.unit,
                    priority=priority,
                    interval_seconds=self.policy.interval_for(priority),
                )
            )
        return sorted(
            result,
            key=lambda item: (
                item.bus_id,
                PRIORITY_RANK[item.priority],
                item.target_id,
            ),
        )

    def _initial_deadlines(
        self,
        specs: list[SchedulerTarget],
        now: float,
    ) -> dict[str, float]:
        last_attempts = self._latest_store.last_attempts()
        wall_now = self._wall_clock()
        groups: dict[tuple[str, str], list[SchedulerTarget]] = {}
        for spec in specs:
            groups.setdefault((spec.bus_id, spec.priority), []).append(spec)

        deadlines: dict[str, float] = {}
        for group in groups.values():
            for index, spec in enumerate(group):
                spread = min(
                    spec.interval_seconds,
                    self.policy.startup_spread_seconds,
                )
                delay = max(
                    0.05,
                    spread * (index + 1) / (len(group) + 1),
                )
                attempted = last_attempts.get(spec.target_id)
                if attempted:
                    try:
                        parsed = datetime.fromisoformat(attempted)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        age = max(
                            0.0,
                            (wall_now - parsed).total_seconds(),
                        )
                        if age < spec.interval_seconds:
                            delay = max(
                                0.05,
                                spec.interval_seconds - age,
                            )
                    except ValueError:
                        LOG.warning(
                            "Ignoring invalid latest-value timestamp for %s",
                            spec.target_id,
                        )
                deadlines[spec.target_id] = now + delay
        return deadlines

    def _install(
        self,
        registry: AcquisitionRegistry,
        *,
        preserve: bool,
    ) -> None:
        now = self._clock()
        specs = self._specs(registry)
        deadlines = self._initial_deadlines(specs, now)
        previous = self._jobs if preserve else {}
        previous_endpoints = self._endpoints if preserve else {}
        jobs: dict[str, _Job] = {}
        bus_jobs: dict[str, set[str]] = {}
        endpoints: dict[tuple[str, int], _Endpoint] = {}

        for spec in specs:
            job = previous.get(spec.target_id)
            if job is None:
                self._sequence += 1
                job = _Job(
                    target=spec,
                    next_deadline=deadlines[spec.target_id],
                    sequence=self._sequence,
                )
            else:
                job = _Job(
                    target=spec,
                    next_deadline=job.next_deadline,
                    sequence=job.sequence,
                )
            jobs[spec.target_id] = job
            bus_jobs.setdefault(spec.bus_id, set()).add(spec.target_id)
            self._bus_locks.setdefault(spec.bus_id, threading.Lock())
            endpoint_key = (spec.bus_id, spec.unit_id)
            endpoints[endpoint_key] = previous_endpoints.get(
                endpoint_key,
                _Endpoint(),
            )
            self._metrics.setdefault(
                spec.bus_id,
                BusSchedulerMetrics(),
            )

        self._jobs = jobs
        self._bus_jobs = bus_jobs
        self._endpoints = endpoints

    def reconcile(self, registry: AcquisitionRegistry) -> None:
        with self._condition:
            old_buses = set(self._bus_jobs)
            self._install(registry, preserve=True)
            if self._started:
                for bus_id in set(self._bus_jobs) - old_buses:
                    self._start_bus(bus_id)
            self._condition.notify_all()

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            self._started = True
            for bus_id in sorted(self._bus_jobs):
                self._start_bus(bus_id)

    def _start_bus(self, bus_id: str, *, recovery: bool = False) -> bool:
        existing = self._threads.get(bus_id)
        if existing is not None and existing.is_alive():
            return False
        if existing is not None:
            self._threads.pop(bus_id, None)

        thread = threading.Thread(
            target=self._run_bus,
            args=(bus_id,),
            name=f"acquisition-{bus_id}",
            daemon=True,
        )
        self._threads[bus_id] = thread
        thread.start()

        if recovery:
            self._worker_restarts_total[bus_id] = (
                self._worker_restarts_total.get(bus_id, 0) + 1
            )
            self._worker_last_recovered_at[bus_id] = (
                self._wall_clock().isoformat()
            )
        return True

    def _advance_overdue_deadlines_for_recovery(
        self,
        bus_id: str,
        now: float,
    ) -> None:
        metrics = self._metrics[bus_id]
        for target_id in self._bus_jobs.get(bus_id, set()):
            job = self._jobs.get(target_id)
            if job is None:
                continue
            endpoint = self._endpoints[
                (job.target.bus_id, job.target.unit_id)
            ]
            if endpoint.cooldown_until > now or job.next_deadline > now:
                continue

            interval = job.target.interval_seconds
            skipped = int((now - job.next_deadline) // interval) + 1
            job.next_deadline += skipped * interval
            metrics.observe_skipped(skipped)

    def _record_worker_failure(
        self,
        bus_id: str,
        error: Exception,
    ) -> None:
        with self._condition:
            self._worker_failures_total[bus_id] = (
                self._worker_failures_total.get(bus_id, 0) + 1
            )
            self._worker_last_failure_type[bus_id] = type(error).__name__
            self._worker_last_failure_at[bus_id] = (
                self._wall_clock().isoformat()
            )
            self._condition.notify_all()

    def supervise_workers(self) -> int:
        with self._condition:
            if not self._started or self._stop_event.is_set():
                return 0

            now = self._clock()
            recovered = 0
            for bus_id in sorted(self._bus_jobs):
                if not self._bus_jobs.get(bus_id):
                    continue
                thread = self._threads.get(bus_id)
                if thread is not None and thread.is_alive():
                    continue

                self._advance_overdue_deadlines_for_recovery(bus_id, now)
                if self._start_bus(bus_id, recovery=True):
                    recovered += 1

            if recovered:
                self._condition.notify_all()
            return recovered

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        for thread in tuple(self._threads.values()):
            thread.join(timeout=10)

    def _effective_deadline(self, job: _Job) -> float:
        endpoint = self._endpoints[
            (job.target.bus_id, job.target.unit_id)
        ]
        return max(job.next_deadline, endpoint.cooldown_until)

    def _due(self, bus_id: str, now: float) -> list[_Job]:
        return [
            self._jobs[target_id]
            for target_id in self._bus_jobs.get(bus_id, set())
            if target_id in self._jobs
            and self._effective_deadline(self._jobs[target_id]) <= now
        ]

    def _select(self, bus_id: str, now: float) -> _Job | None:
        due = sorted(
            self._due(bus_id, now),
            key=lambda job: (
                PRIORITY_RANK[job.target.priority],
                self._effective_deadline(job),
                job.sequence,
            ),
        )
        metrics = self._metrics[bus_id]
        metrics.observe_queue(len(due))
        if not due:
            return None

        low_due = [
            job for job in due if job.target.priority == PRIORITY_LOW
        ]
        if (
            metrics.consecutive_non_low
            >= self.policy.fairness_low_burst
            and low_due
        ):
            metrics.force_fairness(
                low=True,
                deferred=len(due) - 1,
            )
            return min(
                low_due,
                key=lambda job: (
                    self._effective_deadline(job),
                    job.sequence,
                ),
            )

        non_high = [
            job for job in due if job.target.priority != PRIORITY_HIGH
        ]
        if (
            metrics.consecutive_high
            >= self.policy.fairness_high_burst
            and non_high
        ):
            metrics.force_fairness(
                low=False,
                deferred=sum(
                    job.target.priority == PRIORITY_HIGH
                    for job in due
                ),
            )
            return non_high[0]
        return due[0]

    def run_once(self, bus_id: str) -> bool:
        with self._condition:
            now = self._clock()
            job = self._select(bus_id, now)
            if job is None:
                return False
            deadline = job.next_deadline
            lag = max(0.0, now - deadline)
            self._metrics[bus_id].observe_lag(
                lag,
                self.policy.deadline_tolerance_seconds,
            )

        started = self._clock()
        result: ScheduledResult | None = None
        callback_error = False
        try:
            with self._bus_locks[bus_id]:
                result = self._read_target(job.target)
            failed = result.communication_failed
        except Exception:  # noqa: BLE001
            callback_error = True
            failed = True
            LOG.exception(
                "Scheduled acquisition callback failed for %s",
                job.target.target_id,
            )

        if result is not None:
            try:
                self._latest_store.record_attempt(job.target, result)
            except Exception:  # noqa: BLE001
                callback_error = True
                LOG.exception(
                    "Latest-value persistence failed for %s",
                    job.target.target_id,
                )

        completed = self._clock()
        self._complete(
            job,
            deadline,
            completed,
            max(0.0, completed - started),
            failed,
            callback_error=callback_error,
        )

        if result is not None:
            try:
                self._record_result(job.target, result)
            except Exception:  # noqa: BLE001
                with self._condition:
                    self._metrics[bus_id].observe_callback_error()
                LOG.exception(
                    "Scheduled result publication failed for %s",
                    job.target.target_id,
                )
        return True

    def _complete(
        self,
        job: _Job,
        deadline: float,
        completed: float,
        duration: float,
        failed: bool,
        *,
        callback_error: bool,
    ) -> None:
        with self._condition:
            current = self._jobs.get(job.target.target_id)
            if current is None:
                return
            metrics = self._metrics[job.target.bus_id]
            metrics.observe_completion(
                priority=job.target.priority,
                completed=completed,
                duration=duration,
                interval_seconds=job.target.interval_seconds,
                failed=failed,
                callback_error=callback_error,
            )

            endpoint = self._endpoints[
                (job.target.bus_id, job.target.unit_id)
            ]
            if failed:
                endpoint.failure_streak += 1
                if endpoint.failure_streak >= self.policy.failure_threshold:
                    endpoint.trip_count += 1
                    cooldown = min(
                        self.policy.cooldown_max_seconds,
                        self.policy.cooldown_initial_seconds
                        * 2 ** (endpoint.trip_count - 1),
                    )
                    endpoint.cooldown_until = completed + cooldown
                    endpoint.failure_streak = 0
                    deferred = 0
                    for target_id in self._bus_jobs.get(
                        job.target.bus_id,
                        set(),
                    ):
                        candidate = self._jobs[target_id]
                        if candidate.target.unit_id == job.target.unit_id:
                            candidate.next_deadline = max(
                                candidate.next_deadline,
                                endpoint.cooldown_until,
                            )
                            deferred += 1
                    metrics.observe_cooldown(deferred=deferred)
            else:
                endpoint.failure_streak = 0
                endpoint.trip_count = 0
                endpoint.cooldown_until = 0.0

            next_deadline = deadline + job.target.interval_seconds
            skipped = 0
            while next_deadline <= completed:
                next_deadline += job.target.interval_seconds
                skipped += 1
            current.next_deadline = max(
                next_deadline,
                endpoint.cooldown_until,
            )
            metrics.observe_skipped(skipped)
            self._condition.notify_all()

    def _run_bus(self, bus_id: str) -> None:
        try:
            while not self._stop_event.is_set():
                if self.run_once(bus_id):
                    continue
                with self._condition:
                    deadlines = [
                        self._effective_deadline(self._jobs[target_id])
                        for target_id in self._bus_jobs.get(bus_id, set())
                        if target_id in self._jobs
                    ]
                    wait = (
                        min(
                            1.0,
                            max(
                                0.01,
                                min(deadlines) - self._clock(),
                            ),
                        )
                        if deadlines
                        else 1.0
                    )
                    self._condition.wait(timeout=wait)
        except Exception as error:  # noqa: BLE001
            self._record_worker_failure(bus_id, error)
            LOG.exception(
                "Adaptive acquisition worker failed for bus %s",
                bus_id,
            )

    def current_error(self) -> str | None:
        now = self._clock()
        with self._condition:
            inactive_workers = 0
            for bus_id, target_ids in self._bus_jobs.items():
                if not target_ids:
                    continue
                thread = self._threads.get(bus_id)
                if thread is None or not thread.is_alive():
                    inactive_workers += 1

            degraded = sum(
                endpoint.failure_streak > 0
                or endpoint.cooldown_until > now
                for endpoint in self._endpoints.values()
            )

        if inactive_workers:
            return (
                "adaptive acquisition worker unavailable: "
                f"{inactive_workers} bus worker(s) inactive"
            )
        if degraded == 0:
            return None
        return (
            "adaptive acquisition degraded: "
            f"{degraded} endpoint(s) failing or in cooldown"
        )

    def target_diagnostics(
        self,
        *,
        device_family: str | None = None,
    ) -> list[dict[str, Any]]:
        now = self._clock()
        with self._condition:
            jobs = [
                job
                for job in self._jobs.values()
                if device_family is None
                or job.target.device_family == device_family
            ]
            runtime = {
                job.target.target_id: {
                    "cooldown": self._endpoints[
                        (job.target.bus_id, job.target.unit_id)
                    ].cooldown_until
                    > now,
                    "cooldown_remaining_seconds": round(
                        max(
                            0.0,
                            self._endpoints[
                                (job.target.bus_id, job.target.unit_id)
                            ].cooldown_until
                            - now,
                        ),
                        6,
                    ),
                    "next_due_in_seconds": round(
                        max(0.0, self._effective_deadline(job) - now),
                        6,
                    ),
                }
                for job in jobs
            }
            targets = {job.target.target_id: job.target for job in jobs}

        latest = self._latest_store.payloads_for(list(targets))
        diagnostics: list[dict[str, Any]] = []
        for target_id in sorted(targets):
            target = targets[target_id]
            item = latest.get(target_id)
            target_runtime = runtime[target_id]
            if item is None:
                state = "initializing"
                recovery_state = "initializing"
            else:
                quality = item.get("quality")
                state = (
                    str(quality)
                    if quality
                    in {"valid", "sensor_error", "communication_error"}
                    else "unknown"
                )
                if target_runtime["cooldown"]:
                    recovery_state = "cooldown"
                elif int(item.get("consecutive_failures", 0)) > 0:
                    recovery_state = "failing"
                elif item.get("last_recovered_at") == item.get(
                    "last_attempt_at"
                ):
                    recovery_state = "recovered"
                else:
                    recovery_state = "steady"
            diagnostics.append(
                {
                    "target_id": target_id,
                    "channel_id": target.telemetry_channel_id,
                    "state": state,
                    "recovery_state": recovery_state,
                    "last_attempt_at": (
                        item.get("last_attempt_at") if item else None
                    ),
                    "last_success_at": (
                        item.get("last_success_at") if item else None
                    ),
                    "last_error": item.get("last_error") if item else None,
                    "consecutive_failures": int(
                        item.get("consecutive_failures", 0)
                        if item
                        else 0
                    ),
                    "outcomes": {
                        "attempts": int(
                            item.get("attempts_total", 0) if item else 0
                        ),
                        "successes": int(
                            item.get("successes_total", 0) if item else 0
                        ),
                        "communication_failures": int(
                            item.get("communication_failures_total", 0)
                            if item
                            else 0
                        ),
                    },
                    **target_runtime,
                }
            )
        return diagnostics

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._condition:
            active_workers = 0
            expected_workers = 0
            buses: dict[str, dict[str, Any]] = {}

            for bus_id, metrics in sorted(self._metrics.items()):
                configured_targets = len(
                    self._bus_jobs.get(bus_id, set())
                )
                thread = self._threads.get(bus_id)
                worker_alive = (
                    thread is not None and thread.is_alive()
                )
                if configured_targets:
                    expected_workers += 1
                    if worker_alive:
                        active_workers += 1

                if not configured_targets:
                    worker_state = "idle"
                elif worker_alive:
                    worker_state = "running"
                elif self._stop_event.is_set():
                    worker_state = "stopped"
                elif self._started:
                    worker_state = "dead"
                else:
                    worker_state = "starting"

                bus_payload = metrics.snapshot(
                    now=now,
                    load_window_seconds=(
                        self.policy.bus_load_window_seconds
                    ),
                    worker_count=1 if worker_alive else 0,
                    configured_targets=configured_targets,
                    queue_depth=len(self._due(bus_id, now)),
                )
                bus_payload.update(
                    {
                        "worker_state": worker_state,
                        "worker_failures_total": (
                            self._worker_failures_total.get(bus_id, 0)
                        ),
                        "worker_restarts_total": (
                            self._worker_restarts_total.get(bus_id, 0)
                        ),
                        "last_worker_failure_type": (
                            self._worker_last_failure_type.get(bus_id)
                        ),
                        "last_worker_failure_at": (
                            self._worker_last_failure_at.get(bus_id)
                        ),
                        "last_worker_recovered_at": (
                            self._worker_last_recovered_at.get(bus_id)
                        ),
                    }
                )
                buses[bus_id] = bus_payload

            targets = [
                {
                    "target_id": job.target.target_id,
                    "bus_id": job.target.bus_id,
                    "device_family": job.target.device_family,
                    "unit_id": job.target.unit_id,
                    "priority": job.target.priority,
                    "interval_seconds": job.target.interval_seconds,
                    "next_due_in_seconds": round(
                        max(
                            0.0,
                            self._effective_deadline(job) - now,
                        ),
                        6,
                    ),
                    "cooldown": (
                        self._endpoints[
                            (job.target.bus_id, job.target.unit_id)
                        ].cooldown_until
                        > now
                    ),
                }
                for job in sorted(
                    self._jobs.values(),
                    key=lambda item: (
                        item.target.bus_id,
                        PRIORITY_RANK[item.target.priority],
                        item.target.target_id,
                    ),
                )
            ]
            return {
                "schema_version": 1,
                "polling_policy": "priority_adaptive_v1",
                "clock": "monotonic",
                "serialized_worker_per_bus": True,
                "policy": self.policy.sanitized(),
                "configured_targets": len(self._jobs),
                "expected_bus_workers": expected_workers,
                "active_bus_workers": active_workers,
                "workers_healthy": active_workers == expected_workers,
                "worker_failures_total": sum(
                    self._worker_failures_total.values()
                ),
                "worker_restarts_total": sum(
                    self._worker_restarts_total.values()
                ),
                "degraded_endpoints": sum(
                    endpoint.failure_streak > 0
                    or endpoint.cooldown_until > now
                    for endpoint in self._endpoints.values()
                ),
                "cooldown_endpoints": sum(
                    endpoint.cooldown_until > now
                    for endpoint in self._endpoints.values()
                ),
                "targets": targets,
                "buses": buses,
            }

    def latest_summary(self) -> dict[str, Any]:
        return self._latest_store.summary()

    def latest_snapshot(self, *, limit: int = 500) -> dict[str, Any]:
        return self._latest_store.snapshot(limit=limit)
