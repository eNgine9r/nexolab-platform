"""Safety tests for the intentionally unconnected Quick Tunnel preview fixture."""
from __future__ import annotations

import importlib.util
import pathlib
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "inspection" / "nexolab_quick_tunnel_preview.py"
SPEC = importlib.util.spec_from_file_location("quick_tunnel_preview", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PreviewSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.PreviewHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_loopback_only(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_preview_is_explicitly_not_live_nexolab(self) -> None:
        status, headers, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store, private")
        self.assertIn(b"ISOLATED PREVIEW", data)
        self.assertIn(b"NO REAL DEVICES", data)
        self.assertNotIn(b"172.18.48.66", data)
        self.assertNotIn(b":8082", data)

    def test_health_not_telemetry(self) -> None:
        status, _, data = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"preview-only\n")

    def test_no_write_routes(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                status, _, _ = self.request(method, "/api/v1/controller/setpoint")
                self.assertEqual(status, 405)

    def test_unknown_api_rejected(self) -> None:
        status, _, _ = self.request("GET", "/api/v1/telemetry/latest")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
