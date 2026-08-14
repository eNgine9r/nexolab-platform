from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from acquisition_registry import (
    AcquisitionRegistry,
    DeviceLifecycleMutation,
    LifecycleMutation,
    build_initial_document,
)
from adaptive_scheduler import (
    AdaptiveAcquisitionScheduler,
    ScheduledResult,
    SchedulerPolicy,
    SchedulerTarget,
)
from latest_values import LatestValueStore
from main import Settings, TelemetryRecord


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def settings(database_path: Path) -> Settings:
    return Settings(
        node_id="edge-01",
        organization_id=None,
        mqtt_host="mqtt",
        mqtt_port=1883,
        mqtt_topic="nexolab/telemetry",
        health_interval_seconds=30,
        software_version="test",
        sample_interval_seconds=5,
        database_path=database_path,
        health_host="127.0.0.1",
        health_port=8081,
        device_mode="modbus",
        serial_device="/dev/serial/by-id/test",
        serial_baudrate=9600,
        serial_parity="N",
        serial_stopbits=1,
        serial_timeout_seconds=0.3,
        serial_retries=1,
        xjp60d_points=((106, 3), (106, 4)),
        xjp60d_scale=0.1,
        le01mp_unit_ids=(200,),
    )


def registry(
    database_path: Path,
    *,
    active_target_ids: set[str] | None = None,
) -> AcquisitionRegistry:
    current = AcquisitionRegistry(
        build_initial_document(
            settings(database_path),
            discovery_units=(106,),
            legacy_active_points=((106, 3), (106, 4)),
        )
    )
    if active_target_ids is None:
        return current
    mutations = tuple(
        LifecycleMutation(target.target_id, "disabled")
        for target in current.document.targets
        if current.effective_poll_eligible(target)
        and target.target_id not in active_target_ids
    )
    if not mutations:
        return current
    document, _ = current.with_mutations(
        device_mutations=(),
        target_mutations=mutations,
    )
    return AcquisitionRegistry(document)


def success_result(
    target: SchedulerTarget,
    captured_at: str,
) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"event-{target.target_id}",
            node_id="edge-01",
            captured_at=captured_at,
            metric=target.metric,
            value=4.2,
            unit=target.unit,
            quality="valid",
            source="test",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=False,
    )


def failure_result(
    target: SchedulerTarget,
    captured_at: str,
) -> ScheduledResult:
    return ScheduledResult(
        record=TelemetryRecord(
            event_id=f"event-{target.target_id}",
            node_id="edge-01",
            captured_at=captured_at,
            metric=target.metric,
            value=None,
            unit=target.unit,
            quality="communication_error",
            source="test",
            equipment_id=target.device_id,
            channel_id=target.telemetry_channel_id,
        ),
        communication_failed=True,
        error="timeout",
    )


class SchedulerHarness:
    def __init__(
        self,
        current: AcquisitionRegistry,
        database_path: Path,
        *,
        policy: SchedulerPolicy | None = None,
    ) -> None:
        self.clock = FakeClock()
        self.wall_now = datetime(2026, 8, 5, tzinfo=timezone.utc)
        self.calls: list[str] = []
        self.results: dict[str, ScheduledResult] = {}
        self.store = LatestValueStore(database_path)
        self.policy = policy or SchedulerPolicy(
            high_interval_seconds=5,
            medium_interval_seconds=10,
            low_interval_seconds=30,
            startup_spread_seconds=1,
            failure_threshold=2,
            cooldown_initial_seconds=10,
            cooldown_max_seconds=20,
            fairness_high_burst=2,
            fairness_low_burst=3,
        )

        def read_target(target: SchedulerTarget) -> ScheduledResult:
            self.calls.append(target.target_id)
            return self.results.get(
                target.target_id,
                success_result(target, self.wall_now.isoformat()),
            )

        self.scheduler = AdaptiveAcquisitionScheduler(
            current,
            policy=self.policy,
            latest_store=self.store,
            read_target=read_target,
            record_result=lambda target, result: None,
            stop_event=threading.Event(),
            bus_locks={"rs485-main": threading.Lock()},
            clock=self.clock,
            wall_clock=lambda: self.wall_now,
        )

    def make_all_due(self) -> None:
        for job in self.scheduler._jobs.values():  # noqa: SLF001
            job.next_deadline = self.clock.value


class SchedulerPolicyTests(unittest.TestCase):
    def test_defaults_never_accelerate_below_legacy_interval(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            policy = SchedulerPolicy.from_environment(
                legacy_interval_seconds=12
            )

        self.assertEqual(policy.high_interval_seconds, 12)
        self.assertEqual(policy.medium_interval_seconds, 12)
        self.assertEqual(policy.low_interval_seconds, 30)

    def test_invalid_interval_order_is_rejected(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ACQUISITION_HIGH_INTERVAL_SECONDS": "30",
                "ACQUISITION_MEDIUM_INTERVAL_SECONDS": "10",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "high <= medium <= low"):
                SchedulerPolicy.from_environment(
                    legacy_interval_seconds=5
                )


class AdaptiveSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "edge.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_registry_jobs_have_explicit_priority_and_interval(self) -> None:
        current = registry(self.database_path)
        harness = SchedulerHarness(current, self.database_path)

        snapshot = harness.scheduler.snapshot()
        targets = {
            item["target_id"]: item
            for item in snapshot["targets"]
        }

        self.assertEqual(
            targets["xjp60d:106-03"]["priority"],
            "high",
        )
        self.assertEqual(
            targets["xjp60d:106-03"]["interval_seconds"],
            5,
        )
        self.assertEqual(
            targets["le01mp:200-voltage"]["priority"],
            "medium",
        )
        self.assertEqual(
            targets["le01mp:200-reactive-power"]["priority"],
            "low",
        )
        self.assertNotIn("xjp60d:106-01", targets)

    def test_enrollment_adds_no_job_until_explicit_running_activation(self) -> None:
        current = registry(self.database_path)
        enrolled_document, _ = current.with_xjp60d_enrollment((126,))
        enrolled = AcquisitionRegistry(enrolled_document)
        harness = SchedulerHarness(enrolled, self.database_path)

        self.assertNotIn(
            "xjp60d:126-04",
            {item["target_id"] for item in harness.scheduler.snapshot()["targets"]},
        )

        active_document, _ = enrolled.with_mutations(
            device_mutations=(
                DeviceLifecycleMutation("xjp60d-126", "active"),
            ),
            target_mutations=(
                LifecycleMutation("xjp60d:126-04", "active"),
            ),
        )
        harness.scheduler.reconcile(AcquisitionRegistry(active_document))
        targets = {
            item["target_id"]: item
            for item in harness.scheduler.snapshot()["targets"]
        }

        self.assertIn("xjp60d:126-04", targets)
        self.assertGreater(targets["xjp60d:126-04"]["next_due_in_seconds"], 0)
        self.assertLessEqual(targets["xjp60d:126-04"]["next_due_in_seconds"], 1)

        harness.clock.advance(1)
        for _ in range(len(targets)):
            if "xjp60d:126-04" in harness.calls:
                break
            self.assertTrue(harness.scheduler.run_once("rs485-main"))
        self.assertIn("xjp60d:126-04", harness.calls)
        diagnostic = next(
            item
            for item in harness.scheduler.target_diagnostics(
                device_family="xjp60d"
            )
            if item["target_id"] == "xjp60d:126-04"
        )
        self.assertEqual(diagnostic["state"], "valid")
        self.assertEqual(diagnostic["outcomes"]["attempts"], 1)

    def test_priority_and_bounded_low_fairness(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={
                "xjp60d:106-03",
                "le01mp:200-voltage",
                "le01mp:200-reactive-power",
            },
        )
        harness = SchedulerHarness(current, self.database_path)

        harness.make_all_due()
        harness.scheduler.run_once("rs485-main")
        harness.make_all_due()
        harness.scheduler.run_once("rs485-main")
        harness.make_all_due()
        harness.scheduler.run_once("rs485-main")
        harness.make_all_due()
        harness.scheduler.run_once("rs485-main")

        self.assertEqual(
            harness.calls,
            [
                "xjp60d:106-03",
                "xjp60d:106-03",
                "le01mp:200-voltage",
                "le01mp:200-reactive-power",
            ],
        )
        bus = harness.scheduler.snapshot()["buses"]["rs485-main"]
        self.assertEqual(bus["fairness_forced_total"], 2)
        self.assertEqual(bus["fairness_forced_low_total"], 1)

    def test_repeated_failure_cools_down_only_the_endpoint(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={
                "xjp60d:106-03",
                "le01mp:200-voltage",
                "le01mp:200-current",
            },
        )
        harness = SchedulerHarness(current, self.database_path)
        target_id = "le01mp:200-voltage"
        target = harness.scheduler._jobs[target_id].target  # noqa: SLF001
        harness.results[target_id] = failure_result(
            target,
            harness.wall_now.isoformat(),
        )

        for _ in range(2):
            harness.make_all_due()
            harness.scheduler._jobs[  # noqa: SLF001
                "xjp60d:106-03"
            ].next_deadline = 999
            harness.scheduler._jobs[  # noqa: SLF001
                "le01mp:200-current"
            ].next_deadline = 999
            harness.scheduler.run_once("rs485-main")

        endpoint = harness.scheduler._endpoints[  # noqa: SLF001
            ("rs485-main", 200)
        ]
        sibling = harness.scheduler._jobs[  # noqa: SLF001
            "le01mp:200-current"
        ]
        other = harness.scheduler._jobs[  # noqa: SLF001
            "xjp60d:106-03"
        ]
        self.assertEqual(endpoint.cooldown_until, 10)
        self.assertGreaterEqual(sibling.next_deadline, 10)

        other.next_deadline = harness.clock.value
        self.assertTrue(harness.scheduler.run_once("rs485-main"))
        self.assertEqual(harness.calls[-1], "xjp60d:106-03")
        snapshot = harness.scheduler.snapshot()
        self.assertEqual(snapshot["cooldown_endpoints"], 1)
        self.assertEqual(
            snapshot["buses"]["rs485-main"][
                "cooldown_entered_total"
            ],
            1,
        )

    def test_overrun_skips_expired_deadlines_without_burst(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={"xjp60d:106-03"},
        )
        harness = SchedulerHarness(current, self.database_path)
        harness.make_all_due()

        def slow_read(target: SchedulerTarget) -> ScheduledResult:
            harness.clock.advance(16)
            return success_result(
                target,
                harness.wall_now.isoformat(),
            )

        harness.scheduler._read_target = slow_read  # noqa: SLF001
        harness.scheduler.run_once("rs485-main")

        bus = harness.scheduler.snapshot()["buses"]["rs485-main"]
        self.assertEqual(bus["overrun_total"], 1)
        self.assertEqual(bus["deadline_skipped_total"], 3)
        self.assertEqual(bus["skipped_total"], 3)
        next_due = harness.scheduler.snapshot()["targets"][0][
            "next_due_in_seconds"
        ]
        self.assertEqual(next_due, 4)

    def test_latest_value_survives_communication_error(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={"xjp60d:106-03"},
        )
        harness = SchedulerHarness(current, self.database_path)
        target = next(
            iter(harness.scheduler._jobs.values())  # noqa: SLF001
        ).target

        success_at = "2026-08-05T00:00:00+00:00"
        failure_at = "2026-08-05T00:00:05+00:00"
        harness.store.record_attempt(
            target,
            success_result(target, success_at),
        )
        harness.store.record_attempt(
            target,
            failure_result(target, failure_at),
        )

        item = harness.store.snapshot()["items"][0]
        self.assertEqual(item["value"], 4.2)
        self.assertEqual(item["captured_at"], success_at)
        self.assertEqual(item["last_success_at"], success_at)
        self.assertEqual(item["last_attempt_at"], failure_at)
        self.assertEqual(item["quality"], "communication_error")
        self.assertEqual(item["last_error"], "timeout")
        self.assertEqual(item["attempts_total"], 2)
        self.assertEqual(item["successes_total"], 1)
        self.assertEqual(item["communication_failures_total"], 1)
        self.assertEqual(item["consecutive_failures"], 1)

    def test_target_diagnostics_distinguish_initial_failure_and_recovery(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={"xjp60d:106-03"},
        )
        harness = SchedulerHarness(current, self.database_path)
        target = harness.scheduler._jobs[  # noqa: SLF001
            "xjp60d:106-03"
        ].target

        initial = harness.scheduler.target_diagnostics(
            device_family="xjp60d"
        )[0]
        self.assertEqual(initial["state"], "initializing")
        self.assertEqual(initial["outcomes"]["attempts"], 0)

        harness.store.record_attempt(
            target,
            failure_result(target, "2026-08-05T00:00:00+00:00"),
        )
        failing = harness.scheduler.target_diagnostics(
            device_family="xjp60d"
        )[0]
        self.assertEqual(failing["state"], "communication_error")
        self.assertEqual(failing["recovery_state"], "failing")
        self.assertEqual(failing["consecutive_failures"], 1)

        harness.store.record_attempt(
            target,
            success_result(target, "2026-08-05T00:00:05+00:00"),
        )
        recovered = harness.scheduler.target_diagnostics(
            device_family="xjp60d"
        )[0]
        self.assertEqual(recovered["state"], "valid")
        self.assertEqual(recovered["recovery_state"], "recovered")
        self.assertEqual(recovered["consecutive_failures"], 0)

    def test_restart_uses_latest_attempt_and_staggers_startup(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={
                "xjp60d:106-03",
                "xjp60d:106-04",
            },
        )
        first = SchedulerHarness(current, self.database_path)
        target = first.scheduler._jobs[  # noqa: SLF001
            "xjp60d:106-03"
        ].target
        attempted_at = (
            first.wall_now - timedelta(seconds=1)
        ).isoformat()
        first.store.record_attempt(
            target,
            success_result(target, attempted_at),
        )

        restarted = SchedulerHarness(current, self.database_path)
        snapshot = {
            item["target_id"]: item
            for item in restarted.scheduler.snapshot()["targets"]
        }
        self.assertEqual(
            snapshot["xjp60d:106-03"]["next_due_in_seconds"],
            4,
        )
        self.assertGreater(
            snapshot["xjp60d:106-04"]["next_due_in_seconds"],
            0,
        )
        self.assertFalse(
            restarted.scheduler.run_once("rs485-main")
        )

    def test_reconcile_removes_newly_ineligible_target(self) -> None:
        current = registry(
            self.database_path,
            active_target_ids={
                "xjp60d:106-03",
                "xjp60d:106-04",
            },
        )
        harness = SchedulerHarness(current, self.database_path)
        document, _ = current.with_mutations(
            device_mutations=(),
            target_mutations=(
                LifecycleMutation("xjp60d:106-04", "disabled"),
            ),
        )

        harness.scheduler.reconcile(
            AcquisitionRegistry(document)
        )

        target_ids = {
            item["target_id"]
            for item in harness.scheduler.snapshot()["targets"]
        }
        self.assertEqual(target_ids, {"xjp60d:106-03"})


    def test_dead_worker_is_recovered_once_without_catch_up_burst(
        self,
    ) -> None:
        current = registry(
            self.database_path,
            active_target_ids={"xjp60d:106-03"},
        )
        harness = SchedulerHarness(current, self.database_path)
        original_run_once = harness.scheduler.run_once
        fault_injected = threading.Event()
        first_call = True

        def fail_once(bus_id: str) -> bool:
            nonlocal first_call
            if first_call:
                first_call = False
                fault_injected.set()
                raise RuntimeError("deterministic worker fault")
            return original_run_once(bus_id)

        harness.scheduler.run_once = fail_once  # type: ignore[method-assign]
        harness.scheduler.start()
        try:
            self.assertTrue(fault_injected.wait(timeout=1))

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                failed = harness.scheduler.snapshot()
                if failed["active_bus_workers"] == 0:
                    break
                time.sleep(0.01)

            failed = harness.scheduler.snapshot()
            self.assertEqual(failed["expected_bus_workers"], 1)
            self.assertEqual(failed["active_bus_workers"], 0)
            self.assertFalse(failed["workers_healthy"])
            self.assertEqual(failed["worker_failures_total"], 1)
            self.assertEqual(
                failed["buses"]["rs485-main"]["worker_state"],
                "dead",
            )
            self.assertEqual(
                failed["buses"]["rs485-main"][
                    "last_worker_failure_type"
                ],
                "RuntimeError",
            )
            self.assertIn(
                "worker unavailable",
                harness.scheduler.current_error() or "",
            )

            harness.clock.advance(16)
            self.assertEqual(harness.scheduler.supervise_workers(), 1)

            recovered = harness.scheduler.snapshot()
            self.assertEqual(recovered["active_bus_workers"], 1)
            self.assertTrue(recovered["workers_healthy"])
            self.assertEqual(recovered["worker_restarts_total"], 1)
            self.assertEqual(
                recovered["buses"]["rs485-main"][
                    "worker_restarts_total"
                ],
                1,
            )

            thread = harness.scheduler._threads[  # noqa: SLF001
                "rs485-main"
            ]
            self.assertEqual(harness.scheduler.supervise_workers(), 0)
            self.assertIs(
                harness.scheduler._threads["rs485-main"],  # noqa: SLF001
                thread,
            )
            self.assertEqual(harness.calls, [])

            target = recovered["targets"][0]
            next_due = float(target["next_due_in_seconds"])
            self.assertGreater(next_due, 0)
            self.assertGreater(
                recovered["buses"]["rs485-main"][
                    "deadline_skipped_total"
                ],
                0,
            )

            harness.clock.advance(next_due + 0.1)
            with harness.scheduler._condition:  # noqa: SLF001
                harness.scheduler._condition.notify_all()  # noqa: SLF001

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not harness.calls:
                time.sleep(0.01)

            self.assertEqual(
                harness.calls,
                ["xjp60d:106-03"],
            )
        finally:
            harness.scheduler.stop()


if __name__ == "__main__":
    unittest.main()
