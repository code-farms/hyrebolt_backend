from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Values that only ever appear in examples/templates; refused in production.
_PLACEHOLDER_SECRET_MARKERS = ("change-me", "changeme", "example", "placeholder", "replace")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str
    redis_url: str
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    # Auth. HS256 needs a secret at least as long as its 256-bit output to be
    # worth anything; a short or template value makes every token forgeable.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    auth_rate_limit_per_minute: int = 10

    # Hardening (Phase 18). LLM-backed routes share one per-IP budget; JSON
    # bodies above the cap are rejected before parsing (uploads stream
    # separately under RESUME_MAX_UPLOAD_MB).
    ai_rate_limit_per_minute: int = 30
    max_request_body_bytes: int = 1_048_576
    # Comma-separated reverse-proxy IPs whose X-Forwarded-For is trusted;
    # read by uvicorn (--proxy-headers) so rate limits see the real client.
    forwarded_allow_ips: str = "127.0.0.1"

    # Discovery
    discovery_source_timeout_seconds: float = 60.0  # whole per-source task incl. retries
    discovery_retry_attempts: int = 3
    discovery_retry_base_delay_seconds: float = 1.0  # 0 => instant retries (tests)
    discovery_retry_max_delay_seconds: float = 30.0
    discovery_retry_jitter_seconds: float = 0.5  # 0 => deterministic (tests)
    discovery_max_jobs_per_source: int = 50
    search_rate_limit_per_minute: int = 5

    # Deduplication (Phase 6): fuzzy scoring on same-company candidates.
    dedup_auto_merge_threshold: float = 0.85
    dedup_link_threshold: float = 0.65
    # Title gate: candidates whose title similarity is below this can never be
    # duplicates/near-duplicates, no matter how alike the boilerplate is.
    dedup_min_title_similarity: float = 0.5
    dedup_max_candidates: int = 50
    dedup_weight_title: float = 0.45
    dedup_weight_description: float = 0.30
    dedup_weight_location: float = 0.15
    dedup_weight_posted_date: float = 0.10

    # Daily agent (Phase 9). Timezone-aware schedule; IST default.
    daily_search_time: str = "08:00"  # HH:MM in `timezone`
    timezone: str = "Asia/Kolkata"
    max_daily_results: int = 10
    min_match_score: float = 60.0
    agent_analyze_batch: int = 100
    agent_match_batch: int = 200

    # Notifications (Phase 10). Email/Telegram are env-gated: a channel is
    # available only when its flag is true AND its credentials are set.
    # In-app (bell) notifications are always on.
    email_notifications_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None
    telegram_notifications_enabled: bool = False
    telegram_bot_token: str | None = None

    # Matching (Phase 8): spec weight table, configurable.
    match_weight_role: float = 0.25
    match_weight_skills: float = 0.25
    match_weight_experience: float = 0.15
    match_weight_location: float = 0.10
    match_weight_salary: float = 0.10
    match_weight_work_mode: float = 0.05
    match_weight_industry: float = 0.05
    match_weight_company: float = 0.05
    match_weight_watchlist: float = 0.10  # Phase 13 watchlist component
    match_batch_limit: int = 50

    # Resumes (Phase 14): originals on local disk, extracted text in the DB.
    resume_storage_dir: str = "data/resumes"
    resume_max_upload_mb: int = 5
    resume_max_text_chars: int = 30000
    resume_extract_timeout_seconds: float = 20.0
    resume_upload_rate_limit_per_minute: int = 10

    # Application assistant (Phase 15): each generate/regenerate is one request.
    assistant_rate_limit_per_minute: int = 20

    # Personalised ranking (Phase 16). The feed re-ranks this many top base-score
    # candidates in Python; every adjustment below is a capped, explainable delta
    # on the 0-100 deterministic match score.
    ranking_candidate_limit: int = 300
    ranking_preference_cap: float = 15.0
    ranking_freshness_cap: float = 6.0
    ranking_company_boost_cap: float = 5.0
    ranking_company_penalty: float = 10.0
    ranking_feedback_boost_cap: float = 5.0
    ranking_feedback_penalty: float = 15.0
    ranking_role_hide_similarity: float = 0.75

    # Analytics (Phase 17). A job counts as "relevant"/"matched" when the user's
    # match score reaches this (75 = STRONG_MATCH band); company table row cap.
    analytics_relevant_min_score: float = 75.0
    analytics_company_limit: int = 10

    # AI (Phase 7). Default "mock": no API key needed in dev/tests.
    llm_provider: Literal["mock", "openai"] = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_retry_base_delay_seconds: float = 1.0  # 0 => instant retries (tests)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list) and any(origin == "*" for origin in value):
            # Starlette echoes the request Origin for "*" + credentials, which
            # would turn every authenticated endpoint into a cross-site read.
            raise ValueError("CORS_ORIGINS must list explicit origins; '*' is not allowed")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def check_production_hardening(self) -> "Settings":
        if not self.is_production:
            return self
        lowered = self.jwt_secret.lower()
        if any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS):
            raise ValueError("JWT_SECRET looks like a placeholder; generate one with openssl rand -hex 32")
        insecure = [origin for origin in self.cors_origins if not origin.startswith("https://")]
        if insecure:
            raise ValueError(f"CORS_ORIGINS must be https:// in production: {insecure}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
