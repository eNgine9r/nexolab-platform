from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api import create_api_router
from app.config import Settings
from app.db import Database
from app.ingestion import TelemetryIngestor
from app.live import LiveTelemetryHub
from app.live_api import create_live_router
from app.metrics import render_prometheus
from app.mqtt_consumer import MqttConsumer
from app.retention import RetentionWorker
from app.state import RuntimeState


SERVICE_VERSION = "0.4.0"
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database = Database(
        resolved.database_url,
        connect_timeout_seconds=resolved.database_connect_timeout_seconds,
    )
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
        payload_max_bytes=resolved.ingestion_payload_max_bytes,
        dead_letter_payload_max_bytes=resolved.dead_letter_payload_max_bytes,
        database_retry_initial_seconds=resolved.database_retry_initial_seconds,
        database_retry_max_seconds=resolved.database_retry_max_seconds,
    )
    retention_worker = RetentionWorker(
        database=database,
        state=state,
        interval_seconds=resolved.retention_interval_seconds,
        batch_size=resolved.retention_batch_size,
        telemetry_retention_days=resolved.telemetry_retention_days,
        raw_payload_retention_days=resolved.raw_payload_retention_days,
        dead_letter_retention_days=resolved.dead_letter_retention_days,
    )
    mqtt_consumer: MqttConsumer | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal mqtt_consumer

        if resolved.auto_create_schema:
            database.create_schema()

        if database.ping():
            state.mark_database_success()
        else:
            state.mark_database_failure("database ping failed")

        live_hub.start(asyncio.get_running_loop())
        ingestor.start()
        if resolved.retention_enabled:
            retention_worker.start()

        if resolved.mqtt_enabled:
            mqtt_consumer = MqttConsumer(resolved, ingestor, state)
            mqtt_consumer.start()
        else:
            state.set_mqtt_connected(True)
            state.set_mqtt_error(None)

        try:
            yield
        finally:
            if mqtt_consumer is not None:
                mqtt_consumer.stop()
            await asyncio.to_thread(ingestor.stop)
            if resolved.retention_enabled:
                await asyncio.to_thread(retention_worker.stop)
            live_hub.stop()
            database.dispose()

    app = FastAPI(
        title="NEXOLAB Telemetry Service",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    cors_origins = resolved.parsed_cors_allowed_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=resolved.cors_allow_credentials,
            allow_methods=["GET"],
            allow_headers=["*"],
            max_age=600,
        )

    app.state.settings = resolved
    app.state.database = database
    app.state.runtime = state
    app.state.ingestor = ingestor
    app.state.live_hub = live_hub
    app.state.retention_worker = retention_worker
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
        if database_ready:
            state.mark_database_success()
        else:
            state.mark_database_failure("database ping failed")

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
            "database_outage_since": snapshot["database_outage_since"],
            "last_persisted_at": snapshot["last_persisted_at"],
            "ingestion_lag_seconds": snapshot["ingestion_lag_seconds"],
            "mqtt_error": snapshot["mqtt_error"],
            "database_error": snapshot["database_error"],
            "last_error": snapshot["last_error"],
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            render_prometheus(state.snapshot()),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )

    @app.get("/metrics/json")
    def metrics_json() -> dict[str, object]:
        return state.snapshot()

    return app


app = create_app()
