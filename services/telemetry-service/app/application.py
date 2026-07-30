from __future__ import annotations

from fastapi import FastAPI

from app.climate_catalog.api import create_climate_catalog_router
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.main import create_app as create_base_app
from app.refrigeration.sensor_configuration_api import create_sensor_configuration_router
from app.refrigeration.sensor_configuration_repository import PostgresSensorConfigurationRepository


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
    return app


app = create_app()
