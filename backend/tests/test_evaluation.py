"""Tests for deterministic test cases and submission evaluation."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.submissions import get_sandbox_service
from app.core.database import get_db_session
from app.main import app
from app.models import Base
from app.schemas.execution import ExecutionResult
from app.services.execution_worker import process_next_execution_job


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
    service.execute.side_effect = lambda **kwargs: ExecutionResult(
        status="success",
        stdout=kwargs["stdin"].replace("\n", " ") + "\n",
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


def context(client: TestClient) -> tuple[dict, dict, dict]:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Evaluation Candidate", "email": f"{uuid4()}@example.com"},
    ).json()
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate["candidate_id"]}
    ).json()
    question = client.post(
        "/api/v1/questions",
        json={
            "title": f"Evaluation {uuid4()}",
            "description": "Evaluate",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    assert client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions",
        json={"question_id": question["question_id"], "sequence_number": 1},
    ).status_code == 201
    return interview, question, candidate


def process_job(database, sandbox_service: Mock) -> None:
    async def process() -> None:
        async with database() as session:
            assert await process_next_execution_job(session, sandbox_service)

    asyncio.run(process())


def test_test_case_order_and_idempotent_evaluation(
    client: TestClient, database, sandbox_service: Mock
) -> None:
    interview, question, _ = context(client)
    for stdin in ("one", "two"):
        response = client.post(
            f"/api/v1/questions/{question['question_id']}/test-cases",
            json={"stdin": stdin, "expected_stdout": f"{stdin}\n"},
        )
        assert response.status_code == 201
    cases = client.get(f"/api/v1/questions/{question['question_id']}/test-cases")
    assert cases.status_code == 200
    assert [item["stdin"] for item in cases.json()] == ["one", "two"]

    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(input())",
        },
    ).json()
    process_job(database, sandbox_service)
    first = client.post(f"/api/v1/submissions/{submission['submission_id']}/evaluate")
    second = client.post(f"/api/v1/submissions/{submission['submission_id']}/evaluate")
    assert first.status_code == second.status_code == 200
    assert first.json()["passed_test_cases"] == 2
    assert first.json()["score"] == 100
    assert second.json()["evaluation_result_id"] == first.json()["evaluation_result_id"]

    retrieved = client.get(
        f"/api/v1/submissions/{submission['submission_id']}/evaluation"
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["total_test_cases"] == 2


def test_zero_test_cases_is_not_scored(
    client: TestClient, database, sandbox_service: Mock
) -> None:
    interview, question, _ = context(client)
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(1)",
        },
    ).json()
    process_job(database, sandbox_service)
    response = client.post(f"/api/v1/submissions/{submission['submission_id']}/evaluate")
    assert response.status_code == 200
    assert response.json()["status"] == "not_scored"
    assert response.json()["score"] is None


def test_partial_pass_and_stdout_normalization(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question, _ = context(client)
    for stdin, expected in (("pass", "value\n"), ("fail", "different")):
        assert client.post(
            f"/api/v1/questions/{question['question_id']}/test-cases",
            json={"stdin": stdin, "expected_stdout": expected},
        ).status_code == 201
    sandbox_service.execute.side_effect = lambda **kwargs: ExecutionResult(
        status="success",
        stdout="value\r\n" if kwargs["stdin"] == "pass" else "value",
        exit_code=0,
        execution_time_ms=1,
    )
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print('value')",
        },
    ).json()
    process_job(database, sandbox_service)
    result = client.post(f"/api/v1/submissions/{submission['submission_id']}/evaluate")
    assert result.status_code == 200
    assert result.json()["passed_test_cases"] == 1
    assert result.json()["failed_test_cases"] == 1
    assert result.json()["score"] == 50


def test_missing_test_case_question_and_submission_return_404(
    client: TestClient,
) -> None:
    missing = str(uuid4())
    assert client.get(f"/api/v1/questions/{missing}/test-cases").status_code == 404
    assert client.post(f"/api/v1/submissions/{missing}/evaluate").status_code == 404
    assert client.get(f"/api/v1/submissions/{missing}/evaluation").status_code == 404
    assert client.get("/api/v1/questions/not-a-uuid/test-cases").status_code == 422


def test_assessment_results_aggregate_latest_attempts(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    interview, question, _ = context(client)
    assert client.post(
        f"/api/v1/questions/{question['question_id']}/test-cases",
        json={"stdin": "x", "expected_stdout": "x\n"},
    ).status_code == 201

    first = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print(input())",
            "stdin": "x",
        },
    ).json()
    process_job(database, sandbox_service)
    evaluated = client.post(f"/api/v1/submissions/{first['submission_id']}/evaluate")
    assert evaluated.status_code == 200

    second = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "raise Exception()",
            "stdin": "x",
        },
    ).json()
    results = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results"
    )
    assert results.status_code == 200
    body = results.json()
    assert body["total_questions"] == 1
    assert body["attempted_questions"] == 1
    assert body["evaluated_questions"] == 0
    assert body["overall_score"] is None
    assert body["status"] == "not_scored"
    assert body["questions"][0]["latest_submission_id"] == second["submission_id"]
    assert body["questions"][0]["evaluation_status"] == "attempted_not_evaluated"

    process_job(database, sandbox_service)
    assert client.post(f"/api/v1/submissions/{second['submission_id']}/evaluate").status_code == 200
    scored = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results"
    ).json()
    assert scored["evaluated_questions"] == 1
    assert scored["total_passed_test_cases"] == 1
    assert scored["total_test_cases"] == 1
    assert scored["overall_score"] == 100


def test_assessment_results_allow_closed_interviews_and_exclude_unassigned(
    client: TestClient,
) -> None:
    interview, question, _ = context(client)
    unrelated = client.post(
        "/api/v1/questions",
        json={
            "title": f"Unassigned {uuid4()}",
            "description": "Not assigned",
            "difficulty": "easy",
            "expected_language": "python",
        },
    ).json()
    assert unrelated["question_id"] != question["question_id"]
    complete = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/complete"
    )
    assert complete.status_code == 200
    results = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results"
    )
    assert results.status_code == 200
    assert results.json()["interview_status"] == "completed"
    assert len(results.json()["questions"]) == 1
    assert client.get(f"/api/v1/interviews/{uuid4()}/results").status_code == 404
    assert client.get("/api/v1/interviews/not-a-uuid/results").status_code == 422
