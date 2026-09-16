from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from commissioning_connections import (
    commissioning_bus_id,
    connection_inventory,
    inventory_stable_adapters,
    resolve_commissioning_adapter,
)


class CommissioningConnectionTests(unittest.TestCase):
    def _root(self, directory: str) -> Path:
        root = Path(directory) / "by-id"
        root.mkdir()
        for name, tty in (("usb-prod", "ttyUSB0"), ("usb-danfoss", "ttyUSB3")):
            target = Path(directory) / tty
            target.write_text("fixture", encoding="utf-8")
            (root / name).symlink_to(target)
        return root

    @staticmethod
    def _topology(prod_path: str):
        binding = SimpleNamespace(
            bus_id="rs485-main",
            serial_device=prod_path,
            baudrate=9600,
            parity="N",
            stopbits=1,
            timeout_seconds=0.3,
            retries=1,
        )
        return SimpleNamespace(bindings=(binding,))

    def test_inventory_is_passive_and_stable_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            adapters = inventory_stable_adapters(root)
            self.assertEqual([Path(item.stable_path).name for item in adapters], ["usb-danfoss", "usb-prod"])
            self.assertTrue(all(Path(item.real_path).name.startswith("ttyUSB") for item in adapters))

    def test_inventory_distinguishes_production_and_commissioning_connections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            prod = str(root / "usb-prod")
            payload = connection_inventory(node_id="edge-01", topology=self._topology(prod), serial_root=root)
            by_path = {item["stable_transport_identifier"]: item for item in payload["connections"]}
            self.assertEqual(by_path[prod]["ownership"], "production_bus")
            danfoss = str(root / "usb-danfoss")
            self.assertEqual(by_path[danfoss]["ownership"], "available_commissioning")
            self.assertEqual(by_path[danfoss]["bus_id"], commissioning_bus_id(danfoss))
            self.assertIsNone(by_path[danfoss]["serial"])

    def test_resolver_never_aliases_a_production_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            prod = str(root / "usb-prod")
            topology = self._topology(prod)
            candidate = str(root / "usb-danfoss")
            resolved = resolve_commissioning_adapter(
                commissioning_bus_id(candidate), topology=topology, serial_root=root
            )
            self.assertEqual(resolved.stable_path, candidate)
            with self.assertRaisesRegex(ValueError, "production-owned"):
                resolve_commissioning_adapter(
                    commissioning_bus_id(prod), topology=topology, serial_root=root
                )

    def test_unowned_adapter_fails_closed_when_production_identity_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            missing_prod = str(root / "usb-production-missing")
            topology = self._topology(missing_prod)
            candidate = str(root / "usb-danfoss")
            payload = connection_inventory(node_id="edge-01", topology=topology, serial_root=root)
            by_path = {item["stable_transport_identifier"]: item for item in payload["connections"]}
            self.assertFalse(by_path[candidate]["available_for_preflight"])
            with self.assertRaisesRegex(ValueError, "ownership is ambiguous"):
                resolve_commissioning_adapter(
                    commissioning_bus_id(candidate), topology=topology, serial_root=root
                )


if __name__ == "__main__":
    unittest.main()
