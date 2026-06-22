from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Constants
    max_sessions_per_poll: int = 5
    context_distance_threshold: float = 0.40
    bdd_retry_delay_seconds: int = 30
    bdd_max_retries: int = 5
    bdd_split_features: bool = False
    bdd_feature_similarity_threshold: float = 0.42
    bdd_singleton_merge_threshold: float = 0.25
    semantic_assertions_enabled: bool = False
    semantic_assertions_provider: str = "gemini"
    semantic_assertions_model_base_url: str = "http://localhost:8000/v1"
    semantic_assertions_model_name: str = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    semantic_assertions_gemini_model: str = "gemini-2.5-flash-lite"
    semantic_assertions_timeout_seconds: int = 20
    semantic_assertions_max_assertions_per_scenario: int = 2
    semantic_assertions_min_confidence: float = 0.65
    semantic_assertions_html_summary_max_chars: int = 12000
    video_retry_delay_seconds: int = 30
    video_max_retries: int = 5
    video_output_dir: str = "artifacts/videos"
    video_default_width: int = 1280
    video_default_height: int = 720
    video_default_fps: int = 30
    video_action_speed: float = 0.1
    video_random_seed: int = 42
    jira_report_poll_batch_size: int = 3

    # Application
    app_name: str = "DocGen"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # External Services
    redis_url: str = "redis://redis:6379"
    api_base_url: str = "http://localhost:3000/api/v1"
    internal_service_token: str = ""
    gemini_api_key: str = "AIzaSyD__8pzxbF02FoswxBcdDsBKOm-PHTUpAQ"
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_password: str = "password"
    neo4j_username: str = "neo4j"

    poller_cron_hours: str = "0,4,8,12,16,20"
    poller_cron_minutes: str = "0"
    jira_report_cron_minutes: str = None

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000"]


# The @lru_cache decorator ensures settings are loaded once and reused — no repeated file reads or environment lookups on every request.
@lru_cache
def get_settings() -> Settings:
    return Settings()
