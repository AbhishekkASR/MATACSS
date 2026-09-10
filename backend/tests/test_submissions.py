"""Tests for persistent code submission execution."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.submissions import get_sandbox_service
from app.core.database import get_db_session
from app.main import app
from app.models import Base, Submission
from app.schemas.execution import ExecutionResult
from app.services.execution_worker import process_next_execution_job


@pytest.fixture(scope="module")
def database() -> async_sessionmaker:
    async def setup() -> async_sessionmaker:
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
        stdout="hello\n",
        exit_code=0,
        execution_time_ms=1.5,
    )
    app.dependency_overrides[get_sandbox_service] = lambda: lambda: service
    yield service
    app.dependency_overrides.pop(get_sandbox_service, None)


@pytest.fixture
def client(database: async_sessionmaker, sandbox_service: Mock) -> TestClient:
    async def override() -> AsyncGenerator:
        async with database() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_session, None)


def context(client: TestClient, active: bool = True) -> tuple[dict, dict]:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Candidate", "email": f"{uuid4()}@example.com"},
    ).json()
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate["candidate_id"]}
    ).json()
    if not active:
        interview["status"] = "completed"
    question = client.post(
        "/api/v1/questions",
        json={
            "title": "Question",
            "description": "Description",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    assignment = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions",
        json={"question_id": question["question_id"], "sequence_number": 1},
    )
    assert assignment.status_code == 201
    return interview, question


def process_job(database, sandbox_service: Mock) -> None:
    async def process() -> None:
        async with database() as session:
            assert await process_next_execution_job(session, sandbox_service)

    asyncio.run(process())


def test_valid_submission_is_persisted(
    client: TestClient, sandbox_service: Mock, database: async_sessionmaker
) -> None:
    interview, question = context(client)
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print('hello')",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["interview_session_id"] == interview["interview_session_id"]
    assert body["question_id"] == question["question_id"]

    process_job(database, sandbox_service)

    async def verify() -> None:
        async with database() as session:
            submission = (
                await session.execute(
                    select(Submission).where(
                        Submission.id == UUID(body["submission_id"])
                    )
                )
            ).scalar_one()
            assert submission.status == "success"
            assert submission.stdout == "hello\n"

    asyncio.run(verify())
    sandbox_service.execute.assert_called_once()


@pytest.mark.parametrize(
    ("status_value", "timed_out"),
    [
        ("compilation_error", False),
        ("runtime_error", False),
        ("timeout", True),
        ("output_limit_exceeded", False),
        ("sandbox_error", False),
    ],
)
def test_execution_outcomes_are_persisted(
    client: TestClient,
    sandbox_service: Mock,
    status_value: str,
    timed_out: bool,
    database: async_sessionmaker,
) -> None:
    sandbox_service.execute.return_value = ExecutionResult(
        status=status_value,
        stderr="error",
        execution_time_ms=2,
        timed_out=timed_out,
    )
    interview, question = context(client)
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 200
    process_job(database, sandbox_service)

    async def verify() -> None:
        async with database() as session:
            stored = (
                await session.execute(
                    select(Submission)
                    .where(Submission.status == status_value)
                    .order_by(Submission.created_at.desc())
                )
            ).scalars().first()
            assert stored is not None
            assert stored.status == status_value
            assert stored.timed_out is timed_out

    asyncio.run(verify())


def test_missing_interview_returns_404(client: TestClient) -> None:
    _, question = context(client)
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": str(uuid4()),
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 404


def test_missing_question_returns_404(client: TestClient) -> None:
    interview, _ = context(client)
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": str(uuid4()),
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 404


def test_unassigned_question_returns_409_without_execution(
    client: TestClient, sandbox_service: Mock
) -> None:
    interview, _ = context(client)
    question = client.post(
        "/api/v1/questions",
        json={
            "title": "Unassigned",
            "description": "Not assigned",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 409
    sandbox_service.execute.assert_not_called()


def test_submission_history_is_newest_first_and_latest_is_returned(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question = context(client)
    sandbox_service.execute.side_effect = [
        ExecutionResult(
            status="runtime_error",
            stdout="first",
            stderr="error",
            exit_code=1,
            execution_time_ms=2,
        ),
        ExecutionResult(
            status="success",
            stdout="second",
            exit_code=0,
            execution_time_ms=1,
        ),
    ]
    payload = {
        "interview_session_id": interview["interview_session_id"],
        "question_id": question["question_id"],
        "language": "python",
        "source_code": "print(1)",
    }
    first = client.post("/api/v1/submissions", json=payload)
    second = client.post("/api/v1/submissions", json=payload)
    assert first.status_code == second.status_code == 200
    process_job(database, sandbox_service)
    process_job(database, sandbox_service)

    history = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/"
        f"{question['question_id']}/submissions"
    )
    latest = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/"
        f"{question['question_id']}/latest-submission"
    )
    assert history.status_code == 200
    assert [attempt["stdout"] for attempt in history.json()] == ["second", "first"]
    assert latest.status_code == 200
    assert latest.json()["stdout"] == "second"


def test_latest_submission_without_attempt_returns_404(client: TestClient) -> None:
    interview, question = context(client)
    response = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/"
        f"{question['question_id']}/latest-submission"
    )
    assert response.status_code == 404


def test_submission_history_rejects_unassigned_question(client: TestClient) -> None:
    interview, _ = context(client)
    question = client.post(
        "/api/v1/questions",
        json={
            "title": "Unassigned history question",
            "description": "Not assigned",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    response = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/"
        f"{question['question_id']}/submissions"
    )
    assert response.status_code == 409


@pytest.mark.parametrize("transition", ["complete", "cancel"])
def test_submission_history_allows_closed_interviews(
    client: TestClient, sandbox_service: Mock, transition: str, database
) -> None:
    interview, question = context(client)
    payload = {
        "interview_session_id": interview["interview_session_id"],
        "question_id": question["question_id"],
        "language": "python",
        "source_code": "print(1)",
    }
    assert client.post("/api/v1/submissions", json=payload).status_code == 200
    process_job(database, sandbox_service)
    assert client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/{transition}"
    ).status_code == 200
    response = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/"
        f"{question['question_id']}/submissions"
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_inactive_interview_returns_409(
    client: TestClient, database: async_sessionmaker
) -> None:
    interview, question = context(client)

    async def mark_completed() -> None:
        from app.models import InterviewSession

        async with database() as session:
            record = await session.get(
                InterviewSession, UUID(interview["interview_session_id"])
            )
            record.status = "completed"
            await session.commit()

    asyncio.run(mark_completed())
    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"interview_session_id": "bad", "question_id": str(uuid4()), "language": "python", "source_code": "x"},
        {"interview_session_id": str(uuid4()), "question_id": "bad", "language": "python", "source_code": "x"},
        {"interview_session_id": str(uuid4()), "question_id": str(uuid4()), "language": "python", "source_code": " "},
        {"interview_session_id": str(uuid4()), "question_id": str(uuid4()), "language": "go", "source_code": "x"},
    ],
)
def test_submission_validation(client: TestClient, payload: dict) -> None:
    assert client.post("/api/v1/submissions", json=payload).status_code == 422


def test_health_endpoint_still_works(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
