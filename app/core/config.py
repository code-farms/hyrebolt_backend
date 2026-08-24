from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str
    redis_url: str
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    # Auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    auth_rate_limit_per_minute: int = 10

    # Discovery
    discovery_source_timeout_seconds: float = 60.0  # whole per-source task incl. retries
    discovery_retry_attempts: int = 3
    discovery_retry_base_delay_seconds: float = 1.0  # 0 => instant retries (tests)
    discovery_retry_max_delay_seconds: float = 30.0
    discovery_retry_jitter_seconds: float = 0.5  # 0 => deterministic (tests)
    discovery_max_jobs_per_source: int = 50
    search_rate_limit_per_minute: int = 5

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
