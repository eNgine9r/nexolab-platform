from __future__ import annotations

import importlib.util
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
            self.assertEqual(
                adapters[0].stable_path,
                str(root / "usb-test-if00-port0"),
            )

    def test_selects_only_adapter_not_used_by_bus1(self) -> None:
        existing = self.adapter("/dev/serial/by-id/existing", "/dev/ttyUSB0")
        candidate = self.adapter("/dev/serial/by-id/new", "/dev/ttyUSB1")

        selected = MODULE.select_new_adapter(
            (existing, candidate),
            existing_port=existing.stable_path,
            requested_port=None,
        )

        self.assertEqual(selected, candidate)
    def test_ambiguous_new_adapter_requires_explicit_selection(self) -> None:
        adapters = (
            self.adapter("/dev/serial/by-id/a"),
            self.adapter("/dev/serial/by-id/b"),
        )

        with self.assertRaisesRegex(ValueError, "unambiguously"):
            MODULE.select_new_adapter(
                adapters,
                existing_port=None,
                requested_port=None,
            )

    def test_refuses_existing_production_adapter(self) -> None:
        existing = self.adapter("/dev/serial/by-id/existing")

        with self.assertRaisesRegex(ValueError, "existing production"):
            MODULE.select_new_adapter(
                (existing,),
                existing_port=existing.stable_path,
                requested_port=existing.stable_path,
            )

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
