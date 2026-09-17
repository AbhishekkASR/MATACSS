"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}

load_dotenv(ROOT / ".env", override=False)
if (os.getenv("APP_ENV") or "development").lower() == "production":
    load_dotenv(ROOT / ".env.production", override=False)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_value(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _parse_origins(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(
        origin.strip()
        for origin in raw.split(",")
        if origin and origin.strip()
    )


def _mask_secret(value: str | None) -> str:
    if not value:
        return "***"
    return "***"


def _mask_database_url(value: str | None) -> str:
    if not value:
        return ""
    if "://" not in value:
        return value
    scheme, rest = value.split("://", 1)
    if "@" in rest:
        userinfo, endpoint = rest.rsplit("@", 1)
        if ":" in userinfo:
            username, _ = userinfo.split(":", 1)
            return f"{scheme}://{username}:***@{endpoint}"
        return f"{scheme}://***@{endpoint}"
    return value


@dataclass(frozen=True, init=False)
class Settings:
    """Centralized application settings with production validation."""

    app_env: str
    debug: bool
    app_title: str
    app_description: str
    app_version: str
    frontend_origins: tuple[str, ...]
    api_host: str
    api_port: int
    database_url: str
    database_pool_size: int
    database_max_overflow: int
    worker_poll_interval_seconds: int
    worker_batch_size: int
    worker_max_concurrency: int
    worker_max_retries: int
    sandbox_python_image: str
    sandbox_cpp_image: str
    sandbox_java_image: str
    sandbox_timeout_seconds: float
    sandbox_memory_limit: str
    sandbox_cpu_limit: float
    sandbox_pids_limit: int
    sandbox_output_limit_bytes: int
    jwt_secret: str
    jwt_algorithm: str
    jwt_expire_minutes: int
    log_level: str

    def __init__(self) -> None:
        app_env = (os.getenv("APP_ENV") or "development").strip().lower()
        debug = _parse_bool(os.getenv("DEBUG"), app_env != "production")
        frontend_origins = _parse_origins(
            os.getenv("MATACSS_FRONTEND_ORIGINS") or os.getenv("MATACSS_CORS_ALLOWED_ORIGINS")
        )
        if not frontend_origins and app_env != "production":
            frontend_origins = ("http://127.0.0.1:3000", "http://localhost:3000")
        api_host = _env_value("MATACSS_API_HOST", "0.0.0.0")
        api_port = int(_env_value("MATACSS_API_PORT", "8000"))
        database_url = _env_value(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./matacss.db",
        )
        database_pool_size = int(_env_value("DATABASE_POOL_SIZE", "5"))
        database_max_overflow = int(_env_value("DATABASE_MAX_OVERFLOW", "10"))
        worker_poll_interval_seconds = int(_env_value("MATACSS_WORKER_POLL_INTERVAL_SECONDS", "5"))
        worker_batch_size = int(_env_value("MATACSS_WORKER_BATCH_SIZE", "10"))
        worker_max_concurrency = int(_env_value("MATACSS_WORKER_MAX_CONCURRENCY", "1"))
        worker_max_retries = int(_env_value("MATACSS_WORKER_MAX_RETRIES", "3"))
        sandbox_python_image = _env_value("MATACSS_SANDBOX_PYTHON_IMAGE", "python:3.12-alpine")
        sandbox_cpp_image = _env_value("MATACSS_SANDBOX_CPP_IMAGE", "gcc:14-bookworm")
        sandbox_java_image = _env_value("MATACSS_SANDBOX_JAVA_IMAGE", "eclipse-temurin:21-jdk")
        sandbox_timeout_seconds = float(_env_value("MATACSS_SANDBOX_TIMEOUT_SECONDS", "5"))
        sandbox_memory_limit = _env_value("MATACSS_SANDBOX_MEMORY_LIMIT", "128m")
        sandbox_cpu_limit = float(_env_value("MATACSS_SANDBOX_CPU_LIMIT", "0.5"))
        sandbox_pids_limit = int(_env_value("MATACSS_SANDBOX_PIDS_LIMIT", "64"))
        sandbox_output_limit_bytes = int(_env_value("MATACSS_SANDBOX_OUTPUT_LIMIT_BYTES", "65536"))
        jwt_secret = _env_value("MATACSS_JWT_SECRET", "")
        jwt_algorithm = _env_value("MATACSS_JWT_ALGORITHM", "HS256").strip().upper()
        if jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                "MATACSS_JWT_ALGORITHM must be one of HS256, HS384, or HS512."
            )
        jwt_expire_minutes = int(_env_value("MATACSS_JWT_EXPIRE_MINUTES", "60"))
        log_level = _env_value("MATACSS_LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            log_level = "INFO"

        object.__setattr__(self, "app_env", app_env)
        object.__setattr__(self, "debug", debug)
        object.__setattr__(self, "app_title", _env_value("MATACSS_APP_TITLE", "MATACSS Backend"))
        object.__setattr__(
            self,
            "app_description",
            _env_value(
                "MATACSS_APP_DESCRIPTION",
                "Backend foundation for the Multi-Agent Technical Assessment & Code Sandboxing System.",
            ),
        )
        object.__setattr__(self, "app_version", _env_value("MATACSS_APP_VERSION", "0.1.0"))
        object.__setattr__(self, "frontend_origins", self._normalize_origins(frontend_origins))
        object.__setattr__(self, "api_host", api_host.strip())
        object.__setattr__(self, "api_port", api_port)
        object.__setattr__(self, "database_url", database_url.strip())
        object.__setattr__(self, "database_pool_size", database_pool_size)
        object.__setattr__(self, "database_max_overflow", database_max_overflow)
        object.__setattr__(self, "worker_poll_interval_seconds", worker_poll_interval_seconds)
        object.__setattr__(self, "worker_batch_size", worker_batch_size)
        object.__setattr__(self, "worker_max_concurrency", worker_max_concurrency)
        object.__setattr__(self, "worker_max_retries", worker_max_retries)
        object.__setattr__(self, "sandbox_python_image", sandbox_python_image)
        object.__setattr__(self, "sandbox_cpp_image", sandbox_cpp_image)
        object.__setattr__(self, "sandbox_java_image", sandbox_java_image)
        object.__setattr__(self, "sandbox_timeout_seconds", sandbox_timeout_seconds)
        object.__setattr__(self, "sandbox_memory_limit", sandbox_memory_limit)
        object.__setattr__(self, "sandbox_cpu_limit", sandbox_cpu_limit)
        object.__setattr__(self, "sandbox_pids_limit", sandbox_pids_limit)
        object.__setattr__(self, "sandbox_output_limit_bytes", sandbox_output_limit_bytes)
        object.__setattr__(self, "jwt_secret", jwt_secret.strip())
        object.__setattr__(self, "jwt_algorithm", jwt_algorithm)
        object.__setattr__(self, "jwt_expire_minutes", jwt_expire_minutes)
        object.__setattr__(self, "log_level", log_level)

        if self.app_env == "production":
            self._validate_production()
        else:
            self._validate_local()

    @staticmethod
    def _normalize_origins(origins: tuple[str, ...] | list[str] | str | None) -> tuple[str, ...]:
        if origins is None:
            return ()
        if isinstance(origins, str):
            items = _parse_origins(origins)
        else:
            items = tuple(str(origin).strip() for origin in origins if str(origin).strip())
        return tuple(dict.fromkeys(items))

    def _validate_local(self) -> None:
        if self.app_env == "production":
            return
        if self.api_port <= 0:
            raise ValueError("MATACSS_API_PORT must be a positive integer.")
        if self.worker_poll_interval_seconds <= 0:
            raise ValueError("MATACSS_WORKER_POLL_INTERVAL_SECONDS must be positive.")
        if self.worker_batch_size <= 0:
            raise ValueError("MATACSS_WORKER_BATCH_SIZE must be positive.")
        if self.worker_max_concurrency <= 0:
            raise ValueError("MATACSS_WORKER_MAX_CONCURRENCY must be positive.")
        if self.jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError("MATACSS_JWT_ALGORITHM must be one of HS256, HS384, or HS512.")
        if not self.frontend_origins:
            object.__setattr__(self, "frontend_origins", ("http://127.0.0.1:3000", "http://localhost:3000"))

    def _validate_production(self) -> None:
        if not self.database_url:
            raise ValueError("DATABASE_URL is required in production.")
        if "sqlite" in self.database_url.lower():
            raise ValueError("Production requires a PostgreSQL or other non-SQLite DATABASE_URL.")
        if "change_me" in self.database_url.lower():
            raise ValueError("Production DATABASE_URL contains an insecure placeholder value.")
        if "change_me" in self.jwt_secret.lower() or "example" in self.jwt_secret.lower():
            raise ValueError("MATACSS_JWT_SECRET must be set to a strong production value.")
        if len(self.jwt_secret) < 32:
            raise ValueError("MATACSS_JWT_SECRET must be at least 32 characters in production.")
        if not self.frontend_origins or any(origin == "*" for origin in self.frontend_origins):
            raise ValueError("Production CORS origins must be explicit and not wildcard.")
        if not self.jwt_algorithm:
            raise ValueError("MATACSS_JWT_ALGORITHM must be configured for production.")
        if self.jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError("MATACSS_JWT_ALGORITHM must be one of HS256, HS384, or HS512 in production.")
        if self.api_port <= 0:
            raise ValueError("MATACSS_API_PORT must be a positive integer in production.")
        if self.worker_poll_interval_seconds <= 0:
            raise ValueError("MATACSS_WORKER_POLL_INTERVAL_SECONDS must be positive in production.")
        if self.worker_batch_size <= 0:
            raise ValueError("MATACSS_WORKER_BATCH_SIZE must be positive in production.")
        if self.worker_max_concurrency <= 0:
            raise ValueError("MATACSS_WORKER_MAX_CONCURRENCY must be positive in production.")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def redacted_database_url(self) -> str:
        return _mask_database_url(self.database_url)

    @property
    def redacted_jwt_secret(self) -> str:
        return _mask_secret(self.jwt_secret)

    def __repr__(self) -> str:
        return (
            "Settings("
            f"app_env={self.app_env!r}, debug={self.debug!r}, "
            f"database_url={self.redacted_database_url!r}, "
            f"frontend_origins={self.frontend_origins!r}, "
            f"api_host={self.api_host!r}, api_port={self.api_port!r}, "
            f"jwt_secret={self.redacted_jwt_secret!r})"
        )

    __str__ = __repr__


settings = Settings()
