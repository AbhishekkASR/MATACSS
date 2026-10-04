"""Focused Question Engine tests using an in-memory database and mock providers."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.question_engine import require_admin
from app.core.llm_provider import LLMFailureKind, LLMProviderError, LLMResponse
from app.main import app
from app.models import (
    AssessmentFeedback,
    Base,
    Candidate,
    EvaluationResult,
    InterviewQuestion,
    InterviewSession,
    Question,
    QuestionLlmLineage,
    QuestionProvenance,
    QuestionStatus,
    QuestionTestCase,
    Submission,
    User,
)
from app.question_bank.engine import (
    QuestionEngineError,
    QuestionGenerationRequest,
    TrustedValidationRequest,
    adapt_question,
    generate_question,
    retrieve_active_questions,
    transition_question_status,
    validate_draft,
)


class MockProvider:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content or json.dumps(
            {
                "title": "Bounded sum",
                "description": "Compute the sum of two integers.",
                "difficulty": "easy",
                "expected_language": "python",
                "input_format": "Two integers",
                "output_format": "One integer",
                "constraints_text": "Values fit in 32 bits.",
                "supported_languages": ["python"],
                "starter_code": "def solve():\n    pass\n",
                "skills": ["iteration", "arithmetic"],
                "concepts": ["array traversal"],
                "complexity_expectations": {
                    "time": "O(n)",
                    "space": "O(1)",
                },
                "reference_solution": "for value in values: total += value",
                "test_case_candidates": [
                    {
                        "input": "2 3",
                        "expected_output": "5",
                        "rationale": "Basic positive values",
                    }
                ],
            }
        )
        self.error = error
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        if self.error is not None:
            raise self.error
        return LLMResponse(self.content, "mock-model", "req-test")


async def make_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def test_generation_persists_strict_draft_and_lineage():
    async def run():
        factory = await make_factory()
        provider = MockProvider()
        async with factory() as session:
            question, request_id = await generate_question(
                session,
                QuestionGenerationRequest(
                    prompt="Make a beginner sum problem", topic="arithmetic"
                ),
                provider,
            )
            assert request_id == "req-test"
            assert question.status == QuestionStatus.DRAFT
            assert question.test_cases == []
            assert question.provenance.source == "question_engine"
            assert question.llm_lineage.origin == "generated"
            assert question.llm_lineage.model == "mock-model"
            metadata = question.llm_lineage.generation_metadata
            assert metadata["expected_outputs_authoritative"] is False
            artifacts = metadata["draft_artifacts"]
            assert artifacts["verification_status"] == "unverified"
            assert artifacts["authoritative"] is False
            assert artifacts["skills"] == ["iteration", "arithmetic"]
            assert artifacts["concepts"] == ["array traversal"]
            assert artifacts["complexity_expectations"]["time"] == "O(n)"
            assert artifacts["reference_solution"].startswith("for value")
            assert artifacts["test_case_candidates"][0]["expected_output"] == "5"
            assert question.test_cases == []
            assert "expected outputs" in provider.messages[0].content.lower()
            assert '"topic": "arithmetic"' in provider.messages[1].content

    asyncio.run(run())


@pytest.mark.parametrize(
    "output",
    [
        '{"title":"Oops","description":"x","difficulty":"easy","expected_language":"python","expected_stdout":"1"}',
        '{"title":"  ","description":"x","difficulty":"easy","expected_language":"python"}',
        "not JSON",
        "x" * 16_001,
    ],
)
def test_invalid_provider_output_is_not_persisted(output):
    async def run():
        factory = await make_factory()
        async with factory() as session:
            with pytest.raises(QuestionEngineError):
                await generate_question(
                    session,
                    QuestionGenerationRequest(prompt="Generate a question"),
                    MockProvider(output),
                )
            count = await session.scalar(select(func.count(Question.id)))
            assert count == 0
            assert await session.scalar(select(func.count(QuestionProvenance.id))) == 0
            assert await session.scalar(select(func.count(QuestionLlmLineage.id))) == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(skills=[""]),
        lambda payload: payload.update(concepts=["array", "array"]),
        lambda payload: payload.update(
            complexity_expectations={"runtime": "O(n)"}
        ),
        lambda payload: payload.update(
            complexity_expectations={"time": 42}
        ),
        lambda payload: payload.update(reference_solution=""),
        lambda payload: payload.update(reference_solution="x" * 8_001),
        lambda payload: payload.update(
            test_case_candidates=[{"input": "x", "expected_output": 3}]
        ),
        lambda payload: payload.update(
            test_case_candidates=[
                {"input": "x" * 4_001, "expected_output": "y"}
            ]
        ),
        lambda payload: payload.update(test_case_candidates=[]),
        lambda payload: payload.update(
            test_case_candidates=[
                {"input": "x", "expected_output": "y"}
            ]
            * 11
        ),
    ],
)
def test_malformed_draft_artifacts_are_rejected_without_persistence(mutate):
    async def run():
        factory = await make_factory()
        payload = json.loads(MockProvider().content)
        mutate(payload)
        async with factory() as session:
            with pytest.raises(QuestionEngineError):
                await generate_question(
                    session,
                    QuestionGenerationRequest(prompt="Generate a question"),
                    MockProvider(json.dumps(payload)),
                )
            assert await session.scalar(select(func.count(Question.id))) == 0

    asyncio.run(run())


def test_duplicate_json_keys_are_rejected():
    async def run():
        factory = await make_factory()
        content = MockProvider().content.replace(
            '"title": "Bounded sum",',
            '"title": "Bounded sum", "title": "Injected duplicate",',
        )
        async with factory() as session:
            with pytest.raises(QuestionEngineError):
                await generate_question(
                    session,
                    QuestionGenerationRequest(prompt="Generate a question"),
                    MockProvider(content),
                )
            assert await session.scalar(select(func.count(Question.id))) == 0

    asyncio.run(run())


def test_provider_must_respect_requested_filters():
    async def run():
        factory = await make_factory()
        async with factory() as session:
            with pytest.raises(QuestionEngineError, match="requested difficulty"):
                await generate_question(
                    session,
                    QuestionGenerationRequest(prompt="Generate", difficulty="hard"),
                    MockProvider(),
                )
            assert await session.scalar(select(func.count(Question.id))) == 0

    asyncio.run(run())


def test_provider_failure_does_not_persist_partial_question():
    async def run():
        factory = await make_factory()
        for error in (
            LLMProviderError(LLMFailureKind.API, "unavailable"),
            RuntimeError("provider crashed"),
        ):
            async with factory() as session:
                with pytest.raises(LLMProviderError):
                    await generate_question(
                        session,
                        QuestionGenerationRequest(prompt="Generate a question"),
                        MockProvider(error=error),
                    )
                assert await session.scalar(select(func.count(Question.id))) == 0

    asyncio.run(run())


def test_adaptation_keeps_parent_lineage_and_does_not_copy_test_cases():
    async def run():
        factory = await make_factory()
        async with factory() as session:
            parent = Question(
                title="Parent",
                description="Original description",
                difficulty="medium",
                expected_language="python",
                status=QuestionStatus.ACTIVE,
            )
            session.add(parent)
            await session.flush()
            session.add(
                QuestionTestCase(
                    question_id=parent.id, stdin="1", expected_stdout="1"
                )
            )
            await session.commit()
            adapted, _ = await adapt_question(
                session,
                parent.id,
                QuestionGenerationRequest(prompt="Make a variation"),
                MockProvider(),
            )
            assert adapted.status == QuestionStatus.DRAFT
            assert adapted.llm_lineage.origin == "adapted"
            assert adapted.llm_lineage.parent_question_id == parent.id
            assert adapted.provenance.original_question_id == str(parent.id)
            assert adapted.test_cases == []

    asyncio.run(run())


def test_review_approval_and_activation_are_separate_transitions():
    async def run():
        factory = await make_factory()
        async with factory() as session:
            provider = MockProvider()
            question, _ = await generate_question(
                session,
                QuestionGenerationRequest(prompt="Generate"),
                provider,
            )
            with pytest.raises(QuestionEngineError):
                await transition_question_status(
                    session, question, QuestionStatus.DRAFT, QuestionStatus.ACTIVE
                )
            session.add(
                QuestionTestCase(
                    question_id=question.id, stdin="2 3", expected_stdout="5"
                )
            )
            await session.commit()
            await validate_draft(
                session,
                question,
                TrustedValidationRequest(
                    trusted_reference_verified=True,
                    review_notes="Checked against a trusted reference implementation.",
                ),
                uuid4(),
            )
            assert question.status == QuestionStatus.VALIDATED
            await transition_question_status(
                session,
                question,
                QuestionStatus.VALIDATED,
                QuestionStatus.APPROVED,
                uuid4(),
            )
            assert question.status == QuestionStatus.APPROVED
            await transition_question_status(
                session, question, QuestionStatus.APPROVED, QuestionStatus.ACTIVE
            )
            assert question.status == QuestionStatus.ACTIVE
            assert question.llm_lineage.generation_metadata["lifecycle_reviews"]

    asyncio.run(run())


def test_admin_dependency_rejects_unauthenticated_legacy_mode():
    from fastapi import HTTPException

    async def run():
        with pytest.raises(HTTPException) as exc:
            await require_admin(None)
        assert exc.value.status_code == 401

    asyncio.run(run())


def test_question_engine_api_rejects_requests_without_admin_authentication():
    with TestClient(app) as client:
        response = client.get("/api/v1/question-engine/retrieve")
    assert response.status_code == 401


def test_lifecycle_transition_route_requires_admin():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/question-engine/questions/{uuid4()}/transition",
            json={"target_status": "approved"},
        )
    assert response.status_code == 401


def test_admin_lifecycle_route_enforces_forward_transitions():
    async def setup():
        factory = await make_factory()
        async with factory() as session:
            admin = User(
                email="lifecycle-admin@example.com",
                password_hash="unused",
                role="admin",
                active=True,
            )
            session.add(admin)
            await session.flush()
            question = Question(
                title="Imported validated question",
                description="A question with trusted test cases.",
                difficulty="easy",
                status=QuestionStatus.VALIDATED,
            )
            session.add(question)
            await session.flush()
            lineage = QuestionLlmLineage(
                question_id=question.id,
                origin="curated",
                generation_metadata={},
            )
            session.add(lineage)
            await session.commit()
            return factory, admin.id, question.id

    factory, admin_id, question_id = asyncio.run(setup())
    from app.core.database import get_db_session
    from app.api.routes.question_engine import require_admin as admin_dependency

    async def override_db():
        async with factory() as session:
            yield session

    async def override_admin():
        return User(
            id=admin_id,
            email="lifecycle-admin@example.com",
            password_hash="unused",
            role="admin",
            active=True,
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[admin_dependency] = override_admin
    try:
        with TestClient(app) as client:
            skipped = client.post(
                f"/api/v1/question-engine/questions/{question_id}/transition",
                json={"target_status": "active"},
            )
            assert skipped.status_code == 409

            for target in ("approved", "active", "deprecated"):
                response = client.post(
                    f"/api/v1/question-engine/questions/{question_id}/transition",
                    json={"target_status": target},
                )
                assert response.status_code == 204, response.text

            backwards = client.post(
                f"/api/v1/question-engine/questions/{question_id}/transition",
                json={"target_status": "approved"},
            )
            invalid_draft = client.post(
                f"/api/v1/question-engine/questions/{question_id}/transition",
                json={"target_status": "draft"},
            )
        assert backwards.status_code == 409
        assert invalid_draft.status_code == 422

        async def check_state():
            async with factory() as session:
                question = await session.get(Question, question_id)
                lineage = await session.scalar(
                    select(QuestionLlmLineage).where(
                        QuestionLlmLineage.question_id == question_id
                    )
                )
                assert question.status == QuestionStatus.DEPRECATED
                transitions = lineage.generation_metadata["lifecycle_reviews"]
                assert [item["transition"] for item in transitions] == [
                    "validated->approved",
                    "approved->active",
                    "active->deprecated",
                ]
                assert all(item["reviewer_id"] == str(admin_id) for item in transitions)

        asyncio.run(check_state())
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(admin_dependency, None)


def test_start_assessment_requires_candidate_authentication():
    with TestClient(app) as client:
        response = client.post("/api/v1/question-engine/assessments/start", json={})
    assert response.status_code == 401


def test_start_assessment_selects_and_assigns_new_active_question():
    async def run():
        factory = await make_factory()
        async with factory() as session:
            user = User(
                email="start@example.com",
                password_hash="unused",
                role="candidate",
                active=True,
            )
            session.add(user)
            await session.flush()
            candidate = Candidate(
                name="Assessment Candidate",
                email=user.email,
                user_id=user.id,
            )
            session.add(candidate)
            first_interview = InterviewSession(
                candidate=candidate, status="completed"
            )
            old_question = Question(
                title="Previously assigned",
                description="An old task.",
                difficulty="easy",
                expected_language="python",
                status=QuestionStatus.ACTIVE,
            )
            draft_question = Question(
                title="Draft task",
                description="Must not be selected.",
                difficulty="easy",
                expected_language="python",
                status=QuestionStatus.DRAFT,
            )
            new_question = Question(
                title="New active task",
                description="Select this task.",
                difficulty="easy",
                expected_language="python",
                input_format="N followed by N integers",
                output_format="One integer: the sum.",
                constraints_text="1 <= N <= 100",
                supported_languages=["python", "java"],
                starter_code="def solve():\n    pass\n",
                status=QuestionStatus.ACTIVE,
            )
            session.add_all([first_interview, old_question, draft_question, new_question])
            await session.flush()
            session.add(
                InterviewQuestion(
                    interview_session=first_interview,
                    question=old_question,
                    sequence_number=1,
                )
            )
            await session.commit()
            return factory, user.id, candidate.id, old_question.id, new_question.id

    factory, user_id, candidate_id, old_question_id, new_question_id = asyncio.run(run())
    from app.core.database import get_db_session
    from app.api.routes.question_engine import require_candidate as candidate_dependency

    async def override_db():
        async with factory() as session:
            yield session

    async def override_candidate():
        return User(
            id=user_id,
            email="start@example.com",
            password_hash="unused",
            role="candidate",
            active=True,
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[candidate_dependency] = override_candidate
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/question-engine/assessments/start",
                json={"difficulty": "easy", "language": "python"},
            )
            resume_response = None
            if response.status_code == 201:
                resume_response = client.get(
                    f"/api/v1/question-engine/assessments/"
                    f"{response.json()['interview_session_id']}/resume"
                )
                retry_response = client.post(
                    "/api/v1/question-engine/assessments/start",
                    json={"difficulty": "easy", "language": "python"},
                )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["candidate_id"] == str(candidate_id)
        assert body["current_question"]["question_id"] == str(new_question_id)
        assert body["current_question"]["status"] == QuestionStatus.ACTIVE
        contract = body["current_question"]
        assert contract["input_format"] == "N followed by N integers"
        assert contract["output_format"] == "One integer: the sum."
        assert contract["constraints_text"] == "1 <= N <= 100"
        assert contract["supported_languages"] == ["python", "java"]
        assert contract["starter_code"] == "def solve():\n    pass\n"
        assert resume_response is not None
        assert resume_response.status_code == 200, resume_response.text
        assert resume_response.json()["current_question"] == contract
        assert retry_response is not None
        assert retry_response.status_code == 200, retry_response.text
        assert (
            retry_response.json()["interview_session_id"]
            == body["interview_session_id"]
        )
        assert retry_response.json()["current_question"] == contract
        async def persisted():
            async with factory() as session:
                interview = await session.get(
                    InterviewSession, UUID(body["interview_session_id"])
                )
                assert interview is not None
                assignments = list(
                    (
                        await session.scalars(
                            select(InterviewQuestion).where(
                                InterviewQuestion.interview_session_id == interview.id
                            )
                        )
                    ).all()
                )
                assert len(assignments) == 1
                assert assignments[0].question_id == new_question_id
                assert assignments[0].question_id != old_question_id

        asyncio.run(persisted())
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(candidate_dependency, None)


@pytest.mark.parametrize("action", ["continue", "finish"])
def test_next_assessment_uses_saved_plan_and_is_idempotent(action: str):
    async def setup():
        factory = await make_factory()
        async with factory() as session:
            user = User(
                email=f"next-{action}@example.com",
                password_hash="unused",
                role="candidate",
                active=True,
            )
            session.add(user)
            await session.flush()
            candidate = Candidate(
                name="Continuing Candidate",
                email=user.email,
                user_id=user.id,
            )
            question = Question(
                title="Completed starter question",
                description="Solve the initial task.",
                difficulty="easy",
                expected_language="python",
                status=QuestionStatus.ACTIVE,
            )
            next_question = Question(
                title="Graph traversal challenge",
                description="Traverse a graph and report reachability.",
                difficulty="medium",
                expected_language="python",
                status=QuestionStatus.ACTIVE,
            )
            session.add_all([candidate, question, next_question])
            await session.flush()
            interview = InterviewSession(candidate_id=candidate.id, status="active")
            session.add(interview)
            await session.flush()
            session.add(
                InterviewQuestion(
                    interview_session_id=interview.id,
                    question_id=question.id,
                    sequence_number=1,
                )
            )
            submission = Submission(
                interview_session_id=interview.id,
                question_id=question.id,
                language="python",
                source_code="pass",
                status="success",
            )
            session.add(submission)
            await session.flush()
            session.add(
                EvaluationResult(
                    submission_id=submission.id,
                    total_test_cases=1,
                    passed_test_cases=1,
                    failed_test_cases=0,
                    score=100,
                    status="scored",
                    case_results=[],
                )
            )
            session.add(
                AssessmentFeedback(
                    submission_id=submission.id,
                    status="completed",
                    interviewer_feedback={
                        "decision_type": "all_questions_attempted",
                        "question_id": None,
                        "question_sequence_number": None,
                        "question_index": None,
                        "question_title": None,
                        "question_prompt": None,
                        "reason": "Use the saved next-step plan.",
                        "interviewer_message": None,
                        "next_step": {
                            "action": action,
                            "topic": "graph",
                            "difficulty": "medium",
                            "language": "python",
                        },
                    },
                )
            )
            await session.commit()
            return factory, user.id, interview.id, next_question.id

    factory, user_id, interview_id, next_question_id = asyncio.run(setup())
    from app.core.database import get_db_session
    from app.api.routes.question_engine import require_candidate as candidate_dependency

    async def override_db():
        async with factory() as session:
            yield session

    async def override_candidate():
        return User(
            id=user_id,
            email=f"next-{action}@example.com",
            password_hash="unused",
            role="candidate",
            active=True,
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[candidate_dependency] = override_candidate
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/question-engine/assessments/{interview_id}/next"
            )
            repeated = (
                client.post(
                    f"/api/v1/question-engine/assessments/{interview_id}/next"
                )
                if action == "continue" and response.status_code == 200
                else None
            )
        assert response.status_code == 200, response.text
        body = response.json()
        if action == "continue":
            assert body["status"] == "active"
            assert body["current_question"]["question_id"] == str(next_question_id)
            assert repeated is not None
            assert repeated.status_code == 200
            assert repeated.json()["current_question"]["question_id"] == str(
                next_question_id
            )
        else:
            assert body["status"] == "completed"
            assert body["current_question"] is None

        async def persisted_assignments():
            async with factory() as session:
                assignments = list(
                    (
                        await session.scalars(
                            select(InterviewQuestion)
                            .where(InterviewQuestion.interview_session_id == interview_id)
                            .order_by(InterviewQuestion.sequence_number)
                        )
                    ).all()
                )
                interview = await session.get(InterviewSession, interview_id)
                return assignments, interview.status

        assignments, persisted_status = asyncio.run(persisted_assignments())
        assert len(assignments) == (2 if action == "continue" else 1)
        assert persisted_status == ("active" if action == "continue" else "completed")
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(candidate_dependency, None)


def test_start_assessment_without_available_question_creates_no_interview():
    async def setup():
        factory = await make_factory()
        async with factory() as session:
            user = User(
                email="empty@example.com",
                password_hash="unused",
                role="candidate",
                active=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                Candidate(name="No Questions", email=user.email, user_id=user.id)
            )
            await session.commit()
            return factory, user.id

    factory, user_id = asyncio.run(setup())
    from app.core.database import get_db_session
    from app.api.routes.question_engine import require_candidate as candidate_dependency

    async def override_db():
        async with factory() as session:
            yield session

    async def override_candidate():
        return User(
            id=user_id,
            email="empty@example.com",
            password_hash="unused",
            role="candidate",
            active=True,
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[candidate_dependency] = override_candidate
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/question-engine/assessments/start", json={}
            )
        assert response.status_code == 409

        async def count_interviews():
            async with factory() as session:
                return await session.scalar(
                    select(func.count(InterviewSession.id))
                )

        assert asyncio.run(count_interviews()) == 0
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(candidate_dependency, None)


def test_resume_assessment_does_not_disclose_another_candidates_session():
    async def setup():
        factory = await make_factory()
        async with factory() as session:
            user = User(
                email="owner@example.com",
                password_hash="unused",
                role="candidate",
                active=True,
            )
            session.add(user)
            await session.flush()
            owner = Candidate(name="Owner", email=user.email, user_id=user.id)
            other = Candidate(name="Other", email="other@example.com")
            session.add_all([owner, other])
            await session.flush()
            interview = InterviewSession(candidate_id=other.id, status="active")
            question = Question(
                title="Private session question",
                description="Question for another candidate.",
                difficulty="easy",
                status=QuestionStatus.ACTIVE,
            )
            session.add_all([interview, question])
            await session.flush()
            session.add(
                InterviewQuestion(
                    interview_session_id=interview.id,
                    question_id=question.id,
                    sequence_number=1,
                )
            )
            await session.commit()
            return factory, user.id, interview.id

    factory, user_id, interview_id = asyncio.run(setup())
    from app.core.database import get_db_session
    from app.api.routes.question_engine import require_candidate as candidate_dependency

    async def override_db():
        async with factory() as session:
            yield session

    async def override_candidate():
        return User(
            id=user_id,
            email="owner@example.com",
            password_hash="unused",
            role="candidate",
            active=True,
        )

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[candidate_dependency] = override_candidate
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/question-engine/assessments/{interview_id}/resume"
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(candidate_dependency, None)


def test_retrieval_is_active_filtered_and_excludes_candidate_history():
    async def run():
        factory = await make_factory()
        async with factory() as session:
            candidate = Candidate(name="Candidate", email="candidate@example.com")
            session.add(candidate)
            await session.flush()
            first_interview = InterviewSession(candidate_id=candidate.id, status="active")
            second_interview = InterviewSession(candidate_id=candidate.id, status="active")
            active = Question(
                title="Array sum",
                description="Sum an array of integers.",
                difficulty="easy",
                expected_language="python",
                supported_languages=["python"],
                status=QuestionStatus.ACTIVE,
            )
            inactive = Question(
                title="Array sum advanced",
                description="Sum an array.",
                difficulty="easy",
                expected_language="python",
                status=QuestionStatus.DRAFT,
            )
            repeated = Question(
                title="Array sum repeated",
                description="Sum an array.",
                difficulty="easy",
                expected_language="python",
                status=QuestionStatus.ACTIVE,
            )
            session.add_all(
                [first_interview, second_interview, active, inactive, repeated]
            )
            await session.flush()
            session.add(
                InterviewQuestion(
                    interview_session_id=first_interview.id,
                    question_id=repeated.id,
                    sequence_number=1,
                )
            )
            await session.commit()
            questions = await retrieve_active_questions(
                session,
                topic="array",
                difficulty="easy",
                language="python",
                interview_session_id=second_interview.id,
            )
            assert [question.id for question in questions] == [active.id]

    asyncio.run(run())
