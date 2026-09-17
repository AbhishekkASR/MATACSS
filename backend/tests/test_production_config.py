"""Tests for environment-driven production configuration validation."""

from __future__ import annotations

import pytest

import app.core.config as config


def test_production_requires_strong_secret_and_explicit_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://matacss_user:StrongPassword@prod-db.example.com:5432/matacss",
    )
    monkeypatch.setenv("MATACSS_FRONTEND_ORIGINS", "*")
    monkeypatch.delenv("MATACSS_JWT_SECRET", raising=False)

    with pytest.raises(ValueError, match="MATACSS_JWT_SECRET"):
        config.Settings()


def test_production_rejects_unsafe_jwt_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod-db.example.com:5432/matacss")
    monkeypatch.setenv("MATACSS_JWT_SECRET", "a-very-strong-production-secret-1234567890")
    monkeypatch.setenv("MATACSS_FRONTEND_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("MATACSS_JWT_ALGORITHM", "none")

    with pytest.raises(ValueError, match="HS256|HS384|HS512"):
        config.Settings()


def test_production_accepts_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://matacss_user:StrongPassword@prod-db.example.com:5432/matacss",
    )
    monkeypatch.setenv("MATACSS_JWT_SECRET", "a-very-strong-production-secret-1234567890")
    monkeypatch.setenv("MATACSS_FRONTEND_ORIGINS", "https://app.example.com,https://admin.example.com")

    settings = config.Settings()
    assert settings.is_production is True
    assert settings.debug is False
    assert settings.frontend_origins == ("https://app.example.com", "https://admin.example.com")


def test_local_dev_uses_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("MATACSS_FRONTEND_ORIGINS", raising=False)
    monkeypatch.delenv("MATACSS_CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("MATACSS_JWT_SECRET", raising=False)

    settings = config.Settings()
    assert settings.app_env == "development"
    assert settings.debug is True
    assert settings.frontend_origins == ("http://127.0.0.1:3000", "http://localhost:3000")


def test_cors_parsing_and_alias_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MATACSS_CORS_ALLOWED_ORIGINS", " https://a.example.com, , https://b.example.com ")
    monkeypatch.delenv("MATACSS_FRONTEND_ORIGINS", raising=False)

    settings = config.Settings()
    assert settings.frontend_origins == ("https://a.example.com", "https://b.example.com")


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://admin:super-secret-password@db.example.com:5432/matacss")
    monkeypatch.setenv("MATACSS_JWT_SECRET", "super-secret-key-123456")

    settings = config.Settings()
    rendered = repr(settings)
    assert "super-secret-password" not in rendered
    assert "super-secret-key-123456" not in rendered
    assert "***" in rendered


def test_environment_overrides_apply_to_api_and_worker_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MATACSS_API_HOST", "127.0.0.1")
    monkeypatch.setenv("MATACSS_API_PORT", "9000")
    monkeypatch.setenv("MATACSS_WORKER_POLL_INTERVAL_SECONDS", "11")
    monkeypatch.setenv("MATACSS_WORKER_BATCH_SIZE", "25")
    monkeypatch.setenv("MATACSS_WORKER_MAX_RETRIES", "7")

    settings = config.Settings()
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 9000
    assert settings.worker_poll_interval_seconds == 11
    assert settings.worker_batch_size == 25
    assert settings.worker_max_retries == 7
