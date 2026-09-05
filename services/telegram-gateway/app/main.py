from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.backend import BackendError, SnapshotClient, build_snapshot_client
from app.config import (
    Settings,
    read_secret_file,
    validate_enabled_configuration,
    validate_miniapp_configuration,
)
from app.miniapp import (
    MiniAppAccessError,
    MiniAppService,
    validate_identity_links_file,
)
from app.outbox import DeliveryOutbox
from app.service import GatewayRuntime, TelegramDeliveryWorker
from app.telegram import TelegramClient

LOGGER = logging.getLogger(__name__)


class MiniAppReportRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16 * 1024)
    start_hint: str | None = Field(default=None, max_length=128)


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
    miniapp_service: MiniAppService | None = None
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

    if resolved.telegram_miniapp_enabled:
        try:
            validate_miniapp_configuration(resolved)
            miniapp_token = read_secret_file(
                resolved.telegram_bot_token_file,
                label="Telegram bot token",
            )
            validate_identity_links_file(resolved.telegram_identity_links_file)
            miniapp_backend = snapshot_client or build_snapshot_client(resolved)
            miniapp_service = MiniAppService(
                resolved,
                miniapp_backend,
                miniapp_token,
            )
        except (MiniAppAccessError, OSError, ValueError) as error:
            startup_error_code = startup_error_code or "miniapp_configuration_invalid"
            LOGGER.error("Telegram Mini App configuration is invalid: code=miniapp_configuration_invalid")

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
    app.state.miniapp_service = miniapp_service
    app.state.startup_error_code = startup_error_code

    @app.get("/health/live")
    def health_live() -> dict[str, object]:
        return {"status": "alive", "service": resolved.service_name}

    @app.get("/health/ready")
    def health_ready() -> JSONResponse:
        any_enabled = resolved.telegram_enabled or resolved.telegram_miniapp_enabled
        if not any_enabled:
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
        delivery_ready = not resolved.telegram_enabled or state.running
        miniapp_ready = not resolved.telegram_miniapp_enabled or miniapp_service is not None
        ready = delivery_ready and miniapp_ready
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "degraded",
                "enabled": True,
                "delivery_enabled": resolved.telegram_enabled,
                "miniapp_enabled": resolved.telegram_miniapp_enabled,
                "running": state.running,
                "last_poll_at": _iso(state.last_poll_at),
                "last_send_at": _iso(state.last_send_at),
                "last_error_code": state.last_error_code,
                "recovered_unknown_deliveries": state.recovered_unknown_deliveries,
                "deliveries": counts,
            },
        )

    @app.post("/miniapp/report")
    def miniapp_report(payload: MiniAppReportRequest) -> JSONResponse:
        if not resolved.telegram_miniapp_enabled:
            return _miniapp_error(503, "miniapp_disabled")
        if miniapp_service is None:
            return _miniapp_error(503, "miniapp_unavailable")
        try:
            report = miniapp_service.get_report(
                payload.init_data,
                start_hint=payload.start_hint,
            )
        except MiniAppAccessError as error:
            if error.code in {"telegram_init_data_invalid", "telegram_init_data_expired"}:
                return _miniapp_error(401, error.code)
            if error.code in {"miniapp_identity_links_invalid"}:
                return _miniapp_error(503, error.code)
            return _miniapp_error(403, error.code)
        except BackendError as error:
            if error.code == "backend_http_404":
                return _miniapp_error(404, "miniapp_report_not_found")
            if error.code in {"backend_http_401", "backend_http_403"}:
                return _miniapp_error(403, "miniapp_access_denied")
            return _miniapp_error(503, "miniapp_backend_unavailable")
        return JSONResponse(
            status_code=200,
            content={"report": report},
            headers={"Cache-Control": "no-store"},
        )

    return app


def _miniapp_error(status_code: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code}},
        headers={"Cache-Control": "no-store"},
    )


def _iso(value: object) -> str | None:
    return None if value is None else value.isoformat()


app = create_app()
