"""High-value end-to-end regression tests for the core MATACSS pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
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
from app.orchestration.assessment_graph import invoke_assessment_graph
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)
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
    service.execute.return_value = ExecutionResult(
        status="success",
        stdout="42\n",
        stderr="",
        exit_code=0,
        execution_time_ms=5,
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


def test_submission_worker_evaluation_and_assessment_graph_pipeline(
    client: TestClient, sandbox_service: Mock, database
) -> None:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Pipeline Candidate", "email": f"pipeline-{uuid4()}@example.com"},
    )
    assert candidate.status_code == 201
    interview = client.post(
        "/api/v1/interviews",
        json={"candidate_id": candidate.json()["candidate_id"]},
    )
    assert interview.status_code == 201

    question = client.post(
        "/api/v1/questions",
        json={
            "title": "Compute the answer",
            "description": "Print the number 42.",
            "difficulty": "easy",
            "expected_language": "python",
        },
    )
    assert question.status_code == 201
    question_id = question.json()["question_id"]
    assignment = client.post(
        f"/api/v1/interviews/{interview.json()['interview_session_id']}/questions",
        json={"question_id": question_id, "sequence_number": 1},
    )
    assert assignment.status_code == 201

    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview.json()["interview_session_id"],
            "question_id": question_id,
            "language": "python",
            "source_code": "print(42)",
        },
    )
    assert submission.status_code == 200
    submission_id = UUID(submission.json()["submission_id"])

    async def run_worker() -> None:
        async with database() as session:
            for _ in range(25):
                processed = await process_next_execution_job(session, sandbox_service)
                if not processed:
                    break
                current = await session.get(Submission, submission_id)
                if current is not None and current.status != "queued":
                    break

    asyncio.run(run_worker())
    assert sandbox_service.execute.call_count >= 1

    status = client.get(f"/api/v1/submissions/{submission_id}/status")
    assert status.status_code == 200
    assert status.json()["submission_status"] == "success"
    assert status.json()["job_status"] == "succeeded"

    case = client.post(
        f"/api/v1/questions/{question_id}/test-cases",
        json={
            "stdin": "",
            "expected_stdout": "42\n",
            "description": "baseline smoke case",
        },
    )
    assert case.status_code == 201

    evaluated = client.post(f"/api/v1/submissions/{submission_id}/evaluate")
    assert evaluated.status_code == 200
    body = evaluated.json()
    assert body["status"] == "scored"
    assert body["score"] == 100
    assert body["passed_test_cases"] == 1

    question_state = AssessmentQuestionState(
        question_id=question_id,
        sequence_number=1,
        title="Compute the answer",
        description="Print the number 42.",
        difficulty="easy",
        expected_language="python",
        latest_submission_id=None,
        evaluation_status="not_attempted",
    )
    assessment = AssessmentState(
        interview_session_id=UUID(interview.json()["interview_session_id"]),
        candidate_id=UUID(candidate.json()["candidate_id"]),
        assessment_status="active",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        created_at=datetime.now(timezone.utc),
        generated_at=datetime.now(timezone.utc),
        assigned_questions=(question_state,),
        current_question_id=question_id,
        progress=AssessmentProgressState(
            total_questions=1,
            attempted_questions=0,
            evaluated_questions=0,
            current_question_index=0,
        ),
    )

    graph_result = invoke_assessment_graph(assessment)
    assert str(graph_result.interviewer_decision.question_id) == question_id
    assert graph_result.code_review.review_status in {"not_run", "passed"}
    assert str(graph_result.edge_case_generation.question_id) == question_id
    assert graph_result.feedback_result is not None
    assert graph_result.feedback_result.status in {"generated", "incomplete", "blocked"}
    assert graph_result.feedback_result.assessment.score in {None, 100.0}
