from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.backend import SnapshotClient, build_snapshot_client
from app.config import Settings, read_secret_file, validate_enabled_configuration
from app.outbox import DeliveryOutbox
from app.service import GatewayRuntime, TelegramDeliveryWorker
from app.telegram import TelegramClient

LOGGER = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    snapshot_client: SnapshotClient | None = None,
    telegram_client: TelegramClient | None = None,
    outbox: DeliveryOutbox | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    logging.basicConfig(level=getattr(logging, resolved.log_level.upper(), logging.INFO))
    runtime = GatewayRuntime(enabled=resolved.telegram_enabled)
    worker: TelegramDeliveryWorker | None = None
    startup_error_code: str | None = None

    if resolved.telegram_enabled:
        try:
            validate_enabled_configuration(resolved)
            token = read_secret_file(resolved.telegram_bot_token_file, label="Telegram bot token")
            delivery_outbox = outbox or DeliveryOutbox(resolved.telegram_state_db_path)
            backend = snapshot_client or build_snapshot_client(resolved)
            telegram = telegram_client or TelegramClient(
                resolved.telegram_bot_api_base_url,
                token,
                timeout_seconds=resolved.telegram_request_timeout_seconds,
            )
            worker = TelegramDeliveryWorker(
                resolved,
                backend,
                telegram,
                delivery_outbox,
                runtime,
            )
            app_outbox: DeliveryOutbox | None = delivery_outbox
        except (OSError, ValueError) as error:
            startup_error_code = "configuration_invalid"
            app_outbox = None
            LOGGER.error("Telegram gateway configuration is invalid: code=%s", startup_error_code)
    else:
        app_outbox = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if worker is not None:
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(title="NEXOLAB Telegram Gateway", version="1.0.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.runtime = runtime
    app.state.worker = worker
    app.state.outbox = app_outbox
    app.state.startup_error_code = startup_error_code

    @app.get("/health/live")
    def health_live() -> dict[str, object]:
        return {"status": "alive", "service": resolved.service_name}

    @app.get("/health/ready")
    def health_ready() -> JSONResponse:
        if not resolved.telegram_enabled:
            return JSONResponse(
                status_code=200,
                content={"status": "ready", "enabled": False, "mode": "disabled"},
            )
        if startup_error_code is not None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "enabled": True,
                    "error_code": startup_error_code,
                },
            )
        state = runtime.snapshot()
        counts = app_outbox.counts() if app_outbox is not None else {}
        ready = state.running
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "degraded",
                "enabled": True,
                "running": state.running,
                "last_poll_at": _iso(state.last_poll_at),
                "last_send_at": _iso(state.last_send_at),
                "last_error_code": state.last_error_code,
                "recovered_unknown_deliveries": state.recovered_unknown_deliveries,
                "deliveries": counts,
            },
        )

    return app


def _iso(value: object) -> str | None:
    return None if value is None else value.isoformat()


app = create_app()
