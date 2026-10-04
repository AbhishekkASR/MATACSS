"""Persistence and API coverage for submission-scoped advisory feedback."""

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.core.config as config
from app.core.database import get_db_session
from app.core.llm_provider import LLMFailureKind, LLMProviderError, LLMResponse
from app.core.security import get_current_active_user
from app.main import app
from app.api.routes.submissions import get_sandbox_service
from app.services.auth_service import create_user
from app.models import (
    AssessmentFeedback,
    Base,
    Candidate,
    Question,
    QuestionStatus,
    QuestionTestCase,
    User,
    UserRole,
)
from app.schemas.execution import ExecutionResult
from app.services.execution_worker import process_next_execution_job


class InMemorySandbox:
    def execute(self, **_kwargs) -> ExecutionResult:
        return ExecutionResult(
            status="success",
            stdout="official output",
            exit_code=0,
            execution_time_ms=1,
        )


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
def client(database, monkeypatch) -> TestClient:
    async def override() -> AsyncGenerator:
        async with database() as session:
            yield session

    original_jwt_secret = config.settings.jwt_secret
    object.__setattr__(
        config.settings, "jwt_secret", "feedback-test-secret-32-bytes-minimum"
    )
    app.dependency_overrides[get_db_session] = override
    app.dependency_overrides[get_sandbox_service] = lambda: InMemorySandbox
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_sandbox_service, None)
        app.dependency_overrides.pop(get_current_active_user, None)
        object.__setattr__(config.settings, "jwt_secret", original_jwt_secret)


class FakeLLMProvider:
    """In-process stand-in at the provider boundary; no network is available."""

    requests: list[tuple[str, dict]]
    should_fail = False

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def complete(self, messages) -> LLMResponse:
        system = messages[0].content
        payload = json.loads(messages[1].content)
        self.requests.append((system, payload))
        if self.should_fail:
            raise LLMProviderError(
                LLMFailureKind.API, "provider token=secret-value must not persist"
            )
        if "interview presentation assistant" in system:
            result = {
                "selected_question_id": payload["allowed_question_id"],
                "reason": "The next assigned question remains available.",
                "interviewer_message": "Continue with the next question.",
                "next_step": {
                    "action": "continue",
                    "topic": "array boundary handling",
                    "difficulty": "medium",
                    "language": "python",
                },
            }
        elif "advisory static code reviewer" in system:
            question_id = payload["question_id"]
            result = {
                "review_status": "completed",
                "question_id": question_id,
                "correctness_summary": "Static observations are advisory.",
                "observations": [],
                "improvement_suggestions": ["Consider a clearer variable name."],
                "reason": "Static review completed.",
            }
        elif "edge-case candidate generator" in system:
            question_id = payload["question_id"]
            result = {
                "question_id": question_id,
                "cases": [],
                "reason": "No additional candidate cases were generated.",
            }
        else:
            raise AssertionError("Unexpected provider-boundary call")
        return LLMResponse(content=json.dumps(result), model="test-model")


def install_fake_provider(monkeypatch, *, failing: bool = False) -> None:
    FakeLLMProvider.requests = []
    FakeLLMProvider.should_fail = failing
    monkeypatch.setattr(
        "app.services.assessment_orchestration_service.OpenAILLMProvider",
        FakeLLMProvider,
    )


def create_assessment(client: TestClient, database, *, add_followup: bool = False):
    candidate_email = f"feedback-{uuid4()}@example.com"
    candidate_password = "feedback-candidate-password"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Feedback Candidate",
            "email": candidate_email,
            "password": candidate_password,
        },
    )
    assert registration.status_code == 201, registration.text
    candidate_login = client.post(
        "/api/v1/auth/login",
        json={"email": candidate_email, "password": candidate_password},
    )
    assert candidate_login.status_code == 200, candidate_login.text
    candidate_headers = {
        "Authorization": f"Bearer {candidate_login.json()['access_token']}"
    }

    admin_email = f"feedback-admin-{uuid4()}@example.com"
    admin_password = "feedback-admin-password"

    async def create_admin() -> None:
        async with database() as session:
            await create_user(
                session,
                admin_email,
                admin_password,
                role=UserRole.ADMIN,
            )

    asyncio.run(create_admin())
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_headers = {
        "Authorization": f"Bearer {admin_login.json()['access_token']}"
    }

    async def get_candidate_id() -> str:
        async with database() as session:
            candidate = await session.scalar(
                select(Candidate).where(Candidate.email == candidate_email)
            )
            assert candidate is not None
            return str(candidate.id)

    candidate_id = asyncio.run(get_candidate_id())
    interview = client.post(
        "/api/v1/interviews",
        json={"candidate_id": candidate_id},
        headers=candidate_headers,
    )
    assert interview.status_code == 201, interview.text
    interview = interview.json()
    question = client.post(
        "/api/v1/questions",
        json={
            "title": "Feedback question",
            "description": "Given an array, return its length.",
            "difficulty": "easy",
            "expected_language": "python",
        },
        headers=admin_headers,
    ).json()
    assert "question_id" in question, question

    async def prepare() -> None:
        async with database() as session:
            stored_question = await session.get(
                Question, UUID(question["question_id"])
            )
            stored_question.status = QuestionStatus.ACTIVE
            session.add(
                QuestionTestCase(
                    question_id=stored_question.id,
                    stdin="input",
                    expected_stdout="official output",
                    description="sample",
                )
            )
            await session.commit()

    asyncio.run(prepare())
    assigned = client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions",
        json={"question_id": question["question_id"], "sequence_number": 1},
        headers=admin_headers,
    )
    assert assigned.status_code == 201
    if add_followup:
        followup = client.post(
            "/api/v1/questions",
            json={
                "title": "Follow-up question",
                "description": "Given a list, identify its smallest element.",
                "difficulty": "medium",
                "expected_language": "python",
            },
            headers=admin_headers,
        ).json()
        assert "question_id" in followup, followup

        async def activate_followup() -> None:
            async with database() as session:
                stored = await session.get(Question, UUID(followup["question_id"]))
                stored.status = QuestionStatus.ACTIVE
                await session.commit()

        asyncio.run(activate_followup())
        followup_assignment = client.post(
            f"/api/v1/interviews/{interview['interview_session_id']}/questions",
            json={
                "question_id": followup["question_id"],
                "sequence_number": 2,
            },
            headers=admin_headers,
        )
        assert followup_assignment.status_code == 201
    interview["_candidate_headers"] = candidate_headers
    return {"candidate_id": candidate_id, "email": candidate_email}, interview, question


def evaluate_once(client: TestClient, database, interview, question) -> dict:
    submission = client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview["interview_session_id"],
            "question_id": question["question_id"],
            "language": "python",
            "source_code": "print('official output')",
        },
        headers=interview["_candidate_headers"],
    )
    assert submission.status_code == 200

    async def process() -> None:
        async with database() as session:
            assert await process_next_execution_job(session, InMemorySandbox())

    asyncio.run(process())
    response = client.post(
        f"/api/v1/submissions/{submission.json()['submission_id']}/evaluate",
        headers=interview["_candidate_headers"],
    )
    assert response.status_code == 200
    return response.json()


def test_feedback_is_persisted_retrieved_and_idempotent(
    client: TestClient, database, monkeypatch
) -> None:
    install_fake_provider(monkeypatch)
    _, interview, question = create_assessment(client, database)

    first = evaluate_once(client, database, interview, question)
    assert first["score"] == 100
    assert len(FakeLLMProvider.requests) == 3
    second = client.post(
        f"/api/v1/submissions/{first['submission_id']}/evaluate",
        headers=interview["_candidate_headers"],
    )
    assert second.status_code == 200
    assert second.json()["evaluation_result_id"] == first["evaluation_result_id"]
    assert second.json()["score"] == first["score"]
    assert len(FakeLLMProvider.requests) == 3

    async def stored_feedback() -> list[AssessmentFeedback]:
        async with database() as session:
            return list(
                (
                    await session.scalars(
                        select(AssessmentFeedback).where(
                            AssessmentFeedback.submission_id
                            == UUID(first["submission_id"])
                        )
                    )
                ).all()
            )

    records = asyncio.run(stored_feedback())
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].interviewer_feedback["decision_type"] == "all_questions_attempted"
    assert records[0].reviewer_feedback["review_status"] == "completed"
    assert records[0].edge_case_feedback["question_id"] == question["question_id"]
    assert records[0].aggregated_feedback["assessment"]["score"] == 100
    reviewer_request = next(
        payload
        for system, payload in FakeLLMProvider.requests
        if "advisory static code reviewer" in system
    )
    assert reviewer_request["source_code"] == "print('official output')"
    assert reviewer_request["execution_summary"] == {
        "submission_status": "success",
        "evaluation_status": "evaluated",
        "passed_test_cases": 1,
        "total_test_cases": 1,
    }

    response = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results",
        headers=interview["_candidate_headers"],
    )
    assert response.status_code == 200
    report = response.json()["agent_feedback"]
    assert len(report) == 1
    assert set(report[0]) == {
        "submission_id",
        "status",
        "interviewer_decision",
        "code_review",
        "edge_case_generation",
        "feedback",
        "failure_kind",
        "created_at",
    }
    assert report[0]["submission_id"] == first["submission_id"]
    assert report[0]["status"] == "completed"
    assert report[0]["interviewer_decision"]["decision_type"] == (
        "all_questions_attempted"
    )
    assert report[0]["code_review"]["review_status"] == "completed"
    assert report[0]["edge_case_generation"]["question_id"] == question["question_id"]
    assert report[0]["feedback"]["assessment"]["score"] == 100
    assert report[0]["failure_kind"] is None
    assert report[0]["created_at"]
    result = response.json()["questions"][0]
    assert result["score"] == 100
    assert result["ai_feedback"]["is_advisory"] is True
    assert result["ai_feedback"]["reviewer"]["correctness_summary"] == (
        "Static observations are advisory."
    )


def test_provider_failure_does_not_change_official_score_and_can_retry(
    client: TestClient, database, monkeypatch
) -> None:
    install_fake_provider(monkeypatch, failing=True)
    _, interview, question = create_assessment(client, database)

    failed = evaluate_once(client, database, interview, question)
    assert failed["score"] == 100
    assert failed["status"] == "scored"

    async def saved_record() -> AssessmentFeedback:
        async with database() as session:
            return await session.scalar(
                select(AssessmentFeedback).where(
                    AssessmentFeedback.submission_id
                    == UUID(failed["submission_id"])
                )
            )

    record = asyncio.run(saved_record())
    assert record.status == "failed"
    assert record.failure_kind == "provider_error"
    assert "secret-value" not in repr(record.__dict__)
    failed_report = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results",
        headers=interview["_candidate_headers"],
    ).json()
    assert failed_report["questions"][0]["ai_feedback"]["status"] == "failed"
    assert failed_report["agent_feedback"][0]["submission_id"] == failed[
        "submission_id"
    ]
    assert failed_report["agent_feedback"][0]["status"] == "failed"
    assert failed_report["agent_feedback"][0]["failure_kind"] == "provider_error"
    assert "secret-value" not in json.dumps(failed_report["agent_feedback"])

    install_fake_provider(monkeypatch)
    retried = client.post(
        f"/api/v1/submissions/{failed['submission_id']}/evaluate",
        headers=interview["_candidate_headers"],
    )
    assert retried.status_code == 200
    assert retried.json()["score"] == 100
    record = asyncio.run(saved_record())
    assert record.status == "completed"
    assert record.failure_kind is None


def test_interviewer_next_step_is_saved_in_the_retrieved_decision(
    client: TestClient, database, monkeypatch
) -> None:
    install_fake_provider(monkeypatch)
    _, interview, question = create_assessment(
        client, database, add_followup=True
    )

    evaluated = evaluate_once(client, database, interview, question)
    assert evaluated["score"] == 100
    interviewer_request = next(
        payload
        for system, payload in FakeLLMProvider.requests
        if "interview presentation assistant" in system
    )
    assert interviewer_request["allowed_question_id"]
    provider_call_count = len(FakeLLMProvider.requests)
    retried = client.post(
        f"/api/v1/submissions/{evaluated['submission_id']}/evaluate",
        headers=interview["_candidate_headers"],
    )
    assert retried.status_code == 200
    assert len(FakeLLMProvider.requests) == provider_call_count

    results = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/results",
        headers=interview["_candidate_headers"],
    ).json()
    recommendation = results["agent_feedback"][0]["interviewer_decision"][
        "next_step"
    ]
    assert recommendation == {
        "action": "continue",
        "topic": "array boundary handling",
        "difficulty": "medium",
        "language": "python",
    }


def test_saved_feedback_is_only_returned_to_assessment_owner(
    client: TestClient, database, monkeypatch
) -> None:
    install_fake_provider(monkeypatch)
    candidate, interview, question = create_assessment(client, database)
    evaluation = evaluate_once(client, database, interview, question)

    async def create_users() -> tuple[User, User]:
        async with database() as session:
            owner = User(
                email=f"owner-{uuid4()}@example.com",
                password_hash="not-used",
                role="candidate",
            )
            other = User(
                email=f"other-{uuid4()}@example.com",
                password_hash="not-used",
                role="candidate",
            )
            session.add_all([owner, other])
            await session.commit()
            stored_candidate = await session.get(
                Candidate, UUID(candidate["candidate_id"])
            )
            stored_candidate.user_id = owner.id
            await session.commit()
            return owner, other

    owner, other = asyncio.run(create_users())
    monkeypatch.setattr(
        "app.api.routes.domain.settings", SimpleNamespace(jwt_secret="test-secret")
    )
    app.dependency_overrides[get_current_active_user] = lambda: owner
    path = f"/api/v1/interviews/{interview['interview_session_id']}/results"
    owned = client.get(path)
    assert owned.status_code == 200
    assert owned.json()["questions"][0]["ai_feedback"]["status"] == "completed"

    app.dependency_overrides[get_current_active_user] = lambda: other
    denied = client.get(path)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Forbidden"
    assert evaluation["score"] == 100


def test_feedback_migration_is_the_single_head_and_matches_model() -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["007_assessment_feedback"]
    revision = scripts.get_revision("007_assessment_feedback")
    assert revision.down_revision == "006_question_bank"

    table = Base.metadata.tables["assessment_feedback"]
    assert set(table.columns.keys()) == {
        "id",
        "submission_id",
        "status",
        "failure_kind",
        "interviewer_feedback",
        "reviewer_feedback",
        "edge_case_feedback",
        "aggregated_feedback",
        "created_at",
    }
    assert any(
        index.name == "ix_assessment_feedback_submission_id" and index.unique
        for index in table.indexes
    )
    assert any(
        constraint.name == "ck_assessment_feedback_status"
        for constraint in table.constraints
    )
