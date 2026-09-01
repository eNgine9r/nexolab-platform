from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "device-agent-deployment-health-gate.py"
DEPLOY = ROOT / "scripts" / "deploy-current-head-raspberry-pi.sh"
SPEC = importlib.util.spec_from_file_location("device_agent_deployment_health_gate", HELPER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeRuntime:
    def __init__(
        self,
        *,
        container_ids: list[list[str]] | None = None,
        health_statuses: list[str] | None = None,
        running: bool = True,
    ) -> None:
        self.container_ids = container_ids or [["container-a"]]
        self.health_statuses = health_statuses or ["healthy"]
        self.running = running
        self.list_calls = 0
        self.inspect_calls = 0

    def list_container_ids(self) -> list[str]:
        index = min(self.list_calls, len(self.container_ids) - 1)
        self.list_calls += 1
        return self.container_ids[index]

    def inspect_state(self, container_id: str) -> dict[str, object]:
        index = min(self.inspect_calls, len(self.health_statuses) - 1)
        self.inspect_calls += 1
        return {
            "Running": self.running,
            "Health": {"Status": self.health_statuses[index]},
        }


def healthy_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "mqtt_connected": True,
        "acquisition": {
            "scheduler": {
                "workers_healthy": True,
                "expected_bus_workers": 2,
                "active_bus_workers": 2,
            }
        },
    }


class DeploymentHealthGateTests(unittest.TestCase):
    def run_gate(
        self,
        runtime: FakeRuntime,
        *,
        payload: dict[str, object] | None = None,
        payloads: list[dict[str, object]] | None = None,
        timeout: float = 6.0,
        poll: float = 2.0,
    ) -> FakeClock:
        clock = FakeClock()
        health_payloads = payloads or [payload or healthy_payload()]
        health_calls = 0

        def fetch_health(_url: str) -> dict[str, object]:
            nonlocal health_calls
            index = min(health_calls, len(health_payloads) - 1)
            health_calls += 1
            return health_payloads[index]

        MODULE.wait_for_deployment_health(
            runtime,
            expected_container_id="container-a",
            health_url="http://127.0.0.1:8081/health",
            timeout_seconds=timeout,
            poll_seconds=poll,
            clock=clock,
            sleeper=clock.sleep,
            health_fetcher=fetch_health,
        )
        clock.health_calls = health_calls  # type: ignore[attr-defined]
        return clock

    def test_immediate_healthy_succeeds(self) -> None:
        runtime = FakeRuntime(health_statuses=["healthy"])
        clock = self.run_gate(runtime)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(runtime.inspect_calls, 1)

    def test_starting_then_healthy_within_deadline_succeeds(self) -> None:
        runtime = FakeRuntime(health_statuses=["starting", "starting", "healthy"])
        clock = self.run_gate(runtime)
        self.assertEqual(clock.sleeps, [2.0, 2.0])
        self.assertEqual(runtime.inspect_calls, 3)


    def test_healthy_docker_waits_for_mqtt_to_connect(self) -> None:
        not_ready = healthy_payload()
        not_ready["mqtt_connected"] = False
        runtime = FakeRuntime(health_statuses=["healthy", "healthy"])
        clock = self.run_gate(runtime, payloads=[not_ready, healthy_payload()])
        self.assertEqual(clock.sleeps, [2.0])
        self.assertEqual(runtime.inspect_calls, 2)
        self.assertEqual(clock.health_calls, 2)  # type: ignore[attr-defined]

    def test_healthy_docker_waits_for_scheduler_workers(self) -> None:
        not_ready = healthy_payload()
        scheduler = not_ready["acquisition"]["scheduler"]  # type: ignore[index]
        scheduler["workers_healthy"] = False  # type: ignore[index]
        runtime = FakeRuntime(health_statuses=["healthy", "healthy"])
        clock = self.run_gate(runtime, payloads=[not_ready, healthy_payload()])
        self.assertEqual(clock.sleeps, [2.0])
        self.assertEqual(runtime.inspect_calls, 2)
        self.assertEqual(clock.health_calls, 2)  # type: ignore[attr-defined]

    def test_permanent_starting_times_out(self) -> None:
        runtime = FakeRuntime(health_statuses=["starting"])
        with self.assertRaisesRegex(MODULE.HealthGateError, "before deadline"):
            self.run_gate(runtime, timeout=4.0, poll=2.0)

    def test_unhealthy_fails_closed(self) -> None:
        runtime = FakeRuntime(health_statuses=["unhealthy"])
        with self.assertRaisesRegex(MODULE.HealthGateError, "Docker health is unhealthy"):
            self.run_gate(runtime)

    def test_missing_or_multiple_running_containers_fail_closed(self) -> None:
        for container_ids in ([], ["container-a", "container-b"]):
            with self.subTest(container_ids=container_ids):
                runtime = FakeRuntime(container_ids=[container_ids])
                with self.assertRaisesRegex(MODULE.HealthGateError, "exactly one"):
                    self.run_gate(runtime)

    def test_exited_container_fails_closed(self) -> None:
        runtime = FakeRuntime(running=False)
        with self.assertRaisesRegex(MODULE.HealthGateError, "not running"):
            self.run_gate(runtime)

    def test_container_replacement_during_wait_fails_closed(self) -> None:
        runtime = FakeRuntime(
            container_ids=[["container-a"], ["container-b"]],
            health_statuses=["starting"],
        )
        with self.assertRaisesRegex(MODULE.HealthGateError, "container changed"):
            self.run_gate(runtime)

    def test_degraded_operational_status_fails_closed(self) -> None:
        payload = healthy_payload()
        payload["status"] = "degraded"
        with self.assertRaisesRegex(MODULE.HealthGateError, "expected 'ok'"):
            self.run_gate(FakeRuntime(), payload=payload)

    def test_mqtt_disconnected_fails_closed(self) -> None:
        payload = healthy_payload()
        payload["mqtt_connected"] = False
        with self.assertRaisesRegex(MODULE.HealthGateError, "MQTT is not connected"):
            self.run_gate(FakeRuntime(), payload=payload)

    def test_unhealthy_scheduler_workers_fail_closed(self) -> None:
        payload = healthy_payload()
        scheduler = payload["acquisition"]["scheduler"]  # type: ignore[index]
        scheduler["workers_healthy"] = False  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.HealthGateError, "workers are not healthy"):
            self.run_gate(FakeRuntime(), payload=payload)


    def test_missing_scheduler_evidence_fails_closed(self) -> None:
        payload = healthy_payload()
        payload["acquisition"] = {}
        with self.assertRaisesRegex(MODULE.HealthGateError, "missing scheduler evidence"):
            self.run_gate(FakeRuntime(), payload=payload, timeout=2.0, poll=1.0)

    def test_missing_or_invalid_worker_counts_fail_closed(self) -> None:
        cases = [
            ({"expected_bus_workers": 2}, "counts must be"),
            ({"expected_bus_workers": "2", "active_bus_workers": 2}, "counts must be"),
            ({"expected_bus_workers": True, "active_bus_workers": 1}, "counts must be"),
            ({"expected_bus_workers": -1, "active_bus_workers": -1}, "counts must be"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                payload = healthy_payload()
                scheduler = payload["acquisition"]["scheduler"]  # type: ignore[index]
                scheduler.clear()  # type: ignore[union-attr]
                scheduler.update({"workers_healthy": True, **overrides})  # type: ignore[union-attr]
                with self.assertRaisesRegex(MODULE.HealthGateError, message):
                    self.run_gate(FakeRuntime(), payload=payload, timeout=2.0, poll=1.0)

    def test_worker_count_mismatch_fails_closed(self) -> None:
        payload = healthy_payload()
        scheduler = payload["acquisition"]["scheduler"]  # type: ignore[index]
        scheduler["active_bus_workers"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(MODULE.HealthGateError, "do not match expected"):
            self.run_gate(FakeRuntime(), payload=payload)

    def test_deploy_script_preserves_gate_before_historical_checkout(self) -> None:
        script = DEPLOY.read_text(encoding="utf-8")
        stage = script.index('DEVICE_AGENT_HEALTH_GATE_HELPER="$AUDIT_DIR/')
        deployment_checkout_log = script.index(
            'log "Switching temporarily to approved historical main source', stage
        )
        checkout = script.index('git switch --detach "$TARGET_HEAD"', deployment_checkout_log)
        invoke = script.index('python3 "$DEVICE_AGENT_HEALTH_GATE_HELPER"', checkout)
        image = script.index("DEPLOYED_DEVICE_AGENT_IMAGE_ID=", invoke)
        self.assertLess(stage, checkout)
        self.assertLess(checkout, invoke)
        self.assertLess(invoke, image)
        self.assertIn(
            'install -m 0500 "$SCRIPT_DIR/device-agent-deployment-health-gate.py"',
            script,
        )
        self.assertNotIn(
            'python3 "$SCRIPT_DIR/device-agent-deployment-health-gate.py"',
            script,
        )
        self.assertNotIn(
            "{{.State.Health.Status}}' \"$DEPLOYED_DEVICE_AGENT_CONTAINER\")\" == \"healthy\"",
            script,
        )


if __name__ == "__main__":
    unittest.main()
