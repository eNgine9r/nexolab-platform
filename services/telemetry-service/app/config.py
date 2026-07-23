from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, field_validator
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
    mqtt_client_id: str = "nexolab-telemetry-ingestion"
    mqtt_keepalive_seconds: int = Field(default=60, ge=10, le=3600)
    mqtt_qos: int = Field(default=1, ge=0, le=2)

    ingestion_queue_maxsize: int = Field(default=10_000, ge=1)
    ingestion_payload_max_bytes: int = Field(default=262_144, ge=1024)
    dead_letter_payload_max_bytes: int = Field(default=65_536, ge=256)
    api_max_page_size: int = Field(default=1000, ge=1, le=1000)
    history_max_range_days: int = Field(default=31, ge=1, le=366)
    cors_allowed_origins: str = ""

    websocket_client_queue_maxsize: int = Field(default=256, ge=1, le=10_000)
    websocket_heartbeat_seconds: float = Field(default=20.0, ge=1.0, le=300.0)
    websocket_send_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    websocket_resume_limit: int = Field(default=1000, ge=1, le=10_000)

    retention_enabled: bool = True
    telemetry_retention_days: int = Field(default=365, ge=1, le=3650)
    raw_payload_retention_days: int = Field(default=30, ge=1, le=3650)
    dead_letter_retention_days: int = Field(default=30, ge=1, le=3650)
    retention_interval_seconds: int = Field(default=3600, ge=60, le=86_400)
    retention_batch_size: int = Field(default=1000, ge=1, le=100_000)

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        for origin in cls._split_origins(value):
            parsed = urlparse(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must contain comma-separated HTTP(S) origins"
                )
        return value

    def cors_origins(self) -> list[str]:
        return self._split_origins(self.cors_allowed_origins)

    @staticmethod
    def _split_origins(value: str) -> list[str]:
        return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
