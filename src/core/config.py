from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Constants
    max_sessions_per_poll: int = 5
    context_distance_threshold: float = 0.40
    bdd_retry_delay_seconds: int = 30
    bdd_max_retries: int = 5
    bdd_split_features: bool = False
    bdd_feature_similarity_threshold: float = 0.42
    bdd_singleton_merge_threshold: float = 0.25

    # Application
    app_name: str = "DocGen"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # External Services
    redis_url: str = "redis://redis:6379"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_password: str = "password"
    neo4j_username: str = "neo4j"

    poller_cron_hours: str = "0,4,8,12,16,20"
    poller_cron_minutes: str = "0"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000"]


# The @lru_cache decorator ensures settings are loaded once and reused — no repeated file reads or environment lookups on every request.
@lru_cache
def get_settings() -> Settings:
    return Settings()
