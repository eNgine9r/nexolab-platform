from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "probe_akcc25.py"
SPEC = importlib.util.spec_from_file_location("probe_akcc25", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
SCAN = sys.modules["scan_rs485"]
COMMISSION = sys.modules["commission_rs485_bus"]


class FakePort:
    def __init__(self, values: dict[int, int]) -> None:
        self.values = values
        self.buffer = bytearray()
        self.requests: list[bytes] = []

    def reset_input_buffer(self) -> None:
        self.buffer.clear()

    def reset_output_buffer(self) -> None:
        pass

    def write(self, request: bytes) -> int:
        self.requests.append(request)
        unit_id = request[0]
        function = request[1]
        address = int.from_bytes(request[2:4], "big")
        raw = self.values[address]
        payload = bytes((unit_id, function, 2, (raw >> 8) & 0xFF, raw & 0xFF))
        self.buffer[:] = SCAN.add_crc(payload)
        return len(request)

    def flush(self) -> None:
        pass

    @property
    def in_waiting(self) -> int:
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result


class AKCC25ProbeTests(unittest.TestCase):
    def test_probe_reads_only_fixed_fc03_subset_and_records_raw_frames(self) -> None:
        port = FakePort({2007: 0, 2510: 1, 2685: 73, 2511: 1, 2512: 0, 2682: 100, 2541: 0, 2008: 35, 2251: 1, 2255: 1})
        observations = MODULE.probe_port(port, unit_id=35, timeout=0.1)

        self.assertEqual(
            [item["address"] for item in observations],
            [2007, 2510, 2685, 2511, 2512, 2682, 2541, 2008, 2251, 2255],
        )
        self.assertTrue(all(item["function_code"] == 3 for item in observations))
        self.assertEqual([item["documented_access"] for item in observations][-3:], ["RW", "RW", "RW"])
        self.assertTrue(all(item["status"] == "ok" for item in observations))
        self.assertTrue(all(item["request_hex"] and item["response_hex"] for item in observations))
        self.assertTrue(all(request[1] == 3 for request in port.requests))
        self.assertEqual([item["semantic"] for item in observations], ["normal_control", "on", None, "on", "off", None, "off", None, "auto", "even"])

    def test_probe_rejects_current_production_adapter(self) -> None:
        production = COMMISSION.AdapterEvidence(
            stable_path="/dev/serial/by-id/prod",
            real_path="/dev/ttyUSB0",
            symlink_target="../../ttyUSB0",
            udev={},
        )
        with patch.object(MODULE, "runtime_protected_ports", return_value=(production.stable_path,)), patch.object(
            MODULE, "inventory_adapters", return_value=(production,)
        ), patch.object(MODULE, "busy_pids") as busy:
            with self.assertRaisesRegex(ValueError, "current production"):
                MODULE.resolve_isolated_adapter(
                    adapter_path=production.stable_path,
                    container="device-agent",
                    additional_protected=(),
                )
        busy.assert_not_called()

    def test_probe_accepts_one_unprotected_idle_adapter(self) -> None:
        production = COMMISSION.AdapterEvidence(
            stable_path="/dev/serial/by-id/prod",
            real_path="/dev/ttyUSB0",
            symlink_target="../../ttyUSB0",
            udev={},
        )
        candidate = COMMISSION.AdapterEvidence(
            stable_path="/dev/serial/by-id/new",
            real_path="/dev/ttyUSB2",
            symlink_target="../../ttyUSB2",
            udev={},
        )
        with patch.object(MODULE, "runtime_protected_ports", return_value=(production.stable_path,)), patch.object(
            MODULE, "inventory_adapters", return_value=(production, candidate)
        ), patch.object(MODULE, "busy_pids", return_value=()):
            selected, protected = MODULE.resolve_isolated_adapter(
                adapter_path=candidate.stable_path,
                container="device-agent",
                additional_protected=(),
            )
        self.assertEqual(selected, candidate)
        self.assertEqual(protected, (production.stable_path,))

    def test_argument_validation_requires_stable_port_and_bounded_timeout(self) -> None:
        base = argparse.Namespace(adapter="/dev/serial/by-id/new", unit_id=35, timeout=0.3)
        MODULE.validate_args(base)
        with self.assertRaisesRegex(ValueError, "stable"):
            MODULE.validate_args(argparse.Namespace(adapter="/dev/ttyUSB2", unit_id=35, timeout=0.3))
        with self.assertRaisesRegex(ValueError, "timeout"):
            MODULE.validate_args(argparse.Namespace(adapter=base.adapter, unit_id=35, timeout=3.0))
        with self.assertRaisesRegex(ValueError, "unit-id"):
            MODULE.validate_args(argparse.Namespace(adapter=base.adapter, unit_id=0, timeout=0.3))


if __name__ == "__main__":
    unittest.main()
