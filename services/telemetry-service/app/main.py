from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import create_api_router
from app.config import Settings
from app.db import Database
from app.ingestion import TelemetryIngestor
from app.live import LiveTelemetryHub
from app.live_api import create_live_router
from app.mqtt_consumer import MqttConsumer
from app.state import RuntimeState


SERVICE_VERSION = "0.3.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database = Database(resolved.database_url)
    state = RuntimeState()
    live_hub = LiveTelemetryHub(
        state=state,
        queue_maxsize=resolved.websocket_client_queue_maxsize,
    )
    ingestor = TelemetryIngestor(
        database=database,
        state=state,
        queue_maxsize=resolved.ingestion_queue_maxsize,
        on_persisted=live_hub.publish_from_thread,
    )
    mqtt_consumer: MqttConsumer | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal mqtt_consumer

        if resolved.auto_create_schema:
            database.create_schema()

        state.set_database_ready(database.ping())
        live_hub.start(asyncio.get_running_loop())
        ingestor.start()

        if resolved.mqtt_enabled:
            mqtt_consumer = MqttConsumer(resolved, ingestor, state)
            mqtt_consumer.start()
        else:
            state.set_mqtt_connected(True)

        try:
            yield
        finally:
            if mqtt_consumer is not None:
                mqtt_consumer.stop()
            await asyncio.to_thread(ingestor.stop)
            live_hub.stop()
            database.dispose()

    app = FastAPI(
        title="NEXOLAB Telemetry Service",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.database = database
    app.state.runtime = state
    app.state.ingestor = ingestor
    app.state.live_hub = live_hub
    app.include_router(
        create_api_router(
            database,
            max_history_days=resolved.history_max_range_days,
            max_page_size=resolved.api_max_page_size,
        )
    )
    app.include_router(
        create_live_router(
            database,
            live_hub,
            state,
            heartbeat_seconds=resolved.websocket_heartbeat_seconds,
            send_timeout_seconds=resolved.websocket_send_timeout_seconds,
            resume_limit=resolved.websocket_resume_limit,
        )
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": resolved.service_name,
            "version": SERVICE_VERSION,
        }

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> JSONResponse:
        database_ready = database.ping()
        state.set_database_ready(database_ready)
        snapshot = state.snapshot()
        ready = bool(database_ready and snapshot["mqtt_connected"])
        payload = {
            "status": "ready" if ready else "not_ready",
            "database": "ready" if database_ready else "not_ready",
            "mqtt": (
                "ready" if snapshot["mqtt_connected"] else "not_ready"
            ),
            "queue_size": snapshot["queue_size"],
            "websocket_clients": snapshot["websocket_clients"],
            "last_error": snapshot["last_error"],
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/metrics")
    def metrics() -> dict[str, object]:
        return state.snapshot()

    return app


app = create_app()
