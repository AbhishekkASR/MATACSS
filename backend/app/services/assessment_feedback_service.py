"""Generate and persist advisory agent feedback without changing official scores."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_provider import LLMProviderError
from app.models.assessment_feedback import AssessmentFeedback
from app.services.assessment_orchestration_service import (
    AssessmentOrchestrationPreparationError,
    run_real_assessment_orchestration,
)
from app.services.database_service import (
    get_evaluation_result,
    get_submission_for_evaluation,
)

logger = logging.getLogger(__name__)


async def generate_submission_feedback(
    session: AsyncSession, submission_id: UUID
) -> AssessmentFeedback | None:
    """Generate one advisory report after official evaluation has committed.

    Completed reports are immutable on repeat calls. Failed or interrupted
    attempts can be retried; the unique submission key keeps persistence
    idempotent even if requests overlap.
    """
    submission = await get_submission_for_evaluation(session, submission_id)
    if await get_evaluation_result(session, submission_id) is None:
        return None

    try:
        feedback = await session.scalar(
            select(AssessmentFeedback).where(
                AssessmentFeedback.submission_id == submission_id
            )
        )
        if feedback is not None and feedback.status == "completed":
            return feedback
        if feedback is None:
            feedback = AssessmentFeedback(
                submission_id=submission_id,
                status="pending",
            )
            session.add(feedback)
        else:
            feedback.status = "pending"
            feedback.failure_kind = None
            feedback.interviewer_feedback = None
            feedback.reviewer_feedback = None
            feedback.edge_case_feedback = None
            feedback.aggregated_feedback = None
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning(
            "Could not initialize advisory feedback persistence",
            extra={"event": "assessment_feedback_persistence_failed"},
        )
        return None

    try:
        result = await run_real_assessment_orchestration(
            session,
            submission.interview_session_id,
            submission_id=submission_id,
        )
        feedback.interviewer_feedback = result.interviewer_decision.model_dump(
            mode="json"
        )
        feedback.reviewer_feedback = (
            result.code_review.model_dump(mode="json")
            if result.code_review is not None
            else None
        )
        feedback.edge_case_feedback = (
            result.edge_case_generation.model_dump(mode="json")
            if result.edge_case_generation is not None
            else None
        )
        feedback.aggregated_feedback = (
            result.feedback_result.model_dump(mode="json")
            if result.feedback_result is not None
            else None
        )
        feedback.status = "completed"
        feedback.failure_kind = None
    except LLMProviderError:
        await session.rollback()
        feedback = await _reload_feedback(session, submission_id)
        if feedback is None:
            return None
        feedback.status = "failed"
        feedback.failure_kind = "provider_error"
        _clear_feedback_payload(feedback)
        logger.warning(
            "Assessment feedback provider failed",
            extra={
                "event": "assessment_feedback_provider_failed",
                "submission_id": str(submission_id),
            },
        )
    except AssessmentOrchestrationPreparationError as exc:
        await session.rollback()
        feedback = await _reload_feedback(session, submission_id)
        if feedback is None:
            return None
        feedback.status = "failed"
        feedback.failure_kind = "context_error"
        _clear_feedback_payload(feedback)
        logger.warning(
            "Assessment feedback context was unavailable: %s",
            str(exc),
            extra={
                "event": "assessment_feedback_context_failed",
                "submission_id": str(submission_id),
                "failure_class": type(exc).__name__,
            },
        )
    except Exception as exc:
        await session.rollback()
        feedback = await _reload_feedback(session, submission_id)
        if feedback is None:
            return None
        feedback.status = "failed"
        feedback.failure_kind = "orchestration_error"
        _clear_feedback_payload(feedback)
        logger.warning(
            "Assessment feedback orchestration failed (%s)",
            type(exc).__name__,
            extra={
                "event": "assessment_feedback_orchestration_failed",
                "submission_id": str(submission_id),
            },
        )

    try:
        await session.commit()
        await session.refresh(feedback)
        return feedback
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Could not persist advisory feedback result",
            extra={
                "event": "assessment_feedback_persistence_failed",
                "submission_id": str(submission_id),
            },
        )
        return None


async def _reload_feedback(
    session: AsyncSession, submission_id: UUID
) -> AssessmentFeedback | None:
    return await session.scalar(
        select(AssessmentFeedback).where(
            AssessmentFeedback.submission_id == submission_id
        )
    )


def _clear_feedback_payload(feedback: AssessmentFeedback) -> None:
    feedback.interviewer_feedback = None
    feedback.reviewer_feedback = None
    feedback.edge_case_feedback = None
    feedback.aggregated_feedback = None
