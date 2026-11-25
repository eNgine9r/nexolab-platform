"""Hermetic NEXOLAB #1466 local access/Session API probe acceptance."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "inspect-site-lan-access.py"
spec = importlib.util.spec_from_file_location("nexolab_lan_access", SOURCE)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

HOST = "172.18.48.66"
ORIGIN = "http://172.18.48.66:3000"
HTML = [("Content-Type", "text/html; charset=utf-8")]
JSON = [("Content-Type", "application/json")]
PAGE = b'<html lang="uk"><title>NEXOLAB</title></html>'
LOGIN = b'<html lang="uk"><title>NEXOLAB</title><input type="password"/></html>'
READY = json.dumps({"status": "ready", "database": "ready", "mqtt": "ready"}).encode()


def fixture():
    # Entries indexed by fixed port/path and no HTTP requests generated.
    return {
        (3000, "/"): (200, HTML, PAGE),
        (3000, "/login"): (200, HTML, LOGIN),
        (8082, "/health/ready"): (200, JSON, READY),
        (8082, "/api/v1/auth/session"): (
            401, JSON + [("Access-Control-Allow-Origin", ORIGIN)], b'{"detail":"unauthorized"}'
        ),
    }


class SiteLanAccessTests(unittest.TestCase):
    def setUp(self):
        self.routes = fixture()
        self.calls = []

    def fetch(self, host, port, path, *, timeout, origin=None):
        self.calls.append((host, port, path, origin))
        self.assertEqual(host, HOST)
        self.assertGreater(timeout, 0)
        if port == 8082 and path == "/api/v1/auth/session":
            self.assertEqual(origin, ORIGIN)
        else:
            self.assertIsNone(origin)
        return self.routes[(port, path)]

    def result(self, host=HOST, **kwargs):
        return probe.evaluate(host, fetch=self.fetch, **kwargs)

    def test_correct_original_local_lan_returns_only_auth_path_reachable(self):
        x = self.result()
        self.assertEqual(x["status"], probe.READY_VALUE)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(x["checks"].values()))
        for key in ("browser_login_verified", "live_telemetry_verified", "hardware_verified",
                    "site_mutation"):
            self.assertFalse(x[key])
        self.assertTrue(x["read_only"])

    def test_literal_private_ip_and_loopback_only(self):
        for ip in ("172.18.48.66", "10.1.2.3", "192.168.20.21", "127.0.0.1"):
            with self.subTest(ip=ip):
                self.assertEqual(probe.verify_host(ip), ip)

    def test_hostname_and_remote_and_bad_ip_refused_before_network(self):
        for value in ("nexolab-edge-01", "8.8.8.8", "169.254.1.10", "0.0.0.0",
                      "192.168.1.256", "::1", "127.0.0.1:8082", "172.18.48.66/foo",
                      "http://172.18.48.66", "172.18.48.66\nX-Test: injected"):
            with self.subTest(value=value):
                r = self.result(value)
                self.assertEqual(r["status"], "BLOCKED")
                self.assertEqual(self.calls, [])

    def test_redirect_to_external_login_never_followed(self):
        self.routes[3000, "/login"] = (302, [("Location", "https://external.example/login")], b"")
        x = self.result()
        self.assertEqual(x["reason"], "login_page_unavailable_or_not_html")
        self.assertEqual(len(self.calls), 2)

    def test_dashboard_service_stopped(self):
        self.routes[3000, "/"] = (503, HTML, PAGE)
        self.assertEqual(self.result()["reason"], "dashboard_unavailable_or_not_html")

    def test_dashboard_fake_success_body_rejected(self):
        self.routes[3000, "/"] = (200, HTML, b"<html>unknown service</html>")
        self.assertEqual(self.result()["reason"], "dashboard_identity_unverified")

    def test_login_generic_page_without_password_rejected(self):
        self.routes[3000, "/login"] = (200, HTML, PAGE)
        self.assertEqual(self.result()["reason"], "login_form_not_rendered")

    def test_login_html_wrong_content_type_rejected(self):
        self.routes[3000, "/login"] = (200, JSON, LOGIN)
        self.assertEqual(self.result()["reason"], "login_page_unavailable_or_not_html")

    def test_api_not_ready_blocks_site_access(self):
        for data in (
            {"status": "blocked", "database": "ready", "mqtt": "ready"},
            {"status": "ready", "database": "unavailable", "mqtt": "ready"},
            {"status": "ready", "database": "ready", "mqtt": "error"},
            {"status": "ready", "database": "ready"},
        ):
            with self.subTest(data=data):
                self.calls = []
                self.routes[8082, "/health/ready"] = (200, JSON, json.dumps(data).encode())
                x = self.result()
                self.assertEqual(x["reason"], "api_or_dependencies_not_ready")
                self.assertNotIn((HOST, 8082, "/api/v1/auth/session", ORIGIN), self.calls)

    def test_api_error_and_invalid_json_block(self):
        for replacement,reason in [
            ((502, JSON, READY), "session_api_not_ready"),
            ((200, HTML, READY), "session_api_not_ready"),
            ((200, JSON, b"not-json"), "api_readiness_invalid_json"),
            ((200, JSON, b"null"), "api_or_dependencies_not_ready"),
        ]:
            with self.subTest(reason=reason):
                self.routes[8082, "/health/ready"] = replacement
                self.assertEqual(self.result()["reason"], reason)

    def test_session_auth_is_not_mistakenly_bypassed(self):
        for status in (200, 302, 403, 500):
            with self.subTest(status=status):
                self.routes[8082, "/api/v1/auth/session"] = (
                    status, JSON + [("Access-Control-Allow-Origin", ORIGIN)], b""
                )
                self.assertEqual(self.result()["reason"], "session_auth_expected_401")

    def test_missing_duplicate_wrong_wildcard_cors_all_blocked(self):
        for headers in (
            JSON,
            JSON + [("Access-Control-Allow-Origin", "*")],
            JSON + [("Access-Control-Allow-Origin", "http://127.0.0.1:3100")],
            JSON + [("Access-Control-Allow-Origin", ORIGIN)] * 2,
            JSON + [("Access-Control-Allow-Origin", ORIGIN+", *")],
        ):
            with self.subTest(headers=headers):
                self.routes[8082, "/api/v1/auth/session"] = (401, headers, b"")
                self.assertEqual(self.result()["reason"],
                                 "session_origin_not_explicitly_authorized")

    def test_bounded_invalid_timeout_fails_without_request(self):
        for timeout in (0, -1, 10.1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                self.assertEqual(self.result(timeout=timeout)["status"], "BLOCKED")
                self.assertEqual(self.calls, [])

    def test_backend_connection_failure_does_not_leak_details(self):
        def unavailable(host,port,path,**kw):
            raise probe.ProbeBlocked("required_local_endpoint_unreachable")
        o=probe.evaluate(HOST,fetch=unavailable)
        self.assertEqual(o["status"], "BLOCKED")
        self.assertEqual(o["reason"], "required_local_endpoint_unreachable")
        self.assertNotIn("password",json.dumps(o))

    def test_nonmatching_unauthenticated_session_origin_blocks(self):
        self.routes[8082, "/api/v1/auth/session"] = (
            401, JSON + [("access-control-allow-origin", "http://localhost:3000")], b""
        )
        self.assertEqual(self.result()["status"], "BLOCKED")


class LoopbackHttpBehaviorTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://example.invalid/")
                    self.end_headers()
                elif self.path == "/large":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    try: self.wfile.write(b"A" * (probe.MAX_BODY + 10))
                    except BrokenPipeError: pass
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(PAGE)

            def log_message(self,*args):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.server_thread.start()
        # Unittest executes cleanups in LIFO order: stop serving before join.
        self.addCleanup(self.server_thread.join, 1.0)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def test_raw_http_client_does_not_follow_redirects(self):
        code,headers,body = probe.request("127.0.0.1",self.http.server_port,
                                           "/redirect",timeout=2)
        self.assertEqual(code,302)
        self.assertEqual(body,b"")

    def test_raw_http_client_rejects_oversize_response(self):
        with self.assertRaisesRegex(probe.ProbeBlocked, "response_body_exceeds_bound"):
            probe.request("127.0.0.1",self.http.server_port,"/large",timeout=2)

    def test_raw_http_client_reads_bounded_local_html(self):
        code,headers,body=probe.request("127.0.0.1",self.http.server_port,"/",timeout=2)
        self.assertEqual(code,200)
        self.assertEqual(body,PAGE)
        self.assertEqual(probe.one_header(headers,"content-type"),"text/html")


if __name__ == "__main__":
    unittest.main()
