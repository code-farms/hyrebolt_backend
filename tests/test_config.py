import pytest

from app.core.config import Settings


def test_settings_loads_required_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings()

    assert settings.database_url == "postgresql://user:pass@localhost:5432/db"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.environment == "development"


def test_settings_splits_comma_separated_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")

    settings = Settings()

    assert settings.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
