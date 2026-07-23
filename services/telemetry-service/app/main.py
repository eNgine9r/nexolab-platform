from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import create_api_router
from app.config import Settings
from app.db import Database
from app.ingestion import TelemetryIngestor
from app.mqtt_consumer import MqttConsumer
from app.state import RuntimeState


SERVICE_VERSION = "0.2.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database = Database(resolved.database_url)
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database=database,
        state=state,
        queue_maxsize=resolved.ingestion_queue_maxsize,
    )
    mqtt_consumer: MqttConsumer | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal mqtt_consumer

        if resolved.auto_create_schema:
            database.create_schema()

        state.set_database_ready(database.ping())
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
            ingestor.stop()
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
    app.include_router(
        create_api_router(
            database,
            max_history_days=resolved.history_max_range_days,
            max_page_size=resolved.api_max_page_size,
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
            "last_error": snapshot["last_error"],
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/metrics")
    def metrics() -> dict[str, object]:
        return state.snapshot()

    return app


app = create_app()
