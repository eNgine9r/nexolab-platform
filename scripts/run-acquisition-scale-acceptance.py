#!/usr/bin/env python3
"""Run the deterministic Issue #289 acquisition scale matrix.

This script uses production registry, scheduler, latest-value and policy code with
fake monotonic time and read-only fake serial callbacks. It never opens a serial
port and cannot issue Modbus writes.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEVICE_AGENT = ROOT / "services" / "device-agent"
if str(DEVICE_AGENT) not in sys.path:
    sys.path.insert(0, str(DEVICE_AGENT))

from acquisition_registry import (  # noqa: E402
    AcquisitionRegistry,
    LifecycleMutation,
    build_initial_document,
)
from adaptive_scheduler import (  # noqa: E402
    AdaptiveAcquisitionScheduler,
    ScheduledResult,
    SchedulerPolicy,
    SchedulerTarget,
)
from latest_values import LatestValueStore  # noqa: E402
from main import Settings, TelemetryRecord  # noqa: E402

BUS_ID = "rs485-main"
FAST_DURATION_SECONDS = 0.002
SLOW_FAILURE_DURATION_SECONDS = 0.150
SIMULATION_HORIZON_SECONDS = 120.0


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Fake clock cannot move backwards")
        self.value += seconds


@dataclass(frozen=True)
class InventoryProfile:
    name: str
    xjp_points: tuple[tuple[int, int], ...]
    le_unit_ids: tuple[int, ...]
    expected_targets: int


@dataclass
class AssertionEvidence:
    name: str
    passed: bool
    actual: Any
    expected: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": self.actual,
            "expected": self.expected,
        }


class EvidenceCollector:
    def __init__(self) -> None:
        self.assertions: list[AssertionEvidence] = []

    def check(self, name: str, condition: bool, actual: Any, expected: Any) -> None:
        self.assertions.append(
            AssertionEvidence(
                name=name,
                passed=bool(condition),
                actual=actual,
                expected=expected,
            )
        )

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.assertions)


class MatrixHarness:
    def __init__(
        self,
        registry: AcquisitionRegistry,
        database_path: Path,
        *,
        policy: SchedulerPolicy | None = None,
    ) -> None:
        self.clock = FakeClock()
        self.wall_now = datetime(2026, 8, 5, tzinfo=timezone.utc)
        self.calls: list[str] = []
        self.active_reads = 0
        self.maximum_concurrent_reads = 0
        self.failed_units: set[int] = set()
        self.duration_by_unit: dict[int, float] = {}
        self.store = LatestValueStore(database_path)
        self.policy = policy or default_policy()

        def read_target(target: SchedulerTarget) -> ScheduledResult:
            self.active_reads += 1
            self.maximum_concurrent_reads = max(
                self.maximum_concurrent_reads,
                self.active_reads,
            )
            try:
                self.calls.append(target.target_id)
                self.clock.advance(
                    self.duration_by_unit.get(
                        target.unit_id,
                        FAST_DURATION_SECONDS,
                    )
                )
                if target.unit_id in self.failed_units:
                    return failure_result(target, self.wall_now.isoformat())
                return success_result(target, self.wall_now.isoformat())
            finally:
                self.active_reads -= 1

        self.scheduler = AdaptiveAcquisitionScheduler(
            registry,
            policy=self.policy,
            latest_store=self.store,
            read_target=read_target,
            record_result=lambda target, result: None,
            stop_event=threading.Event(),
            bus_locks={BUS_ID: threading.Lock()},
            clock=self.clock,
            wall_clock=lambda: self.wall_now,
        )

    def simulate(self, horizon_seconds: float) -> dict[str, Any]:
        finish = self.clock.value + horizon_seconds
        iterations = 0
        while self.clock.value < finish:
            iterations += 1
            if iterations > 1_000_000:
                raise RuntimeError("Scale matrix exceeded iteration guard")
            if self.scheduler.run_once(BUS_ID):
                continue
            deadlines = [
                self.scheduler._effective_deadline(job)  # noqa: SLF001
                for job in self.scheduler._jobs.values()  # noqa: SLF001
                if job.target.bus_id == BUS_ID
            ]
            if not deadlines:
                self.clock.advance(finish - self.clock.value)
                break
            next_deadline = min(deadlines)
            if next_deadline >= finish:
                self.clock.advance(finish - self.clock.value)
                break
            self.clock.advance(max(0.000001, next_deadline - self.clock.value))
        return self.scheduler.snapshot()

    def make_due(self, target_ids: Iterable[str] | None = None) -> None:
        selected = set(target_ids) if target_ids is not None else None
        for target_id, job in self.scheduler._jobs.items():  # noqa: SLF001
            job.next_deadline = (
                self.clock.value
                if selected is None or target_id in selected
                else self.clock.value + 10_000
            )


def default_policy() -> SchedulerPolicy:
    return SchedulerPolicy(
        high_interval_seconds=5,
        medium_interval_seconds=10,
        low_interval_seconds=30,
        startup_spread_seconds=5,
        failure_threshold=3,
        cooldown_initial_seconds=30,
        cooldown_max_seconds=300,
        fairness_high_burst=8,
        fairness_low_burst=12,
        deadline_tolerance_seconds=0.05,
        bus_load_window_seconds=60,
    )


def settings(
    database_path: Path,
    *,
    xjp_points: tuple[tuple[int, int], ...],
    le_unit_ids: tuple[int, ...],
) -> Settings:
    return Settings(
        node_id="edge-scale-acceptance",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="issue-289",
        sample_interval_seconds=5,
        database_path=database_path,
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="modbus",
        serial_device="/dev/serial/by-id/deterministic-read-only-fixture",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=xjp_points,
        xjp60d_scale=0.1,
        le01mp_unit_ids=le_unit_ids,
    )


def build_registry(profile: InventoryProfile, database_path: Path) -> AcquisitionRegistry:
    xjp_units = tuple(sorted({unit_id for unit_id, _ in profile.xjp_points}))
    document = build_initial_document(
        settings(
            database_path,
            xjp_points=profile.xjp_points,
            le_unit_ids=profile.le_unit_ids,
        ),
        discovery_units=xjp_units,
        legacy_active_points=profile.xjp_points,
    )
    return AcquisitionRegistry(document)


def success_result(target: SchedulerTarget, captured_at: str) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"success-{target.target_id}-{captured_at}",
            node_id="edge-scale-acceptance",
            captured_at=captured_at,
            metric=target.metric,
            value=4.2,
            unit=target.unit,
            quality="valid",
            source="deterministic-read-only-fixture",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=False,
    )


def failure_result(target: SchedulerTarget, captured_at: str) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"failure-{target.target_id}-{captured_at}",
            node_id="edge-scale-acceptance",
            captured_at=captured_at,
            metric=target.metric,
            value=None,
            unit=target.unit,
            quality="communication_error",
            source="deterministic-read-only-fixture",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=True,
        error="deterministic timeout",
    )


def xjp_points(start: int, count: int) -> tuple[tuple[int, int], ...]:
    return tuple(
        (unit_id, channel)
        for unit_id in range(start, start + count)
        for channel in range(1, 7)
    )


def profiles() -> tuple[InventoryProfile, ...]:
    return (
        InventoryProfile(
            name="pilot",
            xjp_points=((106, 3), (106, 4)),
            le_unit_ids=(200, 201, 202, 203),
            expected_targets=38,
        ),
        InventoryProfile(
            name="expanded",
            xjp_points=xjp_points(101, 12),
            le_unit_ids=tuple(range(200, 208)),
            expected_targets=144,
        ),
        InventoryProfile(
            name="stress",
            xjp_points=xjp_points(101, 24),
            le_unit_ids=tuple(range(200, 212)),
            expected_targets=252,
        ),
    )


def theoretical_load_percent(
    scheduler: AdaptiveAcquisitionScheduler,
    duration_seconds: float,
) -> float:
    load = sum(
        duration_seconds / job.target.interval_seconds
        for job in scheduler._jobs.values()  # noqa: SLF001
    )
    return round(load * 100, 3)


def run_healthy_profile(
    profile: InventoryProfile,
    directory: Path,
    collector: EvidenceCollector,
) -> dict[str, Any]:
    registry = build_registry(profile, directory / f"{profile.name}.db")
    harness = MatrixHarness(registry, directory / f"{profile.name}.db")
    snapshot = harness.simulate(SIMULATION_HORIZON_SECONDS)
    bus = snapshot["buses"][BUS_ID]
    theoretical = theoretical_load_percent(
        harness.scheduler,
        FAST_DURATION_SECONDS,
    )

    collector.check(
        f"{profile.name}.configured_targets",
        snapshot["configured_targets"] == profile.expected_targets,
        snapshot["configured_targets"],
        profile.expected_targets,
    )
    collector.check(
        f"{profile.name}.serialized_reads",
        harness.maximum_concurrent_reads == 1,
        harness.maximum_concurrent_reads,
        1,
    )
    collector.check(
        f"{profile.name}.communication_failures",
        bus["communication_failures_total"] == 0,
        bus["communication_failures_total"],
        0,
    )
    collector.check(
        f"{profile.name}.callback_errors",
        bus["callback_errors_total"] == 0,
        bus["callback_errors_total"],
        0,
    )
    collector.check(
        f"{profile.name}.overruns",
        bus["overrun_total"] == 0,
        bus["overrun_total"],
        0,
    )
    collector.check(
        f"{profile.name}.cooldowns",
        bus["cooldown_entered_total"] == 0,
        bus["cooldown_entered_total"],
        0,
    )
    collector.check(
        f"{profile.name}.planning_load",
        theoretical < 70,
        theoretical,
        "< 70%",
    )
    collector.check(
        f"{profile.name}.priority_coverage",
        all(value > 0 for value in bus["executions_by_priority"].values()),
        bus["executions_by_priority"],
        "every configured priority executes",
    )
    collector.check(
        f"{profile.name}.queue_bound",
        bus["max_queue_depth"] <= profile.expected_targets,
        bus["max_queue_depth"],
        f"<= {profile.expected_targets}",
    )

    return {
        "profile": profile.name,
        "active_targets": profile.expected_targets,
        "simulation_horizon_seconds": SIMULATION_HORIZON_SECONDS,
        "fake_request_duration_seconds": FAST_DURATION_SECONDS,
        "theoretical_bus_load_percent": theoretical,
        "maximum_concurrent_reads": harness.maximum_concurrent_reads,
        "bus": bus,
    }


def run_ineligible_filter(
    profile: InventoryProfile,
    directory: Path,
    collector: EvidenceCollector,
) -> dict[str, Any]:
    registry = build_registry(profile, directory / "inactive.db")
    eligible = registry.eligible_targets()
    disabled_ids = {
        target.target_id
        for index, target in enumerate(eligible)
        if index % 4 == 0
    }
    document, _ = registry.with_mutations(
        device_mutations=(),
        target_mutations=tuple(
            LifecycleMutation(target_id=target_id, lifecycle="disabled")
            for target_id in sorted(disabled_ids)
        ),
    )
    filtered = AcquisitionRegistry(document)
    harness = MatrixHarness(filtered, directory / "inactive.db")
    snapshot = harness.simulate(60)
    called = set(harness.calls)
    configured = snapshot["configured_targets"]

    collector.check(
        "ineligible.zero_executions",
        called.isdisjoint(disabled_ids),
        sorted(called & disabled_ids),
        [],
    )
    collector.check(
        "ineligible.configured_target_count",
        configured == profile.expected_targets - len(disabled_ids),
        configured,
        profile.expected_targets - len(disabled_ids),
    )
    return {
        "source_profile": profile.name,
        "disabled_targets": len(disabled_ids),
        "configured_targets": configured,
        "disabled_executions": sorted(called & disabled_ids),
    }


def run_failure_isolation(
    directory: Path,
    collector: EvidenceCollector,
) -> dict[str, Any]:
    profile = profiles()[0]
    registry = build_registry(profile, directory / "failure.db")
    harness = MatrixHarness(registry, directory / "failure.db")
    failing_id = "le01mp:200-voltage"
    healthy_id = "xjp60d:106-03"
    failing_target = harness.scheduler._jobs[failing_id].target  # noqa: SLF001
    initial_captured_at = "2026-08-05T00:00:00+00:00"
    harness.store.record_attempt(
        failing_target,
        success_result(failing_target, initial_captured_at),
    )
    harness.failed_units.add(200)
    harness.duration_by_unit[200] = SLOW_FAILURE_DURATION_SECONDS

    for _ in range(harness.policy.failure_threshold):
        harness.make_due((failing_id,))
        if not harness.scheduler.run_once(BUS_ID):
            raise RuntimeError("Failing target did not execute")

    snapshot_after_failure = harness.scheduler.snapshot()
    endpoint = harness.scheduler._endpoints[(BUS_ID, 200)]  # noqa: SLF001
    sibling_deadlines = [
        job.next_deadline
        for job in harness.scheduler._jobs.values()  # noqa: SLF001
        if job.target.unit_id == 200
    ]
    harness.make_due((healthy_id,))
    if not harness.scheduler.run_once(BUS_ID):
        raise RuntimeError("Healthy target did not execute after cooldown")
    final_snapshot = harness.scheduler.snapshot()
    bus = final_snapshot["buses"][BUS_ID]
    latest = next(
        item
        for item in harness.store.snapshot()["items"]
        if item["target_id"] == failing_id
    )

    collector.check(
        "failure.cooldown_entered_once",
        bus["cooldown_entered_total"] == 1,
        bus["cooldown_entered_total"],
        1,
    )
    collector.check(
        "failure.endpoint_in_cooldown",
        snapshot_after_failure["cooldown_endpoints"] == 1,
        snapshot_after_failure["cooldown_endpoints"],
        1,
    )
    collector.check(
        "failure.siblings_deferred",
        all(deadline >= endpoint.cooldown_until for deadline in sibling_deadlines),
        sibling_deadlines,
        f">= {endpoint.cooldown_until}",
    )
    collector.check(
        "failure.healthy_endpoint_continues",
        harness.calls[-1] == healthy_id,
        harness.calls[-1],
        healthy_id,
    )
    collector.check(
        "failure.maximum_concurrency",
        harness.maximum_concurrent_reads == 1,
        harness.maximum_concurrent_reads,
        1,
    )
    collector.check(
        "failure.latest_value_retained",
        latest["value"] == 4.2 and latest["captured_at"] == initial_captured_at,
        {"value": latest["value"], "captured_at": latest["captured_at"]},
        {"value": 4.2, "captured_at": initial_captured_at},
    )
    collector.check(
        "failure.quality_truthful",
        latest["quality"] == "communication_error"
        and latest["last_error"] == "deterministic timeout",
        {"quality": latest["quality"], "last_error": latest["last_error"]},
        {
            "quality": "communication_error",
            "last_error": "deterministic timeout",
        },
    )
    return {
        "failure_threshold": harness.policy.failure_threshold,
        "failing_unit_id": 200,
        "slow_failure_duration_seconds": SLOW_FAILURE_DURATION_SECONDS,
        "cooldown_until": endpoint.cooldown_until,
        "healthy_execution_after_cooldown": harness.calls[-1],
        "maximum_concurrent_reads": harness.maximum_concurrent_reads,
        "latest_value": latest,
        "bus": bus,
    }


def only_targets(
    registry: AcquisitionRegistry,
    target_ids: set[str],
) -> AcquisitionRegistry:
    document, _ = registry.with_mutations(
        device_mutations=(),
        target_mutations=tuple(
            LifecycleMutation(target.target_id, "disabled")
            for target in registry.eligible_targets()
            if target.target_id not in target_ids
        ),
    )
    return AcquisitionRegistry(document)


def run_fairness_and_overrun(
    directory: Path,
    collector: EvidenceCollector,
) -> dict[str, Any]:
    profile = profiles()[0]
    source = build_registry(profile, directory / "fairness.db")
    fairness_targets = {
        "xjp60d:106-03",
        "le01mp:200-voltage",
        "le01mp:200-reactive-power",
    }
    fairness_policy = SchedulerPolicy(
        high_interval_seconds=5,
        medium_interval_seconds=10,
        low_interval_seconds=30,
        startup_spread_seconds=1,
        failure_threshold=3,
        cooldown_initial_seconds=30,
        cooldown_max_seconds=300,
        fairness_high_burst=2,
        fairness_low_burst=3,
        deadline_tolerance_seconds=0.05,
        bus_load_window_seconds=60,
    )
    fairness = MatrixHarness(
        only_targets(source, fairness_targets),
        directory / "fairness.db",
        policy=fairness_policy,
    )
    for _ in range(4):
        fairness.make_due()
        fairness.scheduler.run_once(BUS_ID)
    fairness_bus = fairness.scheduler.snapshot()["buses"][BUS_ID]
    expected_order = [
        "xjp60d:106-03",
        "xjp60d:106-03",
        "le01mp:200-voltage",
        "le01mp:200-reactive-power",
    ]
    collector.check(
        "fairness.selection_order",
        fairness.calls == expected_order,
        fairness.calls,
        expected_order,
    )
    collector.check(
        "fairness.forced_counts",
        fairness_bus["fairness_forced_total"] == 2
        and fairness_bus["fairness_forced_low_total"] == 1,
        {
            "total": fairness_bus["fairness_forced_total"],
            "low": fairness_bus["fairness_forced_low_total"],
        },
        {"total": 2, "low": 1},
    )

    overrun_source = build_registry(profile, directory / "overrun.db")
    overrun = MatrixHarness(
        only_targets(overrun_source, {"xjp60d:106-03"}),
        directory / "overrun.db",
    )
    overrun.duration_by_unit[106] = 16.0
    overrun.make_due()
    overrun.scheduler.run_once(BUS_ID)
    overrun_snapshot = overrun.scheduler.snapshot()
    overrun_bus = overrun_snapshot["buses"][BUS_ID]
    next_due = overrun_snapshot["targets"][0]["next_due_in_seconds"]
    collector.check(
        "overrun.counters",
        overrun_bus["overrun_total"] == 1
        and overrun_bus["deadline_skipped_total"] == 3,
        {
            "overrun_total": overrun_bus["overrun_total"],
            "deadline_skipped_total": overrun_bus["deadline_skipped_total"],
        },
        {"overrun_total": 1, "deadline_skipped_total": 3},
    )
    collector.check(
        "overrun.no_catch_up_burst",
        next_due == 4.0,
        next_due,
        4.0,
    )
    return {
        "fairness": {
            "order": fairness.calls,
            "bus": fairness_bus,
        },
        "overrun": {
            "bus": overrun_bus,
            "next_due_in_seconds": next_due,
        },
    }


def run_matrix(output: Path) -> dict[str, Any]:
    collector = EvidenceCollector()
    with tempfile.TemporaryDirectory(prefix="nexolab-acquisition-scale-") as temporary:
        directory = Path(temporary)
        healthy = [
            run_healthy_profile(profile, directory, collector)
            for profile in profiles()
        ]
        inactive = run_ineligible_filter(profiles()[1], directory, collector)
        failure = run_failure_isolation(directory, collector)
        fairness = run_fairness_and_overrun(directory, collector)

    payload = {
        "schema_version": 1,
        "classification": "deterministic_software",
        "source_commit": "provided_by_ci_environment",
        "safety": {
            "serial_port_opened": False,
            "modbus_write_attempts": 0,
            "production_data_used": False,
        },
        "declared_targets_document": "docs/operations/acquisition-scale-acceptance.md",
        "profiles": healthy,
        "ineligible_filter": inactive,
        "failure_isolation": failure,
        "fairness_and_overrun": fairness,
        "assertions": [item.as_dict() for item in collector.assertions],
        "passed": collector.passed,
        "completion_classification": (
            "software verified; hardware performance acceptance pending"
            if collector.passed
            else "deterministic software acceptance failed"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("acquisition-scale-evidence/acquisition-scale-matrix.json"),
    )
    args = parser.parse_args()
    payload = run_matrix(args.output)
    print(json.dumps({
        "passed": payload["passed"],
        "output": str(args.output),
        "completion_classification": payload["completion_classification"],
        "assertion_count": len(payload["assertions"]),
    }, sort_keys=True))
    if not payload["passed"]:
        failed = [
            item for item in payload["assertions"] if not item["passed"]
        ]
        print(json.dumps({"failed_assertions": failed}, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
