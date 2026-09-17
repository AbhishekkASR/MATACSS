"""Tests for durable asynchronous submission execution."""

import asyncio
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncGenerator
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.submissions import get_sandbox_service
from app.core.database import get_db_session
from app.main import app
from app.models import Base, ExecutionJob, Submission
from app.schemas.execution import ExecutionResult
from app.services.execution_worker import process_next_execution_job
from app.services.execution_worker import ExecutionWorker
from app.services.execution_queue import find_stale_running_jobs, mark_stale_running_jobs


@pytest.fixture(scope="module")
def database() -> async_sessionmaker[AsyncSession]:
    async def setup() -> async_sessionmaker[AsyncSession]:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(setup())


@pytest.fixture
def sandbox_service() -> Mock:
    service = Mock()
    service.execute.return_value = ExecutionResult(
        status="success",
        stdout="done\n",
        exit_code=0,
        execution_time_ms=2,
    )
    app.dependency_overrides[get_sandbox_service] = lambda: lambda: service
    yield service
    app.dependency_overrides.pop(get_sandbox_service, None)


@pytest.fixture
def client(database, sandbox_service: Mock) -> TestClient:
    async def override() -> AsyncGenerator:
        async with database() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_session, None)


def context(client: TestClient) -> tuple[dict, dict]:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Job Candidate", "email": f"{uuid4()}@example.com"},
    ).json()
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate["candidate_id"]}
    ).json()
    question = client.post(
        "/api/v1/questions",
        json={
            "title": f"Job Question {uuid4()}",
            "description": "Execute",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    assert client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions",
        json={"question_id": question["question_id"], "sequence_number": 1},
    ).status_code == 201
    return interview, question


def test_submission_is_queued_without_docker_execution(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print('done')",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_status"] == "queued"
    sandbox_service.execute.assert_not_called()

    status = client.get(f"/api/v1/submissions/{body['submission_id']}/status")
    assert status.status_code == 200
    assert status.json()["job_status"] == "queued"
    assert status.json()["submission_status"] == "queued"


def test_worker_processes_job_and_status_becomes_terminal(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print('done')",
        },
    ).json()

    async def process() -> int:
        async with database() as session:
            processed = 0
            while await process_next_execution_job(session, sandbox_service):
                processed += 1
                current = await session.scalar(
                    select(Submission).where(
                        Submission.id == UUID(submission["submission_id"])
                    )
                )
                if current is not None and current.status != "queued":
                    break
            return processed

    assert asyncio.run(process()) >= 1
    assert sandbox_service.execute.call_count >= 1
    status = client.get(f"/api/v1/submissions/{submission['submission_id']}/status")
    assert status.json()["job_status"] == "succeeded"
    assert status.json()["submission_status"] == "success"
    assert status.json()["stdout"] == "done\n"


def test_evaluation_is_blocked_until_worker_finishes(client: TestClient) -> None:
    interview, question = context(client)
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    ).json()
    response = client.post(f"/api/v1/submissions/{submission['submission_id']}/evaluate")
    assert response.status_code == 409


def test_worker_processes_fifo_and_does_not_duplicate_completed_jobs(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    payload = {
        "interview_session_id": interview["interview_session_id"],
        "question_id": question["question_id"],
        "language": "python",
    }
    first = client.post(
        "/api/v1/submissions", json={**payload, "source_code": "first"}
    ).json()
    second = client.post(
        "/api/v1/submissions", json={**payload, "source_code": "second"}
    ).json()

    async def process() -> int:
        async with database() as session:
            worker = ExecutionWorker(sandbox_service)
            while await worker.process_next_job(session):
                submissions = (
                    await session.scalars(
                        select(Submission).where(
                            Submission.id.in_(
                                [
                                    UUID(first["submission_id"]),
                                    UUID(second["submission_id"]),
                                ]
                            )
                        )
                    )
                ).all()
                if len(submissions) == 2 and all(
                    item.status != "queued" for item in submissions
                ):
                    break
            return await worker.process_available_jobs(session)

    assert asyncio.run(process()) == 0
    assert [
        call.kwargs["source_code"] for call in sandbox_service.execute.call_args_list[-2:]
    ] == ["first", "second"]
    assert first["submission_id"] != second["submission_id"]


def test_stale_running_detection_is_read_only(
    client: TestClient, database
) -> None:
    interview, question = context(client)
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    ).json()

    async def inspect() -> tuple[int, str]:
        async with database() as session:
            job = await session.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.submission_id == UUID(submission["submission_id"])
                )
            )
            assert job is not None
            job.status = "running"
            job.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
            await session.commit()
            stale = await find_stale_running_jobs(
                session, timedelta(minutes=5)
            )
            refreshed = await session.get(ExecutionJob, job.id)
            assert refreshed is not None
            return len(stale), refreshed.status

    assert asyncio.run(inspect()) == (1, "running")


def test_worker_hardening_run_loop_and_stale_job_recovery(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    ).json()

    async def inspect() -> tuple[int, str, str]:
        async with database() as session:
            job = await session.scalar(
                select(ExecutionJob).where(
                    ExecutionJob.submission_id == UUID(submission["submission_id"])
                )
            )
            assert job is not None
            job.status = "running"
            job.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
            await session.commit()
            stale = await mark_stale_running_jobs(session, timedelta(minutes=5))
            refreshed = await session.get(ExecutionJob, job.id)
            assert refreshed is not None
            submission_record = await session.get(Submission, UUID(submission["submission_id"]))
            assert submission_record is not None
            return len(stale), refreshed.status, submission_record.status

    result = asyncio.run(inspect())
    assert result[1] == "failed"
    assert result[2] == "sandbox_error"
    assert result[0] >= 1


def test_worker_graceful_stop_event_stops_loop(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(2)",
        },
    )

    async def inspect() -> bool:
        async with database() as session:
            worker = ExecutionWorker(sandbox_service, poll_interval_seconds=0.0, batch_size=1)
            await worker.stop()
            processed = await worker.run_until_idle(session, max_jobs=1)
            return processed == 0 and worker.is_stopped

    assert asyncio.run(inspect()) is True
