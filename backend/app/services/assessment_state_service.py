"""Build the shared assessment-state snapshot from authoritative services."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationResult
from app.models.submission import Submission
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)
from app.services.database_service import list_assigned_questions
from app.services.results_service import get_assessment_results


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize database timestamps so this state is safe across consumers."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def build_assessment_state(
    session: AsyncSession, interview_session_id: UUID
) -> AssessmentState:
    """Return a sanitized, non-persistent assessment snapshot.

    Existing assignment and results services remain authoritative for ordering and
    latest-attempt/evaluation semantics. Extra identifier/timestamp lookups only
    enrich that derived data without exposing submission or test-case contents.
    """
    interview, result_rows = await get_assessment_results(session, interview_session_id)
    assignments = await list_assigned_questions(session, interview_session_id)
    result_by_question = {row["question_id"]: row for row in result_rows}

    latest_ids = [
        row["latest_submission_id"]
        for row in result_rows
        if row["latest_submission_id"] is not None
    ]
    latest_submissions: dict[UUID, Submission] = {}
    evaluations: dict[UUID, EvaluationResult] = {}
    if latest_ids:
        latest_submissions = {
            submission.id: submission
            for submission in (
                await session.scalars(select(Submission).where(Submission.id.in_(latest_ids)))
            ).all()
        }
        evaluations = {
            evaluation.submission_id: evaluation
            for evaluation in (
                await session.scalars(
                    select(EvaluationResult).where(EvaluationResult.submission_id.in_(latest_ids))
                )
            ).all()
        }

    questions: list[AssessmentQuestionState] = []
    for assignment, question in assignments:
        row = result_by_question[question.id]
        latest_id = row["latest_submission_id"]
        latest = latest_submissions.get(latest_id) if latest_id else None
        evaluation = evaluations.get(latest_id) if latest_id else None
        questions.append(
            AssessmentQuestionState(
                question_id=question.id,
                sequence_number=assignment.sequence_number,
                title=question.title,
                description=question.description,
                difficulty=question.difficulty,
                expected_language=question.expected_language,
                latest_submission_id=latest_id,
                latest_submission_status=row["latest_submission_status"],
                latest_submission_created_at=_as_utc(latest.created_at) if latest else None,
                evaluation_result_id=evaluation.id if evaluation else None,
                evaluation_status=row["evaluation_status"],
                score=row["score"],
                passed_test_cases=row["passed_test_cases"],
                total_test_cases=row["total_test_cases"],
            )
        )

    current_index = next(
        (index for index, question in enumerate(questions) if question.latest_submission_id is None),
        None,
    ) if interview.status == "active" else None
    return AssessmentState(
        interview_session_id=interview.id,
        candidate_id=interview.candidate_id,
        assessment_status=interview.status,
        started_at=_as_utc(interview.started_at),
        completed_at=_as_utc(interview.completed_at),
        created_at=_as_utc(interview.created_at),
        generated_at=datetime.now(timezone.utc),
        assigned_questions=tuple(questions),
        current_question_id=(questions[current_index].question_id if current_index is not None else None),
        progress=AssessmentProgressState(
            total_questions=len(questions),
            attempted_questions=sum(question.latest_submission_id is not None for question in questions),
            evaluated_questions=sum(question.evaluation_status == "evaluated" for question in questions),
            current_question_index=current_index,
        ),
    )
