from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.climate_catalog.api import create_climate_catalog_router
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.commissioning.api import create_commissioning_router
from app.commissioning.activation_client import DeviceAgentActivationClient
from app.commissioning.activation_repository import CommissioningActivationRepository
from app.commissioning.activation_service import CommissioningActivationService
from app.commissioning.repository import CommissioningRepository
from app.commissioning.preflight_client import DeviceAgentPreflightClient
from app.commissioning.preflight_repository import CommissioningPreflightRepository
from app.commissioning.preflight_service import CommissioningPreflightService
from app.config import Settings
from app.durable_spool import DurableIngestionSpool
from app.daily_reports.api import create_daily_report_router
from app.daily_reports.repository import DailyReportRepository
from app.daily_reports.service import DailyReportSchedulerService
from app.equipment_discovery.api import create_equipment_discovery_router
from app.equipment_discovery.policy import DiscoveryPolicy
from app.equipment_discovery.repository import EquipmentDiscoveryRepository
from app.equipment_discovery.service import EquipmentDiscoveryService
from app.latest_projection_reconcile import reconcile_latest_projection
from app.main import create_app as create_base_app
from app.refrigeration.controller_binding_repository import (
    PostgresRefrigerationControllerBindingRepository,
)
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
    discovery_repository = EquipmentDiscoveryRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    commissioning_repository = CommissioningRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    commissioning_preflight_repository = CommissioningPreflightRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    commissioning_activation_repository = CommissioningActivationRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    commissioning_controller_binding_repository = (
        PostgresRefrigerationControllerBindingRepository(app.state.database)
    )
    commissioning_preflight_service = None
    commissioning_activation_service = None
    if resolved.commissioning_device_agent_base_url:
        commissioning_preflight_service = CommissioningPreflightService(
            repository=commissioning_preflight_repository,
            client=DeviceAgentPreflightClient(
                resolved.commissioning_device_agent_base_url,
                transport_timeout_seconds=resolved.commissioning_preflight_deadline_seconds + 2.0,
            ),
            deadline_seconds=resolved.commissioning_preflight_deadline_seconds,
        )
        commissioning_activation_service = CommissioningActivationService(
            repository=commissioning_activation_repository,
            client=DeviceAgentActivationClient(
                resolved.commissioning_device_agent_base_url,
                transport_timeout_seconds=10.0,
            ),
            controller_binding_repository=commissioning_controller_binding_repository,
            security_repository=app.state.security_repository,
            freshness_seconds=resolved.commissioning_preflight_freshness_seconds,
            verification_timeout_seconds=resolved.commissioning_activation_verification_timeout_seconds,
        )
    discovery_policy = DiscoveryPolicy.from_settings(resolved)
    discovery_service = EquipmentDiscoveryService(
        discovery_repository,
        discovery_policy,
        schedule_interval_seconds=resolved.equipment_discovery_schedule_interval_seconds,
        scheduled_organization_id=resolved.auth_default_organization_id,
    )
    daily_report_repository = DailyReportRepository(
        app.state.database,
        security_repository=app.state.security_repository,
    )
    daily_report_service = DailyReportSchedulerService(
        daily_report_repository,
        enabled=resolved.daily_reports_scheduler_enabled,
        interval_seconds=resolved.daily_reports_scheduler_interval_seconds,
    )
    app.state.climate_catalog_repository = climate_catalog_repository
    app.state.sensor_configuration_repository = sensor_configuration_repository
    app.state.equipment_discovery_repository = discovery_repository
    app.state.equipment_discovery_policy = discovery_policy
    app.state.equipment_discovery_service = discovery_service
    app.state.daily_report_repository = daily_report_repository
    app.state.daily_report_service = daily_report_service
    app.state.commissioning_repository = commissioning_repository
    app.state.commissioning_preflight_repository = commissioning_preflight_repository
    app.state.commissioning_preflight_service = commissioning_preflight_service
    app.state.commissioning_activation_repository = commissioning_activation_repository
    app.state.commissioning_activation_service = commissioning_activation_service
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
    app.include_router(
        create_equipment_discovery_router(
            discovery_repository,
            discovery_service,
            discovery_policy,
            app.state.security_dependencies,
            default_organization_id=resolved.auth_default_organization_id,
        )
    )
    app.include_router(
        create_daily_report_router(
            daily_report_repository,
            app.state.security_dependencies,
            scheduler_service=daily_report_service,
        )
    )
    app.include_router(
        create_commissioning_router(
            commissioning_repository,
            app.state.security_dependencies,
            default_organization_id=resolved.auth_default_organization_id,
            preflight_repository=commissioning_preflight_repository,
            preflight_service=commissioning_preflight_service,
            activation_repository=commissioning_activation_repository,
            activation_service=commissioning_activation_service,
            activation_freshness_seconds=resolved.commissioning_preflight_freshness_seconds,
        )
    )
    _install_equipment_discovery_lifespan(app)
    _install_latest_projection_reconciliation_lifespan(app)
    _install_durable_ingestion_lifespan(app)
    _install_daily_report_lifespan(app)
    return app


def _install_latest_projection_reconciliation_lifespan(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    database = app.state.database
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def reconciliation_lifespan(application: FastAPI) -> AsyncIterator[None]:
        if settings.auto_create_schema:
            database.create_schema()
        reconcile_latest_projection(database)
        async with original_lifespan(application):
            yield

    app.router.lifespan_context = reconciliation_lifespan


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


def _install_equipment_discovery_lifespan(app: FastAPI) -> None:
    service: EquipmentDiscoveryService = app.state.equipment_discovery_service
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def discovery_lifespan(application: FastAPI) -> AsyncIterator[None]:
        service.reconcile_interrupted_scans()
        service.start_scheduler()
        try:
            async with original_lifespan(application):
                yield
        finally:
            await service.shutdown()

    app.router.lifespan_context = discovery_lifespan



def _install_daily_report_lifespan(app: FastAPI) -> None:
    service: DailyReportSchedulerService = app.state.daily_report_service
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def daily_report_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            service.start_scheduler()
            try:
                yield
            finally:
                await service.shutdown()

    app.router.lifespan_context = daily_report_lifespan


app = create_app()
