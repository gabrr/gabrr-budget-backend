from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_CORS_ORIGINS = ",".join(
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str
    app_env: Literal["local", "production"] = "local"
    cors_origins: str = LOCAL_CORS_ORIGINS
    default_account_id: str = "acct_demo_checking"
    max_file_upload_mb: int = Field(default=20, ge=1, le=512)

    # Supabase Auth settings used to authenticate browser requests.
    supabase_url: str = "https://bptkqiftccwgsmwlpahv.supabase.co"
    supabase_jwt_audience: str = "authenticated"
    allowed_user_email: str = "g.webdevelopr@gmail.com"

    # Remote agent settings used by the backend Agent Gateway.
    agent_base_url: str = "http://127.0.0.1:8001"
    agent_auth_mode: Literal["none", "google"] = "none"
    adk_app_name: str = "app"
    agent_timeout_seconds: float = Field(default=300.0, gt=0)

    @property
    def parsed_cors_origins(self) -> list[str]:
        return list(
            dict.fromkeys(
                origin.strip()
                for origin in self.cors_origins.split(",")
                if origin.strip()
            )
        )

    @property
    def max_file_upload_bytes(self) -> int:
        return self.max_file_upload_mb * 1024 * 1024

    @property
    def supabase_jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_jwt_issuer}/.well-known/jwks.json"

    @model_validator(mode="after")
    def require_production_configuration(self) -> "Settings":
        if self.app_env != "production":
            return self

        if "cors_origins" not in self.model_fields_set or not self.parsed_cors_origins:
            raise ValueError("CORS_ORIGINS must be explicitly configured in production")

        if "supabase_url" not in self.model_fields_set or not self.supabase_url.strip():
            raise ValueError("SUPABASE_URL must be explicitly configured in production")

        if "allowed_user_email" not in self.model_fields_set or not self.allowed_user_email.strip():
            raise ValueError("ALLOWED_USER_EMAIL must be explicitly configured in production")

        return self


settings = Settings()
