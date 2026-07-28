from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.alerts.api import create_alert_router
from app.alerts.processor import AlertProcessor
from app.alerts.repository import AlertRepository
from app.api import create_api_router
from app.config import Settings
from app.ingestion import TelemetryIngestor
from app.live import LiveTelemetryHub
from app.live_api import create_live_router
from app.metrics import render_prometheus
from app.model_registry import register_models
from app.mqtt_consumer import MqttConsumer
from app.mqtt_tls import MQTTTLSConfig
from app.nodes.api import create_node_router
from app.nodes.broker_adapter import DynamicSecurityAdminAdapter
from app.nodes.broker_api import create_broker_control_router
from app.nodes.broker_control import BrokerControlSecretCipher
from app.nodes.broker_node_repository import BrokerSynchronizedNodeRepository
from app.nodes.broker_repository import BrokerControlRepository
from app.nodes.broker_worker import BrokerControlWorker
from app.nodes.ingress import NodeIngressAuthorizer
from app.nodes.repository import NodeRepository
from app.refrigeration.api import create_refrigeration_router
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.storage import S3ObjectStorage, UnavailableObjectStorage
from app.reports.api import create_report_router
from app.reports.output_api import create_report_output_router
from app.reports.output_queries import ReportOutputQueryRepository
from app.reports.output_repository import ReportOutputRepository
from app.reports.repository import ReportRepository
from app.retention import RetentionWorker
from app.security.api import create_security_router
from app.security.authentication import JwtAuthenticator
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository
from app.sessions.api import create_session_router
from app.sessions.audit_api import create_session_audit_router
from app.sessions.audit_repository import AuditedSessionRepository
from app.sessions.configuration_api import create_session_configuration_router
from app.sessions.telemetry_api import create_session_telemetry_router
from app.sessions.telemetry_attribution import SessionAwareDatabase
from app.state import RuntimeState


SERVICE_VERSION = "0.15.0"
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    register_models()
    database = SessionAwareDatabase(
        resolved.database_url,
        connect_timeout_seconds=resolved.database_connect_timeout_seconds,
    )
    session_repository = AuditedSessionRepository(database)
    alert_repository = AlertRepository(database)
    alert_processor = AlertProcessor(
        database,
        default_organization_id=resolved.auth_default_organization_id,
    )
    refrigeration_repository = PostgresRefrigerationLayoutRepository(database)
    security_repository = SecurityRepository(database)
    broker_control_repository, broker_control_worker = _create_broker_control(
        resolved,
        database,
    )
    node_repository_type = (
        BrokerSynchronizedNodeRepository
        if broker_control_repository is not None
        else NodeRepository
    )
    node_repository = node_repository_type(
        database,
        security_repository=security_repository,
        broker_control_repository=broker_control_repository,
    )
    node_ingress_authorizer = (
        NodeIngressAuthorizer(database)
        if resolved.mqtt_node_registry_enforced
        else None
    )
    report_repository = ReportRepository(
        database,
        security_repository=security_repository,
    )
    report_output_repository = ReportOutputRepository(
        database,
        security_repository=security_repository,
    )
    report_output_query_repository = ReportOutputQueryRepository(database)
    security_dependencies = _create_security_dependencies(
        resolved,
        security_repository,
    )
    object_storage = _create_object_storage(resolved)
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
        after_persist=alert_processor.process_payload,
        authorize_ingress=(
            node_ingress_authorizer.authorize
            if node_ingress_authorizer is not None
            else None
        ),
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
        if broker_control_worker is not None:
            broker_control_worker.start()

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
            if broker_control_worker is not None:
                await asyncio.to_thread(broker_control_worker.stop)
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
            allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=[
                "Content-Disposition",
                "ETag",
                "Idempotent-Replay",
                "X-Content-SHA256",
                "X-Manifest-SHA256",
            ],
            max_age=600,
        )

    app.state.settings = resolved
    app.state.database = database
    app.state.session_repository = session_repository
    app.state.alert_repository = alert_repository
    app.state.alert_processor = alert_processor
    app.state.refrigeration_repository = refrigeration_repository
    app.state.node_repository = node_repository
    app.state.node_ingress_authorizer = node_ingress_authorizer
    app.state.broker_control_repository = broker_control_repository
    app.state.broker_control_worker = broker_control_worker
    app.state.report_repository = report_repository
    app.state.report_output_repository = report_output_repository
    app.state.report_output_query_repository = report_output_query_repository
    app.state.security_repository = security_repository
    app.state.security_dependencies = security_dependencies
    app.state.object_storage = object_storage
    app.state.runtime = state
    app.state.ingestor = ingestor
    app.state.live_hub = live_hub
    app.state.retention_worker = retention_worker
    app.include_router(create_security_router(security_repository, security_dependencies))
    app.include_router(create_node_router(node_repository, security_dependencies))
    app.include_router(
        create_broker_control_router(
            node_repository,
            broker_control_repository,
            security_dependencies,
        )
    )
    app.include_router(create_alert_router(alert_repository, security_dependencies))
    app.include_router(create_report_router(report_repository, security_dependencies))
    app.include_router(
        create_report_output_router(
            report_output_repository,
            report_output_query_repository,
            security_dependencies,
            security_repository,
        )
    )
    app.include_router(
        create_api_router(
            database,
            max_history_days=resolved.history_max_range_days,
            max_page_size=resolved.api_max_page_size,
            security_dependencies=security_dependencies,
        )
    )
    app.include_router(create_session_router(session_repository, security_dependencies))
    app.include_router(
        create_session_configuration_router(
            session_repository,
            security_dependencies,
        )
    )
    app.include_router(
        create_session_audit_router(
            session_repository,
            security_dependencies,
        )
    )
    app.include_router(
        create_session_telemetry_router(
            database,
            max_history_days=resolved.history_max_range_days,
            max_page_size=resolved.api_max_page_size,
            security_dependencies=security_dependencies,
        )
    )
    app.include_router(
        create_refrigeration_router(
            refrigeration_repository,
            object_storage,
            image_max_bytes=resolved.equipment_image_max_bytes,
            signed_url_seconds=resolved.equipment_image_signed_url_seconds,
            security_dependencies=security_dependencies,
            security_repository=security_repository,
            default_organization_id=resolved.auth_default_organization_id,
        )
    )
    app.include_router(
        create_live_router(
            database,
            live_hub,
            state,
            heartbeat_seconds=resolved.websocket_heartbeat_seconds,
            send_timeout_seconds=resolved.websocket_send_timeout_seconds,
            auth_timeout_seconds=resolved.websocket_auth_timeout_seconds,
            resume_limit=resolved.websocket_resume_limit,
            security_dependencies=security_dependencies,
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


def _create_broker_control(
    settings: Settings,
    database: SessionAwareDatabase,
) -> tuple[BrokerControlRepository | None, BrokerControlWorker | None]:
    if not settings.broker_control_enabled:
        return None, None

    cipher = BrokerControlSecretCipher.from_key_file(
        settings.broker_control_encryption_key_file or "",
        key_id=settings.broker_control_encryption_key_id or "",
    )
    repository = BrokerControlRepository(database, cipher)
    adapter = DynamicSecurityAdminAdapter(
        executable=settings.broker_control_admin_executable,
        broker_host=settings.mqtt_host,
        broker_port=settings.mqtt_port,
        admin_username=settings.broker_control_admin_username or "",
        admin_client_id=settings.broker_control_admin_client_id,
        admin_password_file=settings.broker_control_admin_password_file or "",
        timeout_seconds=settings.broker_control_command_timeout_seconds,
        tls_config=MQTTTLSConfig.from_settings(settings),
    )
    worker = BrokerControlWorker(
        database=database,
        repository=repository,
        adapter=adapter,
        poll_interval_seconds=settings.broker_control_poll_interval_seconds,
        max_commands_per_run=settings.broker_control_max_commands_per_run,
        max_attempts=settings.broker_control_max_attempts,
        retry_initial_seconds=settings.broker_control_retry_initial_seconds,
        retry_max_seconds=settings.broker_control_retry_max_seconds,
        stale_lock_seconds=settings.broker_control_stale_lock_seconds,
    )
    return repository, worker


def _create_security_dependencies(
    settings: Settings,
    repository: SecurityRepository,
) -> SecurityDependencies:
    authenticator: JwtAuthenticator | None = None
    if settings.auth_mode == "jwt":
        authenticator = JwtAuthenticator(
            public_key=settings.resolved_auth_jwt_public_key,
            jwks_url=settings.auth_jwt_jwks_url,
            algorithm=settings.auth_jwt_algorithm,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            provider=settings.auth_jwt_provider,
        )
    return SecurityDependencies(
        repository,
        mode=settings.auth_mode,
        authenticator=authenticator,
        default_organization_id=settings.auth_default_organization_id,
    )


def _create_object_storage(settings: Settings) -> S3ObjectStorage | UnavailableObjectStorage:
    if settings.object_storage_backend != "s3":
        return UnavailableObjectStorage()
    return S3ObjectStorage(
        bucket=settings.object_storage_bucket,
        endpoint_url=settings.object_storage_endpoint_url,
        public_endpoint_url=settings.object_storage_public_endpoint_url,
        region=settings.object_storage_region,
        access_key_id=settings.object_storage_access_key_id,
        secret_access_key=settings.object_storage_secret_access_key,
        force_path_style=settings.object_storage_force_path_style,
    )


app = create_app()
