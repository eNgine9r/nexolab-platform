import unittest
from unittest.mock import Mock

from dual_bus_main import DualBusAdaptiveRegistryHealthHandler
from test_commissioning_search import FakeRuntime, payload


class AddressSearchHandlerTests(unittest.TestCase):
    def handler(self, body):
        handler = object.__new__(DualBusAdaptiveRegistryHealthHandler)
        handler.path = "/api/v1/commissioning/address-search"
        handler.agent = FakeRuntime()
        handler._read_json_body = Mock(return_value=body)
        handler._send_json = Mock()
        return handler

    def test_one_address_is_echoed_with_read_only_candidate(self):
        handler = self.handler(payload(first_unit_id=7, last_unit_id=7, deadline_seconds=2.0))
        handler.do_POST()
        code, body = handler._send_json.call_args.args
        self.assertEqual(code, 200)
        self.assertEqual(body["unit_id"], 7)
        self.assertEqual(body["candidates"], (7,))
        self.assertEqual(body["modbus_writes"], "none")
        self.assertEqual(handler.agent.calls, [7])

    def test_range_and_long_deadline_rejected_before_read(self):
        for body in (
            payload(deadline_seconds=2.0),
            payload(first_unit_id=1, last_unit_id=1, deadline_seconds=30),
        ):
            with self.subTest(body=body):
                handler = self.handler(body)
                handler.do_POST()
                self.assertEqual(handler._send_json.call_args.args[0], 422)
                self.assertEqual(handler.agent.calls, [])
