from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "DocGen"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # Database
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "postgres"

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/coverit?schema=public"

    # External Services
    redis_url: str = "redis://redis:6379"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000"]


# The @lru_cache decorator ensures settings are loaded once and reused — no repeated file reads or environment lookups on every request.
@lru_cache
def get_settings() -> Settings:
    return Settings()
