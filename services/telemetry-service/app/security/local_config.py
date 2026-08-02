from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LocalAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    auth_local_enabled: bool = False
    auth_local_private_key_file: str | None = None
    auth_local_public_key_file: str | None = None
    auth_local_issuer: str = "urn:nexolab:local"
    auth_local_audience: str = "nexolab-api"
    auth_local_provider: str = "nexolab-local"
    auth_local_access_token_seconds: int = Field(default=300, ge=60, le=3600)
    auth_local_refresh_token_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    auth_local_max_failed_attempts: int = Field(default=5, ge=3, le=20)
    auth_local_lockout_seconds: int = Field(default=300, ge=30, le=86_400)

    @model_validator(mode="after")
    def validate_local_auth(self) -> "LocalAuthSettings":
        if not self.auth_local_enabled:
            return self
        required = {
            "AUTH_LOCAL_PRIVATE_KEY_FILE": self.auth_local_private_key_file,
            "AUTH_LOCAL_PUBLIC_KEY_FILE": self.auth_local_public_key_file,
            "AUTH_LOCAL_ISSUER": self.auth_local_issuer,
            "AUTH_LOCAL_AUDIENCE": self.auth_local_audience,
            "AUTH_LOCAL_PROVIDER": self.auth_local_provider,
        }
        missing = [
            name
            for name, value in required.items()
            if value is None or not str(value).strip()
        ]
        if missing:
            raise ValueError(
                "local authentication is enabled but required settings are missing: "
                + ", ".join(sorted(missing))
            )
        if self.auth_local_provider.strip() != "nexolab-local":
            raise ValueError("AUTH_LOCAL_PROVIDER must be nexolab-local")
        return self
