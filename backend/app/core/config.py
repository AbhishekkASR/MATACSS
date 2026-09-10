"""Application configuration."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    """Minimal application settings loaded from environment variables."""

    app_title: str = os.getenv("MATACSS_APP_TITLE", "MATACSS Backend")
    app_description: str = os.getenv(
        "MATACSS_APP_DESCRIPTION",
        "Backend foundation for the Multi-Agent Technical Assessment & Code Sandboxing System.",
    )
    app_version: str = os.getenv("MATACSS_APP_VERSION", "0.1.0")
    frontend_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "MATACSS_FRONTEND_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000",
        ).split(",")
        if origin.strip()
    )
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://localhost/matacss"
    )
    database_pool_size: int = int(os.getenv("DATABASE_POOL_SIZE", "5"))
    database_max_overflow: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))
    sandbox_python_image: str = os.getenv(
        "MATACSS_SANDBOX_PYTHON_IMAGE", "python:3.12-alpine"
    )
    sandbox_cpp_image: str = os.getenv(
        "MATACSS_SANDBOX_CPP_IMAGE", "gcc:14-bookworm"
    )
    sandbox_java_image: str = os.getenv(
        "MATACSS_SANDBOX_JAVA_IMAGE", "eclipse-temurin:21-jdk"
    )
    sandbox_timeout_seconds: float = float(
        os.getenv("MATACSS_SANDBOX_TIMEOUT_SECONDS", "5")
    )
    sandbox_memory_limit: str = os.getenv("MATACSS_SANDBOX_MEMORY_LIMIT", "128m")
    sandbox_cpu_limit: float = float(os.getenv("MATACSS_SANDBOX_CPU_LIMIT", "0.5"))
    sandbox_pids_limit: int = int(os.getenv("MATACSS_SANDBOX_PIDS_LIMIT", "64"))
    sandbox_output_limit_bytes: int = int(
        os.getenv("MATACSS_SANDBOX_OUTPUT_LIMIT_BYTES", "65536")
    )


settings = Settings()
