"""PostgreSQL integration checks, skipped unless DATABASE_URL is configured."""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.postgres


def test_postgres_connection() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL DATABASE_URL is not configured")

    async def check() -> None:
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
        await engine.dispose()

    try:
        asyncio.run(check())
    except Exception as exc:
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
