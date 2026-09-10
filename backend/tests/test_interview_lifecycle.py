"""Tests for interview lifecycle transitions and deterministic progress."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.submissions import get_sandbox_service
from app.core.database import get_db_session
from app.main import app
from app.models import Base
from app.schemas.execution import ExecutionResult
from app.services.database_service import (
    create_candidate,
    create_interview_session,
    transition_interview_session,
)
from app.models.interview import InterviewStatus


@pytest.fixture
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
        status="success", stdout="ok\n", exit_code=0, execution_time_ms=1
    )
    app.dependency_overrides[get_sandbox_service] = lambda: lambda: service
    yield service
    app.dependency_overrides.pop(get_sandbox_service, None)


@pytest.fixture
def client(
    database: async_sessionmaker, sandbox_service: Mock
) -> TestClient:
    async def override() -> AsyncGenerator:
        async with database() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_session, None)


def assessment(client: TestClient) -> tuple[dict, list[dict]]:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Lifecycle Candidate", "email": f"{uuid4()}@example.com"},
    ).json()
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate["candidate_id"]}
    ).json()
    questions = [
        client.post(
            "/api/v1/questions",
            json={
                "title": f"Question {index}",
                "description": "Description",
                "difficulty": "easy",
                "expected_language": "python",
            },
        ).json()
        for index in range(1, 4)
    ]
    assignment = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions/bulk",
        json={
            "questions": [
                {"question_id": question["question_id"], "sequence_number": index}
                for index, question in enumerate(questions, start=1)
            ]
        },
    )
    assert assignment.status_code == 201
    return interview, questions


def submit(client: TestClient, interview: dict, question: dict) -> None:
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


def test_get_existing_interview_reports_no_progress(client: TestClient) -> None:
    interview, questions = assessment(client)
    unassigned = client.post(
        "/api/v1/questions",
        json={
            "title": "Unassigned question",
            "description": "Not part of this interview",
            "difficulty": "easy",
            "expected_language": "python",
        },
    )
    assert unassigned.status_code == 201
    response = client.get(f"/api/v1/interviews/{interview['interview_session_id']}")

    assert response.status_code == 200
    assert response.json() == {
        "interview_session_id": interview["interview_session_id"],
        "candidate_id": interview["candidate_id"],
        "status": "active",
        "started_at": interview["started_at"],
        "created_at": interview["created_at"],
        "completed_at": None,
        "total_questions": len(questions),
        "submitted_questions": 0,
        "attempted_questions": 0,
        "submission_count": 0,
    }


def test_get_nonexistent_interview_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/interviews/{uuid4()}")
    assert response.status_code == 404


def test_complete_active_interview(client: TestClient) -> None:
    interview, _ = assessment(client)
    response = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/complete"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["started_at"] == interview["started_at"]
    assert body["completed_at"]


def test_complete_already_completed_interview_returns_409(client: TestClient) -> None:
    interview, _ = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/complete"
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409


def test_cancel_active_interview(client: TestClient) -> None:
    interview, _ = assessment(client)
    response = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["completed_at"]


def test_cancel_already_cancelled_interview_returns_409(client: TestClient) -> None:
    interview, _ = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/cancel"
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409


@pytest.mark.parametrize("transition", ["complete", "cancel"])
def test_closed_interview_rejects_submissions(
    client: TestClient, transition: str
) -> None:
    interview, questions = assessment(client)
    client.post(f"/api/v1/interviews/{interview['interview_session_id']}/{transition}")

    response = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": questions[0]["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    )
    assert response.status_code == 409


def test_progress_distinguishes_submission_records_and_questions(
    client: TestClient,
) -> None:
    interview, questions = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}"

    submit(client, interview, questions[0])
    submit(client, interview, questions[0])
    progress = client.get(path).json()
    assert progress["total_questions"] == 3
    assert progress["submitted_questions"] == 1
    assert progress["attempted_questions"] == 1
    assert progress["submission_count"] == 2

    submit(client, interview, questions[1])
    progress = client.get(path).json()
    assert progress["submitted_questions"] == 2
    assert progress["attempted_questions"] == 2
    assert progress["submission_count"] == 3


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/interviews/not-a-uuid"),
        ("post", "/api/v1/interviews/not-a-uuid/complete"),
        ("post", "/api/v1/interviews/not-a-uuid/cancel"),
    ],
)
def test_lifecycle_invalid_uuid_returns_422(
    client: TestClient, method: str, path: str
) -> None:
    response = getattr(client, method)(path)
    assert response.status_code == 422


def test_transition_rolls_back_when_commit_fails(
    database: async_sessionmaker,
) -> None:
    async def scenario() -> None:
        async with database() as session:
            candidate = await create_candidate(
                session, "Rollback Candidate", f"{uuid4()}@example.com"
            )
            interview = await create_interview_session(session, candidate.id)
            session.commit = AsyncMock(side_effect=SQLAlchemyError("commit failed"))
            session.rollback = AsyncMock()

            with pytest.raises(SQLAlchemyError):
                await transition_interview_session(
                    session, interview.id, InterviewStatus.COMPLETED
                )

            session.rollback.assert_awaited_once()

    asyncio.run(scenario())
