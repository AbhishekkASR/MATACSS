"""Derived assessment-level result aggregation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationResult
from app.models.interview import InterviewSession
from app.models.interview_question import InterviewQuestion
from app.models.question import Question
from app.models.submission import Submission
from app.services.database_service import InterviewSessionNotFoundError


async def get_assessment_results(
    session: AsyncSession, interview_session_id: UUID
) -> tuple[InterviewSession, list[dict]]:
    """Aggregate the latest attempt and evaluation for each assigned question."""
    interview = await session.scalar(
        select(InterviewSession).where(InterviewSession.id == interview_session_id)
    )
    if interview is None:
        raise InterviewSessionNotFoundError

    assignments = list(
        (
            await session.execute(
                select(InterviewQuestion, Question)
                .join(Question, Question.id == InterviewQuestion.question_id)
                .where(
                    InterviewQuestion.interview_session_id == interview_session_id
                )
                .order_by(InterviewQuestion.sequence_number.asc())
            )
        ).all()
    )
    submissions = list(
        (
            await session.scalars(
                select(Submission)
                .where(Submission.interview_session_id == interview_session_id)
                .order_by(Submission.created_at.desc(), Submission.id.desc())
            )
        ).all()
    )
    latest_by_question: dict[UUID, Submission] = {}
    for submission in submissions:
        latest_by_question.setdefault(submission.question_id, submission)

    submission_ids = [submission.id for submission in latest_by_question.values()]
    evaluations: dict[UUID, EvaluationResult] = {}
    if submission_ids:
        evaluations = {
            result.submission_id: result
            for result in (
                await session.scalars(
                    select(EvaluationResult).where(
                        EvaluationResult.submission_id.in_(submission_ids)
                    )
                )
            ).all()
        }

    results: list[dict] = []
    for assignment, question in assignments:
        latest = latest_by_question.get(question.id)
        evaluation = evaluations.get(latest.id) if latest else None
        if latest is None:
            evaluation_status = "not_attempted"
        elif evaluation is None:
            evaluation_status = "attempted_not_evaluated"
        else:
            evaluation_status = "evaluated"
        results.append(
            {
                "question_id": question.id,
                "sequence_number": assignment.sequence_number,
                "title": question.title,
                "difficulty": question.difficulty,
                "latest_submission_id": latest.id if latest else None,
                "latest_submission_status": latest.status if latest else None,
                "evaluation_status": evaluation_status,
                "score": evaluation.score if evaluation else None,
                "passed_test_cases": evaluation.passed_test_cases if evaluation else 0,
                "total_test_cases": evaluation.total_test_cases if evaluation else 0,
            }
        )
    return interview, results
