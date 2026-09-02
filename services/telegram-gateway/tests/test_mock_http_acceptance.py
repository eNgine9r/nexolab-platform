from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from app.backend import NoAccessTokenProvider, SnapshotClient
from app.config import Settings
from app.outbox import DeliveryOutbox
from app.service import GatewayRuntime, TelegramDeliveryWorker
from app.telegram import TelegramClient
from tests.support import ORG_ID, sample_snapshot
from tests.test_service import DESTINATION, DIRECT_LINK, NOW


class MockHandler(BaseHTTPRequestHandler):
    response_payload: object = {}
    requests: list[dict[str, object]] = []

    def log_message(self, format, *args):
        return

    def do_GET(self):
        self.__class__.requests.append({"method": "GET", "path": self.path})
        self._reply()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append({"method": "POST", "path": self.path, "body": body})
        self._reply()

    def _reply(self):
        encoded = json.dumps(self.__class__.response_payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _snapshot_payload():
    snapshot = sample_snapshot()
    return {
        "id": snapshot.id,
        "organization_id": snapshot.organization_id,
        "profile_id": snapshot.profile_id,
        "equipment_id": snapshot.equipment_id,
        "scheduled_for": snapshot.scheduled_for.isoformat(),
        "payload_sha256": snapshot.payload_sha256,
        "payload": snapshot.payload,
    }


class BackendHandler(MockHandler):
    response_payload = {
        "items": [_snapshot_payload()],
        "count": 1,
        "limit": 50,
        "offset": 0,
        "next_offset": None,
    }
    requests: list[dict[str, object]] = []


class TelegramHandler(MockHandler):
    response_payload = {"ok": True, "result": {"message_id": 321}}
    requests: list[dict[str, object]] = []


def _start_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_real_http_clients_deliver_one_snapshot_without_replay(tmp_path) -> None:
    BackendHandler.requests = []
    TelegramHandler.requests = []
    backend_server, backend_thread = _start_server(BackendHandler)
    telegram_server, telegram_thread = _start_server(TelegramHandler)
    try:
        backend_url = f"http://127.0.0.1:{backend_server.server_port}"
        telegram_url = f"http://127.0.0.1:{telegram_server.server_port}"
        token = "1:" + ("A" * 35)
        source = SnapshotClient(
            backend_url,
            ORG_ID,
            NoAccessTokenProvider(),
            timeout_seconds=2,
        )
        sink = TelegramClient(telegram_url, token, timeout_seconds=2)
        config = Settings(
            telegram_enabled=True,
            telegram_state_db_path=str(tmp_path / "outbox.db"),
            telegram_destination_chat_id=DESTINATION,
            telegram_mini_app_url_template=DIRECT_LINK,
            nexolab_backend_auth_mode="none",
            nexolab_backend_organization_id=ORG_ID,
            telegram_snapshot_max_pages=1,
        )
        outbox = DeliveryOutbox(config.telegram_state_db_path)
        runtime = GatewayRuntime(enabled=True)
        worker = TelegramDeliveryWorker(
            config,
            source,
            sink,
            outbox,
            runtime,
            clock=lambda: NOW,
        )
        worker.run_once()
        worker.run_once()

        posts = [item for item in TelegramHandler.requests if item["method"] == "POST"]
        assert len(posts) == 1
        body = posts[0]["body"]
        assert body["chat_id"] == DESTINATION
        assert "parse_mode" not in body
        button = body["reply_markup"]["inline_keyboard"][0][0]
        assert button == {
            "text": "Відкрити NEXOLAB",
            "url": "https://t.me/nexolab_bot/nexolab?startapp=report_snapshot-1",
        }
        assert "web_app" not in button
        record = outbox.get_by_snapshot("snapshot-1", DESTINATION)
        assert record is not None
        assert record.state.value == "sent"
        assert record.telegram_message_id == 321
        assert record.attempts == 1
        assert runtime.snapshot().last_send_at == NOW
        assert BackendHandler.requests
    finally:
        _stop_server(backend_server, backend_thread)
        _stop_server(telegram_server, telegram_thread)
