"""Isolated HTTP-fixture tests; no physical hardware or production access."""

from __future__ import annotations

import contextlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest

MODULE = Path(__file__).resolve().parents[1] / "check-frontend-entrypoint-parity.py"
spec = importlib.util.spec_from_file_location("frontend_entrypoint_parity", MODULE)
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)
EXPECTED = "8ab3be4ab67b202e4df99c23d0cc4a81d8d0f3bc"


@contextlib.contextmanager
def serve(identity, status=200, redirect=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/runtime-identity":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(302 if redirect else status)
            self.send_header("Content-Type", "application/json")
            if redirect:
                self.send_header("Location", "https://example.invalid/login")
            self.end_headers()
            if not redirect:
                self.wfile.write(json.dumps(identity).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def identity(source=EXPECTED, build="build_approved"):
    return {"source_commit": source, "build_id": build, "identity_source": "offline_image_manifest"}


class ReadOnlyParityTests(unittest.TestCase):
    def test_matching_source_and_build_pass(self):
        with serve(identity()) as first, serve(identity()) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])

    def test_source_mismatch_fails(self):
        with serve(identity()) as first, serve(identity(source="a" * 40)) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("source differs" in fail for fail in result["failures"]))

    def test_different_build_same_source_fails(self):
        with serve(identity()) as first, serve(identity(build="otherbuild")) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("build IDs" in fail for fail in result["failures"]))

    def test_missing_identity_fails_closed(self):
        with serve({"source_commit": EXPECTED}) as first, serve(identity()) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["entries"][0]["identity"], "unavailable")

    def test_redirect_is_not_followed(self):
        with serve(identity(), redirect=True) as first, serve(identity()) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("HTTP 302" in fail for fail in result["failures"]))

    def test_invalid_remote_and_metadata_origins_rejected(self):
        for origin in ("https://example.com", "http://8.8.8.8:80", "http://169.254.169.254:80",
                       "http://localhost:3000", "http://127.0.0.1:3000/?token=hello"):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError):
                    parity.parse_entrypoint("local=" + origin)

    def test_duplicate_names_and_fewer_than_two_rejected(self):
        with self.assertRaises(ValueError):
            parity.verify([("a", "http://127.0.0.1:3000")], EXPECTED)
        with self.assertRaises(ValueError):
            parity.verify([("a", "http://127.0.0.1:3000"), ("a", "http://127.0.0.1:3105")], EXPECTED)

    def test_500_response_fails(self):
        with serve(identity(), status=500) as first, serve(identity()) as second:
            result = parity.verify([("local", first), ("funnel", second)], EXPECTED)
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
