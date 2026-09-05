from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "commission_rs485_bus.py"
SPEC = importlib.util.spec_from_file_location("commission_rs485_bus", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CommissionRS485BusTests(unittest.TestCase):
    def adapter(self, path: str, real_path: str = "/dev/ttyUSB9"):
        return MODULE.AdapterEvidence(
            stable_path=path,
            real_path=real_path,
            symlink_target="../../ttyUSB9",
            udev={"ID_VENDOR_ID": "10c4"},
        )

    def test_inventory_resolves_stable_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "by-id"
            target = Path(directory) / "ttyUSB9"
            root.mkdir()
            target.write_text("device", encoding="utf-8")
            (root / "usb-test-if00-port0").symlink_to(target)

            with patch.object(MODULE, "_read_udev", return_value={}):
                adapters = MODULE.inventory_adapters(root)

            self.assertEqual(len(adapters), 1)
            self.assertEqual(adapters[0].real_path, str(target))
            self.assertEqual(adapters[0].stable_path, str(root / "usb-test-if00-port0"))

    def test_runtime_health_maps_container_paths_to_host_paths(self) -> None:
        payload = {
            "status": "ok",
            "acquisition": {
                "rs485_buses": [
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                    {"serial_device": "/host/dev/serial/by-id/bus-b"},
                ]
            }
        }
        self.assertEqual(
            MODULE.parse_runtime_protected_ports(payload),
            ("/dev/serial/by-id/bus-a", "/dev/serial/by-id/bus-b"),
        )

    def test_runtime_health_requires_reported_bus_paths(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"status": "ok", "acquisition": {}}), stderr=""
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ):
            with self.assertRaisesRegex(RuntimeError, "ownership is incomplete"):
                MODULE.runtime_protected_ports()

    def test_runtime_health_rejects_partial_bus_ownership(self) -> None:
        payload = {
            "status": "ok",
            "acquisition": {
                "rs485_buses": [
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                    {"bus_id": "rs485-b"},
                ]
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ):
            with self.assertRaisesRegex(RuntimeError, "ownership is incomplete"):
                MODULE.runtime_protected_ports()

    def test_runtime_health_rejects_non_ok_device_agent(self) -> None:
        payload = {
            "status": "error",
            "acquisition": {
                "rs485_buses": [
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                ]
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ):
            with self.assertRaisesRegex(RuntimeError, "health is not ok"):
                MODULE.runtime_protected_ports()

    def test_runtime_health_rejects_duplicate_production_paths(self) -> None:
        payload = {
            "status": "ok",
            "acquisition": {
                "rs485_buses": [
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                ]
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ):
            with self.assertRaisesRegex(RuntimeError, "ownership is incomplete"):
                MODULE.runtime_protected_ports()

    def test_runtime_health_returns_all_production_ports(self) -> None:
        payload = {
            "status": "ok",
            "acquisition": {
                "rs485_buses": [
                    {"serial_device": "/host/dev/serial/by-id/bus-a"},
                    {"serial_device": "/host/dev/serial/by-id/bus-b"},
                ]
            }
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with patch.object(MODULE.shutil, "which", return_value="/usr/bin/docker"), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ):
            self.assertEqual(
                MODULE.runtime_protected_ports(),
                ("/dev/serial/by-id/bus-a", "/dev/serial/by-id/bus-b"),
            )

    def test_selects_only_adapter_outside_all_production_ports(self) -> None:
        bus_a = self.adapter("/dev/serial/by-id/bus-a", "/dev/ttyUSB0")
        bus_b = self.adapter("/dev/serial/by-id/bus-b", "/dev/ttyUSB1")
        candidate = self.adapter("/dev/serial/by-id/new", "/dev/ttyUSB2")
        selected = MODULE.select_new_adapter(
            (bus_a, bus_b, candidate),
            protected_ports=(bus_a.stable_path, bus_b.stable_path),
            requested_port=None,
        )
        self.assertEqual(selected, candidate)

    def test_refuses_either_current_production_adapter(self) -> None:
        bus_a = self.adapter("/dev/serial/by-id/bus-a")
        bus_b = self.adapter("/dev/serial/by-id/bus-b")
        for requested in (bus_a.stable_path, bus_b.stable_path):
            with self.subTest(requested=requested), self.assertRaisesRegex(
                ValueError, "current production"
            ):
                MODULE.select_new_adapter(
                    (bus_a, bus_b),
                    protected_ports=(bus_a.stable_path, bus_b.stable_path),
                    requested_port=requested,
                )

    def test_missing_production_adapter_fails_closed(self) -> None:
        candidate = self.adapter("/dev/serial/by-id/new")
        with self.assertRaisesRegex(ValueError, "not currently enumerated"):
            MODULE.select_new_adapter(
                (candidate,),
                protected_ports=("/dev/serial/by-id/production",),
                requested_port=candidate.stable_path,
            )

    def test_no_unprotected_adapter_fails_closed(self) -> None:
        bus_a = self.adapter("/dev/serial/by-id/bus-a")
        bus_b = self.adapter("/dev/serial/by-id/bus-b")
        with self.assertRaisesRegex(ValueError, "one unprotected adapter"):
            MODULE.select_new_adapter(
                (bus_a, bus_b),
                protected_ports=(bus_a.stable_path, bus_b.stable_path),
                requested_port=None,
            )

    def test_main_refuses_scan_when_runtime_ownership_is_unavailable(self) -> None:
        candidate = self.adapter("/dev/serial/by-id/new")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            MODULE, "inventory_adapters", return_value=(candidate,)
        ), patch.object(
            MODULE, "runtime_protected_ports", side_effect=RuntimeError("ownership unavailable")
        ), patch.object(
            MODULE, "busy_pids"
        ) as busy, patch.object(
            sys,
            "argv",
            [
                "commission_rs485_bus.py",
                "--scan",
                "--adapter",
                candidate.stable_path,
                "--output-root",
                directory,
            ],
        ):
            self.assertEqual(MODULE.main(), 2)
            busy.assert_not_called()

    def test_main_refuses_runtime_production_adapter_before_busy_probe(self) -> None:
        bus_a = self.adapter("/dev/serial/by-id/bus-a", "/dev/ttyUSB0")
        bus_b = self.adapter("/dev/serial/by-id/bus-b", "/dev/ttyUSB1")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            MODULE, "inventory_adapters", return_value=(bus_a, bus_b)
        ), patch.object(
            MODULE,
            "runtime_protected_ports",
            return_value=(bus_a.stable_path, bus_b.stable_path),
        ), patch.object(MODULE, "busy_pids") as busy, patch.object(
            sys,
            "argv",
            [
                "commission_rs485_bus.py",
                "--scan",
                "--adapter",
                bus_b.stable_path,
                "--output-root",
                directory,
            ],
        ):
            self.assertEqual(MODULE.main(), 2)
            busy.assert_not_called()

    def test_scan_command_uses_repository_read_only_scanner(self) -> None:
        candidate = self.adapter("/dev/serial/by-id/new")
        command = MODULE.build_scan_command(
            candidate,
            output=Path("evidence/discovery.json"),
            unit_ids="1-32",
            full=False,
        )
        self.assertIn("scan_rs485.py", command[1])
        self.assertIn("--quick", command)
        self.assertIn("--deep", command)
        self.assertEqual(command[command.index("--port") + 1], candidate.stable_path)
        self.assertNotIn("--write", command)

    def test_full_scan_omits_quick_profile_flag(self) -> None:
        command = MODULE.build_scan_command(
            self.adapter("/dev/serial/by-id/new"),
            output=Path("evidence/discovery.json"),
            unit_ids="1-247",
            full=True,
        )
        self.assertNotIn("--quick", command)
        self.assertIn("--deep", command)


if __name__ == "__main__":
    unittest.main()
