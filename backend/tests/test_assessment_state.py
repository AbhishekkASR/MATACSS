"""Focused coverage for the future-agent assessment state contract."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.candidate import Candidate
from app.models.evaluation import EvaluationResult
from app.models.interview import InterviewSession, InterviewStatus
from app.models.interview_question import InterviewQuestion
from app.models.question import Question
from app.models.submission import Submission
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)
from app.services.assessment_state_service import build_assessment_state


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


async def _assessment(
    session: AsyncSession,
    *,
    status: InterviewStatus = InterviewStatus.ACTIVE,
    question_count: int = 2,
    attempt_first: bool = False,
    evaluate_first: bool = False,
) -> tuple[InterviewSession, list[Question]]:
    now = datetime.now(timezone.utc)
    candidate = Candidate(name="State Candidate", email=f"{uuid4()}@example.com")
    session.add(candidate)
    await session.flush()
    interview = InterviewSession(
        candidate_id=candidate.id,
        status=status,
        started_at=now if status == InterviewStatus.ACTIVE else None,
        completed_at=now if status != InterviewStatus.ACTIVE else None,
        created_at=now,
    )
    session.add(interview)
    questions: list[Question] = []
    for number in range(1, question_count + 1):
        question = Question(
            title=f"Question {number}",
            description=f"Public prompt {number}",
            difficulty="easy",
            expected_language="python",
            created_at=now,
        )
        session.add(question)
        await session.flush()
        session.add(
            InterviewQuestion(
                interview_session_id=interview.id,
                question_id=question.id,
                sequence_number=number,
                created_at=now,
            )
        )
        questions.append(question)
    if attempt_first:
        submission = Submission(
            interview_session_id=interview.id,
            question_id=questions[0].id,
            language="python",
            source_code="secret candidate source must never enter state",
            stdin="private input",
            status="success",
            stdout="private output",
            stderr="",
            created_at=now,
        )
        session.add(submission)
        await session.flush()
        if evaluate_first:
            session.add(
                EvaluationResult(
                    submission_id=submission.id,
                    status="scored",
                    total_test_cases=2,
                    passed_test_cases=1,
                    failed_test_cases=1,
                    score=50,
                    case_results=[{"expected_stdout": "private expected output"}],
                    created_at=now,
                )
            )
    await session.commit()
    return interview, questions


def test_active_state_orders_questions_and_sanitizes_latest_context(database) -> None:
    async def exercise() -> None:
        async with database() as session:
            interview, questions = await _assessment(
                session, attempt_first=True, evaluate_first=True
            )
            state = await build_assessment_state(session, interview.id)
            assert [item.question_id for item in state.assigned_questions] == [
                question.id for question in questions
            ]
            assert state.current_question_id == questions[1].id
            assert state.progress.current_question_index == 1
            assert state.progress.attempted_questions == state.progress.evaluated_questions == 1
            first = state.assigned_questions[0]
            assert first.evaluation_status == "evaluated"
            assert first.score == 50
            assert first.passed_test_cases == 1
            dump = state.model_dump_json()
            assert "secret candidate source" not in dump
            assert "private input" not in dump
            assert "private output" not in dump
            assert "private expected output" not in dump

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_closed_state_has_no_current_question(database, status: InterviewStatus) -> None:
    async def exercise() -> None:
        async with database() as session:
            interview, _ = await _assessment(session, status=status, question_count=1)
            state = await build_assessment_state(session, interview.id)
            assert state.assessment_status == status
            assert state.completed_at is not None
            assert state.current_question_id is None
            assert state.progress.current_question_index is None

    asyncio.run(exercise())


def test_empty_and_fully_attempted_active_states_have_no_current_question(database) -> None:
    async def exercise() -> None:
        async with database() as session:
            empty, _ = await _assessment(session, question_count=0)
            empty_state = await build_assessment_state(session, empty.id)
            assert empty_state.progress.total_questions == 0
            assert empty_state.current_question_id is None

            attempted, _ = await _assessment(session, question_count=1, attempt_first=True)
            attempted_state = await build_assessment_state(session, attempted.id)
            assert attempted_state.progress.attempted_questions == 1
            assert attempted_state.current_question_id is None

    asyncio.run(exercise())


def test_invalid_state_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Question",
        description="Prompt",
        difficulty="easy",
        evaluation_status="not_attempted",
    )
    with pytest.raises(ValidationError, match="closed interviews require"):
        AssessmentState(
            interview_session_id=uuid4(),
            candidate_id=uuid4(),
            assessment_status=InterviewStatus.COMPLETED,
            created_at=now,
            generated_at=now,
            assigned_questions=(question,),
            progress=AssessmentProgressState(
                total_questions=1, attempted_questions=0, evaluated_questions=0
            ),
        )
    with pytest.raises(ValidationError, match="first unattempted"):
        AssessmentState(
            interview_session_id=uuid4(),
            candidate_id=uuid4(),
            assessment_status=InterviewStatus.ACTIVE,
            created_at=now,
            generated_at=now,
            assigned_questions=(question,),
            progress=AssessmentProgressState(
                total_questions=1, attempted_questions=0, evaluated_questions=0
            ),
        )
