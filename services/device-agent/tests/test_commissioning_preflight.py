from __future__ import annotations

import unittest

from commissioning_preflight import (
    CommissioningPreflightRequest,
    PreflightBus,
    PreflightExecutionError,
    PreflightObservation,
    PreflightProfile,
    execute_preflight,
    parse_preflight_request,
)


class FakeRuntime:
    node_id = "edge-01"

    def __init__(self) -> None:
        self.bus = PreflightBus(
            bus_id="rs485-main",
            serial_device="/host/dev/serial/by-id/usb-test",
            path_present=True,
        )
        self.owner: str | None = None
        self.registry_identity: tuple[str, str] | None = None
        self.read_error: PreflightExecutionError | None = None
        self.read_calls: list[tuple[str, str, int]] = []

    def preflight_bus(self, bus_id: str) -> PreflightBus:
        if bus_id != self.bus.bus_id:
            raise ValueError(f"Unknown RS-485 bus_id: {bus_id}")
        return self.bus

    def preflight_unit_owner(self, unit_id: int) -> str | None:
        del unit_id
        return self.owner

    def preflight_registry_identity(self, bus_id: str, unit_id: int) -> tuple[str, str] | None:
        del bus_id, unit_id
        return self.registry_identity

    def preflight_read_profile(
        self,
        profile: PreflightProfile,
        *,
        bus_id: str,
        unit_id: int,
        deadline_monotonic: float,
    ) -> tuple[PreflightObservation, ...]:
        self.read_calls.append((profile.profile_id, bus_id, unit_id))
        self.assert_deadline = deadline_monotonic
        if self.read_error is not None:
            raise self.read_error
        return (PreflightObservation(key="control_state", quality="valid", semantic="cooling"),)


def request(**overrides: object) -> CommissioningPreflightRequest:
    payload: dict[str, object] = {
        "node_id": "edge-01",
        "bus_id": "rs485-main",
        "stable_transport_identifier": "/dev/serial/by-id/usb-test",
        "unit_id": 2,
        "profile_id": "embraco-sync",
        "profile_version": "embraco-sync-fc03-v1.00.04",
        "deadline_seconds": 5.0,
    }
    payload.update(overrides)
    return parse_preflight_request(payload)


class CommissioningPreflightContractTests(unittest.TestCase):
    def test_success_is_fc03_only_and_sanitized(self) -> None:
        runtime = FakeRuntime()
        result = execute_preflight(request(), runtime)

        self.assertEqual(result["result"], "passed")
        self.assertEqual(result["evidence_level"], "hardware_verified")
        self.assertEqual(result["function_codes"], [3])
        self.assertEqual(result["modbus_writes"], "none")
        self.assertEqual(result["hardware_writes"], "none")
        self.assertEqual(result["observations"], [{"key": "control_state", "quality": "valid", "semantic": "cooling"}])
        self.assertEqual(runtime.read_calls, [("embraco-sync", "rs485-main", 2)])
        self.assertNotIn("raw_value", str(result))

    def test_request_rejects_arbitrary_modbus_write_or_register_fields(self) -> None:
        base = {
            "node_id": "edge-01",
            "bus_id": "rs485-main",
            "stable_transport_identifier": "/dev/serial/by-id/usb-test",
            "unit_id": 2,
            "profile_id": "embraco-sync",
            "profile_version": "embraco-sync-fc03-v1.00.04",
            "deadline_seconds": 5,
        }
        for field, value in (
            ("function", 6),
            ("function_code", 16),
            ("address", 1),
            ("registers", [1, 2]),
            ("write_value", 20),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "unsupported preflight request fields"):
                    parse_preflight_request({**base, field: value})

    def test_missing_or_replaced_adapter_fails_before_read(self) -> None:
        runtime = FakeRuntime()
        runtime.bus = PreflightBus(runtime.bus.bus_id, runtime.bus.serial_device, False)
        missing = execute_preflight(request(), runtime)
        self.assertEqual((missing["result"], missing["code"]), ("failed", "adapter_unavailable"))
        self.assertEqual(runtime.read_calls, [])

        runtime = FakeRuntime()
        runtime.bus = PreflightBus("rs485-main", "/host/dev/serial/by-id/usb-other", True)
        replaced = execute_preflight(request(), runtime)
        self.assertEqual((replaced["result"], replaced["code"]), ("failed", "adapter_identity_mismatch"))
        self.assertEqual(runtime.read_calls, [])

    def test_bus_and_unit_conflicts_fail_closed(self) -> None:
        runtime = FakeRuntime()
        missing_bus = execute_preflight(request(bus_id="rs485-missing"), runtime)
        self.assertEqual(missing_bus["code"], "bus_unavailable")

        runtime = FakeRuntime()
        runtime.owner = "rs485-other"
        conflict = execute_preflight(request(), runtime)
        self.assertEqual(conflict["code"], "unit_id_conflict")
        self.assertEqual(runtime.read_calls, [])

        runtime = FakeRuntime()
        runtime.registry_identity = ("xjp60d", "dixell-xjp60d-fc03-v1")
        mismatch = execute_preflight(request(), runtime)
        self.assertEqual(mismatch["code"], "unit_id_conflict")
        self.assertEqual(runtime.read_calls, [])

    def test_profile_version_mismatch_and_unsupported_profiles_fail_closed(self) -> None:
        mismatch = execute_preflight(request(profile_version="wrong"), FakeRuntime())
        self.assertEqual(mismatch["code"], "profile_mismatch")

        unsupported = execute_preflight(
            request(profile_id="unknown", profile_version="unknown-v1"),
            FakeRuntime(),
        )
        self.assertEqual(unsupported["code"], "unsupported_profile")
        self.assertEqual(unsupported["evidence_level"], "unsupported")

    def test_timeout_and_malformed_response_are_persistable_failures(self) -> None:
        runtime = FakeRuntime()
        runtime.read_error = PreflightExecutionError("timeout", "Bounded FC03 preflight timed out")
        timed_out = execute_preflight(request(), runtime)
        self.assertEqual(timed_out["code"], "timeout")
        self.assertEqual(timed_out["modbus_writes"], "none")

        runtime = FakeRuntime()
        runtime.read_error = PreflightExecutionError("malformed_response", "Malformed FC03 response")
        malformed = execute_preflight(request(), runtime)
        self.assertEqual(malformed["code"], "malformed_response")
        self.assertEqual(malformed["hardware_writes"], "none")

    def test_node_identity_and_stable_path_are_exact(self) -> None:
        node = execute_preflight(request(node_id="edge-02"), FakeRuntime())
        self.assertEqual(node["code"], "node_identity_mismatch")
        with self.assertRaisesRegex(ValueError, "/dev/serial/by-id"):
            parse_preflight_request(
                {
                    "node_id": "edge-01",
                    "bus_id": "rs485-main",
                    "stable_transport_identifier": "/dev/ttyUSB0",
                    "unit_id": 2,
                    "profile_id": "embraco-sync",
                    "profile_version": "embraco-sync-fc03-v1.00.04",
                    "deadline_seconds": 5,
                }
            )


if __name__ == "__main__":
    unittest.main()
