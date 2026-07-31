from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from managed_main import (
    XJP60DDiscoveryScanner,
    XJP60DPointStore,
    canonical_point,
    parse_control_points,
)
from modbus_rtu import ModbusTimeoutError
from xjp60d import XJP60DReading


class FakeReader:
    def __init__(self) -> None:
        self.requests: list[tuple[int, int]] = []

    def read_channel(self, unit_id: int, channel: int) -> XJP60DReading:
        self.requests.append((unit_id, channel))
        if unit_id == 101:
            raise ModbusTimeoutError("controller unavailable")
        quality = "valid" if channel in {3, 4} else "sensor_error"
        return XJP60DReading(
            unit_id=unit_id,
            channel=channel,
            raw_value=45 if quality == "valid" else 0,
            raw_status=0x1100 if quality == "valid" else 0x1103,
            value=4.5 if quality == "valid" else None,
            unit="degC",
            quality=quality,
            alarm=None,
        )


class ManagedMainTests(unittest.TestCase):
    def test_parses_channel_ids_and_point_objects(self) -> None:
        self.assertEqual(
            parse_control_points(["106-03", {"unit_id": 126, "channel": 4}]),
            ((106, 3), (126, 4)),
        )
        self.assertEqual(canonical_point(126, 4), "126-04")

    def test_point_store_initializes_and_persists_operator_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "edge.db"
            store = XJP60DPointStore(database)

            self.assertEqual(
                store.load_or_initialize(((106, 3), (106, 4))),
                ((106, 3), (106, 4)),
            )
            store.replace_points(((106, 4), (126, 4)))

            reloaded = XJP60DPointStore(database)
            self.assertEqual(
                reloaded.load_or_initialize(((101, 1),)),
                ((106, 4), (126, 4)),
            )

    def test_discovery_skips_absent_controller_after_first_failure(self) -> None:
        reader = FakeReader()

        result = XJP60DDiscoveryScanner(reader, (101, 106)).scan()

        self.assertEqual(reader.requests[0], (101, 1))
        self.assertNotIn((101, 2), reader.requests)
        self.assertEqual(
            [item["channel_id"] for item in result["available_points"]],
            ["106-03", "106-04"],
        )
        self.assertEqual(result["reachable_controller_count"], 1)
        self.assertEqual(result["controller_errors"][0]["unit_id"], 101)


if __name__ == "__main__":
    unittest.main()
