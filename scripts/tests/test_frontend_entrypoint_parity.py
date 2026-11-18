"""Isolated HTTP-fixture tests; no physical hardware or production access."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import tempfile
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


    def test_explicit_pinned_build_map_allows_different_origin_bundles(self):
        with serve(identity(build="lan-built")) as lan, serve(identity(build="https-built")) as https:
            origins = [("lan", lan), ("funnel", https)]
            without_manifest = parity.verify(origins, EXPECTED)
            with_manifest = parity.verify(
                origins, EXPECTED, expected_builds={"lan": "lan-built", "funnel": "https-built"}
            )
        self.assertEqual(without_manifest["status"], "FAIL")
        self.assertEqual(with_manifest["status"], "PASS")
        self.assertEqual(with_manifest["build_policy"], "manifest_pinned")

    def test_pinned_map_rejects_a_build_not_in_approved_release(self):
        with serve(identity(build="lan-built")) as lan, serve(identity(build="rogue-build")) as https:
            result = parity.verify(
                [("lan", lan), ("funnel", https)], EXPECTED,
                expected_builds={"lan": "lan-built", "funnel": "https-built"},
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("frontend build differs" in error for error in result["failures"]))

    def test_build_manifest_digest_and_exact_source_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.json"
            data = {
                "schema_version": 1,
                "source_commit": EXPECTED,
                "entrypoint_builds": {"lan": "build-lan", "funnel": "build-https"},
            }
            raw = json.dumps(data).encode()
            p.write_bytes(raw)
            expected_digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(
                parity.load_build_manifest(p, expected_digest, EXPECTED, ["lan", "funnel"]),
                data["entrypoint_builds"],
            )
            with self.assertRaisesRegex(ValueError, "SHA256 differs"):
                parity.load_build_manifest(p, "0" * 64, EXPECTED, ["lan", "funnel"])
            with self.assertRaisesRegex(ValueError, "exactly"):
                parity.load_build_manifest(p, "invalid", EXPECTED, ["lan", "funnel"])
            with self.assertRaisesRegex(ValueError, "requested entrypoints"):
                parity.load_build_manifest(p, expected_digest, EXPECTED, ["lan", "funnel", "test"])

    def test_manifest_rejects_wrong_source_and_extra_unapproved_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.json"
            for data, message in (
                ({"schema_version": 1, "source_commit": "a" * 40,
                  "entrypoint_builds": {"lan": "x", "funnel": "x"}}, "approved source"),
                ({"schema_version": 1, "source_commit": EXPECTED,
                  "entrypoint_builds": {"lan": "x", "funnel": "x"}, "override": True},
                 "manifest fields"),
            ):
                with self.subTest(message=message):
                    raw = json.dumps(data).encode()
                    p.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, message):
                        parity.load_build_manifest(
                            p, hashlib.sha256(raw).hexdigest(), EXPECTED, ["lan", "funnel"]
                        )

    def test_manifest_rejects_oversized_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "manifest.json"
            for raw, message in ((b" " * 16385, "exceeds"), (b"not json", "invalid")):
                with self.subTest(message=message):
                    p.write_bytes(raw)
                    with self.assertRaisesRegex(ValueError, message):
                        parity.load_build_manifest(
                            p, hashlib.sha256(raw).hexdigest(), EXPECTED, ["lan", "funnel"]
                        )

    def test_cli_accepts_approved_origin_specific_build_manifest(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "builds.json"
            payload = {
                "schema_version": 1,
                "source_commit": EXPECTED,
                "entrypoint_builds": {"lan": "approved-lan", "funnel": "approved-https"},
            }
            raw = json.dumps(payload, sort_keys=True).encode()
            manifest.write_bytes(raw)
            with serve(identity(build="approved-lan")) as lan:
                with serve(identity(build="approved-https")) as https:
                    output = StringIO()
                    with redirect_stdout(output):
                        code = parity.main([
                            "--expected-source", EXPECTED,
                            "--entrypoint", "lan=" + lan,
                            "--entrypoint", "funnel=" + https,
                            "--build-manifest", str(manifest),
                            "--manifest-sha256", hashlib.sha256(raw).hexdigest(),
                        ])
                    self.assertEqual(code, 0)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["status"], "PASS")
                    self.assertEqual(result["build_policy"], "manifest_pinned")

    def test_cli_requires_manifest_and_digest_together(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with redirect_stdout(output):
            result = parity.main([
                "--expected-source", EXPECTED,
                "--entrypoint", "lan=http://127.0.0.1:3104",
                "--entrypoint", "funnel=http://127.0.0.1:3105",
                "--build-manifest", "/tmp/nexolab-no-manifest.json",
            ])
        self.assertEqual(result, 2)
        self.assertIn("provided together", output.getvalue())



if __name__ == "__main__":
    unittest.main()
