"""Tests for request/job correlation and observability guards."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.logging import CorrelationIdFilter, sanitize_log_value, set_correlation_id, reset_correlation_id
from app.main import app
from app.models import Base, ExecutionJob, Submission
from app.schemas.execution import ExecutionResult
from app.services.execution_worker import ExecutionWorker


def test_settings_log_level_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATACSS_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.log_level == "DEBUG"


def test_request_correlation_id_is_returned_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with TestClient(app) as client:
        with caplog.at_level(logging.INFO):
            response = client.get(
                "/health",
                headers={"X-Correlation-ID": "request-123"},
            )
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "request-123"
    assert any(record.correlation_id == "request-123" for record in caplog.records)


def test_secret_redaction_removes_sensitive_tokens() -> None:
    payload = "Authorization: Bearer abc.def.ghi password=super-secret token=jwt-value secret=topsecret"
    cleaned = sanitize_log_value(payload)
    assert "super-secret" not in cleaned
    assert "abc.def.ghi" not in cleaned
    assert "[REDACTED]" in cleaned
    assert "topsecret" not in cleaned


def test_log_filter_sets_correlation_id_for_records() -> None:
    filter_ = CorrelationIdFilter()
    token = set_correlation_id("job-42")
    try:
        record = logging.LogRecord(
            name="app.services.worker",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert filter_.filter(record) is True
        assert record.correlation_id == "job-42"
    finally:
        reset_correlation_id(token)


@pytest.fixture
def worker_database() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def setup() -> async_sessionmaker[AsyncSession]:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(setup())


def test_worker_logs_include_job_correlation(
    worker_database: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def prepare() -> None:
        async with worker_database() as session:
            submission = Submission(
                interview_session_id=uuid4(),
                question_id=uuid4(),
                language="python",
                source_code="print('ok')",
                stdin="",
                status="queued",
            )
            session.add(submission)
            await session.flush()
            session.add(
                ExecutionJob(
                    submission_id=submission.id,
                    status="queued",
                    attempt_count=0,
                )
            )
            await session.commit()

            service = type("Service", (), {})()
            service.execute = lambda **kwargs: ExecutionResult(
                status="success",
                stdout="ok\n",
                exit_code=0,
                execution_time_ms=4,
            )
            worker = ExecutionWorker(service)
            with caplog.at_level(logging.INFO, logger="app.services.execution_worker"):
                assert await worker.process_next_job(session) is True
            assert any(
                getattr(record, "event", "") == "job_started"
                and getattr(record, "correlation_id", "")
                for record in caplog.records
            )

    asyncio.run(prepare())
