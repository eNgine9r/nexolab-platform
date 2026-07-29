from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings
from app.main import create_app as create_base_app
from app.refrigeration.sensor_configuration_api import create_sensor_configuration_router
from app.refrigeration.sensor_configuration_repository import PostgresSensorConfigurationRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_base_app(settings)
    resolved = app.state.settings
    sensor_configuration_repository = PostgresSensorConfigurationRepository(app.state.database)
    app.state.sensor_configuration_repository = sensor_configuration_repository
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
