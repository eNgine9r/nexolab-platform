from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from commissioning_activation import (
    CommissioningActivationJournal,
    activation_fingerprint,
    parse_activation_request,
)


def payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "activation_id": "activation-001",
        "action": "activate",
        "node_id": "edge-01",
        "bus_id": "rs485-main",
        "stable_transport_identifier": "/dev/serial/by-id/usb-controller",
        "unit_id": 125,
        "profile_id": "dixell-xjp60d",
        "profile_version": "dixell-xjp60d-fc03-v1",
    }
    value.update(overrides)
    return value


class CommissioningActivationContractTests(unittest.TestCase):
    def test_request_accepts_only_repository_owned_activation_identity(self) -> None:
        request = parse_activation_request(payload())
        self.assertEqual(request.unit_id, 125)
        self.assertEqual(request.profile_id, "dixell-xjp60d")

    def test_request_rejects_modbus_or_write_surface(self) -> None:
        for field, value in (
            ("function", 6),
            ("register", 1),
            ("write_value", 10),
            ("addresses", [1, 2]),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    parse_activation_request(payload(**{field: value}))

    def test_fingerprint_is_stable_across_activate_and_rollback(self) -> None:
        activate = parse_activation_request(payload(action="activate"))
        rollback = parse_activation_request(payload(action="rollback"))
        self.assertEqual(
            activation_fingerprint(activate),
            activation_fingerprint(rollback),
        )

    def test_journal_persists_recoverable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "edge.db"
            journal = CommissioningActivationJournal(path)
            journal.save(
                "activation-001",
                "fingerprint",
                "prepared",
                {"device_id": "xjp60d-125", "registry_revision_before": 4},
            )
            loaded = CommissioningActivationJournal(path).load("activation-001")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["state"], "prepared")
            self.assertEqual(loaded["device_id"], "xjp60d-125")
            self.assertEqual(loaded["registry_revision_before"], 4)

    def test_request_rejects_unstable_adapter_and_wrong_profile(self) -> None:
        with self.assertRaises(ValueError):
            parse_activation_request(
                payload(stable_transport_identifier="/dev/ttyUSB0")
            )
        with self.assertRaises(ValueError):
            parse_activation_request(payload(profile_version="unknown"))


if __name__ == "__main__":
    unittest.main()
