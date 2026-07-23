from __future__ import annotations

from pydantic import Field
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
    auto_create_schema: bool = False

    mqtt_enabled: bool = True
    mqtt_host: str = "mqtt"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_topic: str = "nexolab/telemetry"
    mqtt_client_id: str = "nexolab-telemetry-ingestion"
    mqtt_keepalive_seconds: int = Field(default=60, ge=10, le=3600)
    mqtt_qos: int = Field(default=1, ge=0, le=2)

    ingestion_queue_maxsize: int = Field(default=10_000, ge=1)
    api_max_page_size: int = Field(default=1000, ge=1, le=1000)
    history_max_range_days: int = Field(default=31, ge=1, le=366)

    websocket_client_queue_maxsize: int = Field(default=256, ge=1, le=10_000)
    websocket_heartbeat_seconds: float = Field(default=20.0, ge=1.0, le=300.0)
    websocket_send_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    websocket_resume_limit: int = Field(default=1000, ge=1, le=10_000)
