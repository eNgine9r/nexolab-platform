from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.climate_catalog.api import create_climate_catalog_router
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.durable_spool import DurableIngestionSpool
from app.main import create_app as create_base_app
from app.refrigeration.sensor_configuration_api import (
    create_sensor_configuration_router,
)
from app.refrigeration.sensor_configuration_repository import (
    PostgresSensorConfigurationRepository,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_base_app(settings)
    resolved = app.state.settings
    climate_catalog_repository = PostgresClimateCatalogRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    sensor_configuration_repository = PostgresSensorConfigurationRepository(
        app.state.database,
        climate_catalog_repository=climate_catalog_repository,
    )
    app.state.climate_catalog_repository = climate_catalog_repository
    app.state.sensor_configuration_repository = sensor_configuration_repository
    app.include_router(
        create_climate_catalog_router(
            climate_catalog_repository,
            app.state.security_dependencies,
            default_organization_id=resolved.auth_default_organization_id,
        )
    )
    app.include_router(
        create_sensor_configuration_router(
            sensor_configuration_repository,
            app.state.refrigeration_repository,
            app.state.object_storage,
            signed_url_seconds=resolved.equipment_image_signed_url_seconds,
            security_dependencies=app.state.security_dependencies,
            security_repository=app.state.security_repository,
            default_organization_id=resolved.auth_default_organization_id,
        )
    )
    _install_durable_ingestion_lifespan(app)
    return app


def _install_durable_ingestion_lifespan(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.ingestion_spool = None
    if not settings.mqtt_enabled or not settings.ingestion_spool_enabled:
        return

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def durable_lifespan(application: FastAPI) -> AsyncIterator[None]:
        spool = DurableIngestionSpool(
            settings.ingestion_spool_path,
            max_records=settings.ingestion_spool_max_records,
            max_bytes=settings.ingestion_spool_max_bytes,
            busy_timeout_seconds=settings.ingestion_spool_busy_timeout_seconds,
        )
        application.state.ingestion_spool = spool
        application.state.ingestor.attach_durable_spool(spool)
        try:
            async with original_lifespan(application):
                yield
        finally:
            spool.close()

    app.router.lifespan_context = durable_lifespan


app = create_app()
