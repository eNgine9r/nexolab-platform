from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from commissioning_buses import CommissionedBus, CommissionedBusStore, validate_bus
from commissioning_connections import commissioning_bus_id


def bus(name: str = "usb-a") -> CommissionedBus:
    path = "/dev/serial/by-id/" + name
    return CommissionedBus(commissioning_bus_id(path), path, 9600, "N", 1, 0.3, 1)


class CommissionedBusStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "edge.db"
        self.store = CommissionedBusStore(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_prepare_is_non_pollable_and_survives_restart(self) -> None:
        item = bus()
        self.assertEqual(self.store.prepare(item, activation_id="act-1", protected_paths=set()), "prepared")
        self.assertEqual(self.store.prepare(item, activation_id="act-1", protected_paths=set()), "prepared")
        self.assertEqual(self.store.active_buses(), ())
        self.store.close()
        self.store = CommissionedBusStore(self.path)
        self.assertEqual(self.store.active_buses(), ())
        with self.assertRaises(ValueError):
            self.store.prepare(item, activation_id="act-2", protected_paths=set())
        self.store.activate(item, activation_id="act-1")
        self.assertEqual(self.store.active_buses(), (item,))
        self.store.close()
        self.store = CommissionedBusStore(self.path)
        self.assertEqual(self.store.active_buses(), (item,))
        self.assertEqual(self.store.prepare(item, activation_id="another-device", protected_paths=set()), "active")

    def test_identity_profile_and_protected_bus_collisions_fail_closed(self) -> None:
        item = bus()
        with self.assertRaises(ValueError):
            self.store.prepare(item, activation_id="a", protected_paths={"/host" + item.stable_path})
        self.store.prepare(item, activation_id="a", protected_paths=set())
        with self.assertRaises(ValueError):
            self.store.prepare(replace(item, parity="E"), activation_id="a", protected_paths=set())
        with self.assertRaises(ValueError):
            self.store.activate(item, activation_id="wrong")
        self.assertEqual(self.store.active_buses(), ())
        self.store.activate(item, activation_id="a")
        self.assertFalse(self.store.cancel_prepared(item.bus_id, activation_id="a"))
        self.assertEqual(self.store.active_buses(), (item,))

    def test_cancel_only_own_prepared_and_keep_other_buses(self) -> None:
        one, two = bus(), bus("usb-b")
        self.store.prepare(one, activation_id="one", protected_paths=set())
        self.store.prepare(two, activation_id="two", protected_paths=set())
        self.assertFalse(self.store.cancel_prepared(one.bus_id, activation_id="two"))
        self.assertTrue(self.store.cancel_prepared(one.bus_id, activation_id="one"))
        self.store.activate(two, activation_id="two")
        self.assertEqual(self.store.active_buses(), (two,))

    def test_invalid_or_repointed_identity_never_enters_authority(self) -> None:
        item = bus()
        for invalid in (
            replace(item, bus_id="rs485-main"), replace(item, stable_path="/dev/ttyUSB0"),
            replace(item, stopbits=True), replace(item, timeout_seconds=float("nan")),
            replace(item, retries=999),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_bus(invalid)
        self.assertEqual(self.store.active_buses(), ())

    def test_competing_activations_never_both_own_prepared_bus(self) -> None:
        item = bus()
        other = CommissionedBusStore(self.path)
        self.addCleanup(other.close)
        def prepare(store: CommissionedBusStore, owner: str) -> str:
            try:
                return store.prepare(item, activation_id=owner, protected_paths=set())
            except ValueError:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as executor:
            one = executor.submit(prepare, self.store, "one")
            two = executor.submit(prepare, other, "two")
        self.assertCountEqual([one.result(), two.result()], ["prepared", "conflict"])
        self.assertEqual(self.store.active_buses(), ())


if __name__ == "__main__":
    unittest.main()
