from __future__ import annotations

import threading
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, call, patch

from commissioning_preflight import PROFILES, PreflightBus, PreflightExecutionError, PreflightObservation
from commissioning_search import SearchRequest, parse_search_request, run_search
from dual_bus_main import DualBusAdaptiveRegistryDeviceAgent

BUS = "commissioning-1234567890abcdef"
PATH = "/dev/serial/by-id/usb-test"


def payload(**kwargs: object) -> dict[str, object]:
    value: dict[str, object] = {
        "node_id": "edge-01",
        "bus_id": BUS,
        "stable_transport_identifier": PATH,
        "profile_id": "dixell-xjp60d",
        "profile_version": "dixell-xjp60d-fc03-v1",
        "first_unit_id": 1,
        "last_unit_id": 3,
        "deadline_seconds": 30,
        "isolated_bus_confirmed": True,
    }
    value.update(kwargs)
    return value


class FakeRuntime:
    node_id = "edge-01"

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.failures: dict[int, str] = {}
        self.connections: list[dict[str, object]] = [
            {
                "bus_id": "rs485-main",
                "stable_transport_identifier": "/dev/serial/by-id/usb-production",
                "ownership": "production_bus",
                "present": True,
                "available_for_preflight": True,
                "available_for_isolated_search": False,
            },
            {
                "bus_id": BUS,
                "stable_transport_identifier": PATH,
                "ownership": "available_commissioning",
                "present": True,
                "available_for_preflight": True,
                "available_for_isolated_search": True,
            },
        ]

    def commissioning_connections(self) -> dict[str, object]:
        return {"schema_version": 1, "node_id": self.node_id, "connections": self.connections}

    def search_bus(self, bus_id: str) -> PreflightBus:
        return PreflightBus(bus_id, "/host/dev/serial/by-id/usb-test", True)

    def preflight_read_profile(
        self,
        profile: object,
        *,
        bus_id: str,
        unit_id: int,
        deadline_monotonic: float,
        commissioning_only: bool,
    ) -> tuple[PreflightObservation, ...]:
        if not commissioning_only:
            raise AssertionError("search must require unowned commissioning transport")
        del profile, bus_id, deadline_monotonic
        self.calls.append(unit_id)
        if unit_id in self.failures:
            raise PreflightExecutionError(self.failures[unit_id], "sanitized")
        return (PreflightObservation("channel-01", "sensor_error", None),)


class SearchContractTests(unittest.TestCase):
    def test_strict_input_and_isolation_are_mandatory_even_when_constructed_directly(self) -> None:
        bad = [
            {"first_unit_id": 0},
            {"last_unit_id": 248},
            {"first_unit_id": True},
            {"bus_id": "rs485-main"},
            {"isolated_bus_confirmed": False},
            {"deadline_seconds": float("nan")},
            {"deadline_seconds": 601},
            {"profile_id": "other"},
            {"register": 5},
            {"stable_transport_identifier": "/dev/ttyUSB0"},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_search_request(payload(**change))
        with self.assertRaises(ValueError):
            SearchRequest("edge-01", BUS, PATH, 1, 3, 30, False)

    def test_sequential_reads_distinguish_timeout_and_exception_from_candidate(self) -> None:
        runtime = FakeRuntime()
        runtime.failures = {1: "timeout", 2: "profile_mismatch"}
        progress = []
        result = run_search(
            parse_search_request(payload()), runtime, cancelled=threading.Event(), progress=progress.append
        )
        self.assertEqual(runtime.calls, [1, 2, 3])
        self.assertEqual(result.state, "completed")
        self.assertEqual(result.attempted, 3)
        self.assertEqual(result.candidates, (3,))
        self.assertEqual(result.exception_addresses, (2,))
        self.assertEqual([item.attempted for item in progress], [1, 2, 3])

    def test_missing_protected_adapter_or_duplicate_identity_prevents_reads(self) -> None:
        for variant in ("missing", "no_production", "duplicate", "alias", "unavailable", "production"):
            runtime = FakeRuntime()
            if variant == "missing":
                runtime.connections[0]["present"] = False
                runtime.connections[1]["available_for_isolated_search"] = False
            elif variant == "no_production":
                runtime.connections.pop(0)
                runtime.connections[0]["available_for_isolated_search"] = False
            elif variant == "duplicate":
                runtime.connections.append(dict(runtime.connections[1]))
            elif variant == "alias":
                alias = dict(runtime.connections[1])
                alias["bus_id"] = "commissioning-0000000000000000"
                alias["stable_transport_identifier"] = "/host" + PATH
                runtime.connections.append(alias)
            elif variant == "unavailable":
                runtime.connections[1]["available_for_preflight"] = False
                runtime.connections[1]["available_for_isolated_search"] = False
            else:
                runtime.connections[1]["ownership"] = "production_bus"
            result = run_search(parse_search_request(payload()), runtime, cancelled=threading.Event())
            self.assertEqual(result.state, "failed", variant)
            self.assertEqual(runtime.calls, [], variant)

    def test_identity_change_stops_before_recording_a_result(self) -> None:
        runtime = FakeRuntime()
        original = runtime.preflight_read_profile

        def read(*args: object, **kwargs: object) -> tuple[PreflightObservation, ...]:
            result = original(*args, **kwargs)  # type: ignore[arg-type]
            runtime.connections[1]["stable_transport_identifier"] = "/dev/serial/by-id/usb-other"
            return result

        runtime.preflight_read_profile = read  # type: ignore[method-assign]
        result = run_search(parse_search_request(payload()), runtime, cancelled=threading.Event())
        self.assertEqual(result.state, "failed")
        self.assertEqual(result.candidates, ())
        self.assertEqual(runtime.calls, [1])

    def test_explicit_isolated_search_capability_allows_absent_historical_adapter(self) -> None:
        runtime = FakeRuntime()
        runtime.connections[0]["present"] = False
        runtime.connections[1]["available_for_preflight"] = False
        result = run_search(parse_search_request(payload(first_unit_id=1, last_unit_id=1)), runtime, cancelled=threading.Event())
        self.assertEqual(result.state, "completed")

    def test_adapter_loss_during_last_timeout_does_not_look_like_a_complete_scan(self) -> None:
        runtime = FakeRuntime()

        def read(*args: object, **kwargs: object) -> tuple[PreflightObservation, ...]:
            del args, kwargs
            runtime.connections[1]["present"] = False
            raise PreflightExecutionError("timeout", "no response")

        runtime.preflight_read_profile = read  # type: ignore[method-assign]
        result = run_search(
            parse_search_request(payload(first_unit_id=1, last_unit_id=1)),
            runtime,
            cancelled=threading.Event(),
        )
        self.assertEqual((result.state, result.error_code), ("failed", "adapter_unavailable"))

    def test_cancel_deadline_and_malformed_response_are_bounded(self) -> None:
        event = threading.Event()
        event.set()
        runtime = FakeRuntime()
        result = run_search(parse_search_request(payload()), runtime, cancelled=event)
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(runtime.calls, [])
        runtime.failures[1] = "malformed_response"
        result = run_search(parse_search_request(payload()), runtime, cancelled=threading.Event())
        self.assertEqual((result.state, result.error_code), ("failed", "malformed_response"))
        self.assertEqual(runtime.calls, [1])
        times = iter([0.0, 31.0])
        result = run_search(
            parse_search_request(payload()),
            FakeRuntime(),
            cancelled=threading.Event(),
            monotonic=lambda: next(times),
        )
        self.assertEqual(result.state, "timed_out")

    def test_inflight_cancel_and_late_reply_preserve_only_prior_results(self) -> None:
        event = threading.Event()
        runtime = FakeRuntime()
        result = run_search(
            parse_search_request(payload()), runtime, cancelled=event, progress=lambda _: event.set()
        )
        self.assertEqual(result.state, "cancelled")
        self.assertEqual(result.candidates, (1,))
        self.assertEqual(runtime.calls, [1])

        times = iter([0.0, 0.1, 0.2, 4.0])
        result = run_search(
            parse_search_request(payload(first_unit_id=1, last_unit_id=1)),
            FakeRuntime(),
            cancelled=threading.Event(),
            monotonic=lambda: next(times),
        )
        self.assertEqual(
            (result.state, result.error_code, result.candidates), ("failed", "read_deadline_exceeded", ())
        )

    def test_concurrent_search_is_rejected(self) -> None:
        import commissioning_search

        self.assertTrue(commissioning_search._SCAN_GUARD.acquire(blocking=False))
        try:
            runtime = FakeRuntime()
            result = run_search(parse_search_request(payload()), runtime, cancelled=threading.Event())
            self.assertEqual((result.state, result.error_code), ("failed", "search_busy"))
            self.assertEqual(runtime.calls, [])
        finally:
            commissioning_search._SCAN_GUARD.release()

    def test_unexpected_reader_failure_releases_search_guard(self) -> None:
        runtime = FakeRuntime()
        with patch.object(runtime, "preflight_read_profile", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                run_search(parse_search_request(payload()), runtime, cancelled=threading.Event())
        result = run_search(
            parse_search_request(payload(first_unit_id=1, last_unit_id=1)),
            FakeRuntime(),
            cancelled=threading.Event(),
        )
        self.assertEqual(result.state, "completed")

    def test_real_agent_path_reuses_exclusive_port_lock_and_fixed_fc03_registers(self) -> None:
        agent = object.__new__(DualBusAdaptiveRegistryDeviceAgent)
        agent.settings = Mock(
            node_id="edge-01", xjp60d_scale=0.1, embraco_temperature_scale=1, embraco_control_scale=1
        )
        topology = Mock(explicit=True)
        topology.binding.side_effect = ValueError("unowned")
        agent.rs485_topology = topology
        agent._commissioning_adapter_locks = {}
        agent._commissioning_adapter_locks_guard = threading.Lock()
        agent._logical_bus_observer = Mock(return_value=Mock())
        inventory = FakeRuntime().commissioning_connections()
        agent.commissioning_connections = Mock(return_value=inventory)
        client = Mock()
        client.instrumentation_scope.return_value = nullcontext()
        client.read_holding_register.side_effect = [215, 0]
        adapter = Mock(runtime_path="/host/dev/serial/by-id/usb-test")
        with patch("dual_bus_main.resolve_commissioning_adapter", return_value=adapter), patch(
            "dual_bus_main.ModbusRTUClient", return_value=client
        ) as factory:
            result = run_search(
                parse_search_request(payload(first_unit_id=7, last_unit_id=7)),
                agent,
                cancelled=threading.Event(),
            )
        self.assertEqual((result.state, result.candidates), ("completed", (7,)))
        self.assertEqual(client.read_holding_register.call_args_list, [call(7, 256), call(7, 257)])
        self.assertTrue(factory.call_args.kwargs["exclusive"])
        client.close.assert_called_once_with()
        client.write_single_register.assert_not_called()

    def test_real_agent_rejects_production_binding_even_if_name_looks_like_commissioning(self) -> None:
        agent = object.__new__(DualBusAdaptiveRegistryDeviceAgent)
        agent.rs485_topology = Mock(explicit=True)
        agent.rs485_topology.binding.return_value = Mock(bus_id=BUS)
        with self.assertRaises(PreflightExecutionError) as error:
            agent.preflight_read_profile(
                PROFILES["dixell-xjp60d"],
                bus_id=BUS,
                unit_id=1,
                deadline_monotonic=99999999,
                commissioning_only=True,
            )
        self.assertEqual(error.exception.code, "bus_unavailable")


if __name__ == "__main__":
    unittest.main()
