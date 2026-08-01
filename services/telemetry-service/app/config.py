from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    service_name: str = "nexolab-telemetry-service"
    log_level: str = "INFO"

    database_url: str = (
        "postgresql+psycopg://nexolab:nexolab@postgres:5432/nexolab"
    )
    database_connect_timeout_seconds: int = Field(default=3, ge=1, le=30)
    database_retry_initial_seconds: float = Field(default=0.25, ge=0.05, le=30.0)
    database_retry_max_seconds: float = Field(default=5.0, ge=0.1, le=300.0)
    auto_create_schema: bool = False

    mqtt_enabled: bool = True
    mqtt_host: str = "mqtt"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_topic: str = "nexolab/telemetry"
    mqtt_node_registry_enforced: bool = False
    mqtt_node_topic_filter: str = "nexolab/v1/+/+/telemetry"
    mqtt_node_health_topic_filter: str = "nexolab/v1/+/+/health"
    mqtt_node_status_topic_filter: str = "nexolab/v1/+/+/status"
    mqtt_client_id: str = "nexolab-telemetry-ingestion"
    mqtt_auth_required: bool = False
    mqtt_username: str | None = None
    mqtt_password_file: str | None = None
    mqtt_keepalive_seconds: int = Field(default=60, ge=10, le=3600)
    mqtt_qos: int = Field(default=1, ge=0, le=2)
    mqtt_tls_required: bool = False
    mqtt_tls_ca_file: str | None = None
    mqtt_tls_cert_file: str | None = None
    mqtt_tls_key_file: str | None = None

    broker_control_enabled: bool = False
    broker_control_encryption_key_file: str | None = None
    broker_control_encryption_key_id: str | None = None
    broker_control_admin_executable: str = "/usr/local/bin/nexolab-dynsec-admin"
    broker_control_admin_username: str | None = None
    broker_control_admin_client_id: str = "nexolab-broker-control-worker"
    broker_control_admin_password_file: str | None = None
    broker_control_poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.05,
        le=300.0,
    )
    broker_control_max_commands_per_run: int = Field(
        default=25,
        ge=1,
        le=1000,
    )
    broker_control_max_attempts: int = Field(default=8, ge=1, le=100)
    broker_control_retry_initial_seconds: float = Field(
        default=1.0,
        ge=0.05,
        le=3600.0,
    )
    broker_control_retry_max_seconds: float = Field(
        default=300.0,
        ge=0.05,
        le=86_400.0,
    )
    broker_control_command_timeout_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=300.0,
    )
    broker_control_stale_lock_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=86_400.0,
    )

    ingestion_queue_maxsize: int = Field(default=10_000, ge=1)
    ingestion_payload_max_bytes: int = Field(default=262_144, ge=1024)
    dead_letter_payload_max_bytes: int = Field(default=65_536, ge=256)
    ingestion_spool_enabled: bool = True
    ingestion_spool_path: str = "data/telemetry-ingestion/spool.db"
    ingestion_spool_max_records: int = Field(default=500_000, ge=1)
    ingestion_spool_max_bytes: int = Field(
        default=4 * 1024 * 1024 * 1024,
        ge=1024 * 1024,
    )
    ingestion_spool_busy_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=300.0,
    )
    ingestion_spool_poll_interval_seconds: float = Field(
        default=0.1,
        ge=0.01,
        le=10.0,
    )
    api_max_page_size: int = Field(default=1000, ge=1, le=1000)
    history_max_range_days: int = Field(default=31, ge=1, le=366)

    object_storage_backend: Literal["disabled", "s3"] = "disabled"
    object_storage_bucket: str = "nexolab-equipment-images"
    object_storage_endpoint_url: str | None = None
    object_storage_public_endpoint_url: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_force_path_style: bool = True
    equipment_image_max_bytes: int = Field(
        default=1536 * 1024,
        ge=1024,
        le=50 * 1024 * 1024,
    )
    equipment_image_signed_url_seconds: int = Field(
        default=900,
        ge=60,
        le=86_400,
    )

    auth_mode: Literal["disabled", "jwt"] = "disabled"
    auth_default_organization_id: str = (
        "00000000-0000-0000-0000-000000000001"
    )
    auth_jwt_public_key: str | None = None
    auth_jwt_jwks_url: str | None = None
    auth_jwt_algorithm: str = "RS256"
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None
    auth_jwt_provider: str = "oidc"

    cors_allowed_origins: str = ""
    cors_allow_credentials: bool = False

    websocket_client_queue_maxsize: int = Field(default=256, ge=1, le=10_000)
    websocket_heartbeat_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=300.0,
    )
    websocket_send_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
    )
    websocket_auth_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
    )
    websocket_resume_limit: int = Field(default=1000, ge=1, le=10_000)

    retention_enabled: bool = True
    telemetry_retention_days: int = Field(default=365, ge=1, le=3650)
    raw_payload_retention_days: int = Field(default=30, ge=1, le=3650)
    dead_letter_retention_days: int = Field(default=30, ge=1, le=3650)
    retention_interval_seconds: int = Field(default=3600, ge=60, le=86_400)
    retention_batch_size: int = Field(default=1000, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_runtime_secrets(self) -> "Settings":
        has_username = bool(self.mqtt_username and self.mqtt_username.strip())
        has_password_file = bool(
            self.mqtt_password_file and self.mqtt_password_file.strip()
        )
        if has_username != has_password_file:
            raise ValueError(
                "MQTT_USERNAME and MQTT_PASSWORD_FILE must be configured together"
            )
        if self.mqtt_auth_required and not has_username:
            raise ValueError(
                "MQTT credentials are required when MQTT_AUTH_REQUIRED=true"
            )

        tls_files = (
            self.mqtt_tls_ca_file,
            self.mqtt_tls_cert_file,
            self.mqtt_tls_key_file,
        )
        has_tls_files = any(value and value.strip() for value in tls_files)
        if not self.mqtt_tls_required and has_tls_files:
            raise ValueError("MQTT TLS files require MQTT_TLS_REQUIRED=true")
        if self.mqtt_tls_required and not (
            self.mqtt_tls_ca_file and self.mqtt_tls_ca_file.strip()
        ):
            raise ValueError(
                "MQTT_TLS_CA_FILE is required when MQTT_TLS_REQUIRED=true"
            )
        has_client_certificate = bool(
            self.mqtt_tls_cert_file and self.mqtt_tls_cert_file.strip()
        )
        has_client_key = bool(
            self.mqtt_tls_key_file and self.mqtt_tls_key_file.strip()
        )
        if has_client_certificate != has_client_key:
            raise ValueError(
                "MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE must be configured together"
            )

        if self.database_retry_max_seconds < self.database_retry_initial_seconds:
            raise ValueError(
                "DATABASE_RETRY_MAX_SECONDS must be greater than or equal to "
                "DATABASE_RETRY_INITIAL_SECONDS"
            )
        if not self.ingestion_spool_path.strip():
            raise ValueError("INGESTION_SPOOL_PATH must not be empty")
        if (
            self.broker_control_retry_max_seconds
            < self.broker_control_retry_initial_seconds
        ):
            raise ValueError(
                "BROKER_CONTROL_RETRY_MAX_SECONDS must be greater than or equal "
                "to BROKER_CONTROL_RETRY_INITIAL_SECONDS"
            )
        if (
            self.broker_control_stale_lock_seconds
            <= self.broker_control_command_timeout_seconds
        ):
            raise ValueError(
                "BROKER_CONTROL_STALE_LOCK_SECONDS must be greater than "
                "BROKER_CONTROL_COMMAND_TIMEOUT_SECONDS"
            )
        if self.broker_control_enabled:
            required = {
                "BROKER_CONTROL_ENCRYPTION_KEY_FILE": (
                    self.broker_control_encryption_key_file
                ),
                "BROKER_CONTROL_ENCRYPTION_KEY_ID": (
                    self.broker_control_encryption_key_id
                ),
                "BROKER_CONTROL_ADMIN_EXECUTABLE": (
                    self.broker_control_admin_executable
                ),
                "BROKER_CONTROL_ADMIN_USERNAME": (
                    self.broker_control_admin_username
                ),
                "BROKER_CONTROL_ADMIN_CLIENT_ID": (
                    self.broker_control_admin_client_id
                ),
                "BROKER_CONTROL_ADMIN_PASSWORD_FILE": (
                    self.broker_control_admin_password_file
                ),
            }
            missing = [
                name
                for name, value in required.items()
                if value is None or not str(value).strip()
            ]
            if missing:
                raise ValueError(
                    "broker control is enabled but required settings are missing: "
                    + ", ".join(sorted(missing))
                )
        return self

    @property
    def parsed_cors_allowed_origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def resolved_mqtt_topic(self) -> str:
        return (
            self.mqtt_node_topic_filter
            if self.mqtt_node_registry_enforced
            else self.mqtt_topic
        )

    @property
    def resolved_mqtt_topics(self) -> tuple[str, ...]:
        if not self.mqtt_node_registry_enforced:
            return (self.mqtt_topic,)
        return (
            self.mqtt_node_topic_filter,
            self.mqtt_node_health_topic_filter,
            self.mqtt_node_status_topic_filter,
        )

    @property
    def resolved_auth_jwt_public_key(self) -> str | None:
        if self.auth_jwt_public_key is None:
            return None
        return self.auth_jwt_public_key.replace("\\n", "\n")
