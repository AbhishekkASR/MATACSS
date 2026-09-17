"""Application boundary between persisted assessment data and agent inputs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewerProvider,
    ReviewExecutionSummary,
)
from app.orchestration.edge_case_generator import (
    EdgeCaseExecutionSummary,
    EdgeCaseGeneratorInput,
    EdgeCaseGeneratorProvider,
)
from app.orchestration.assessment_graph import (
    AssessmentGraphResult,
    invoke_assessment_graph,
)
from app.orchestration.interviewer import InterviewerProvider
from app.schemas.assessment_state import AssessmentState
from app.services.assessment_state_service import build_assessment_state
from app.services.database_service import (
    SubmissionAttemptNotFoundError,
    get_evaluation_result,
    get_latest_submission,
)


class AssessmentOrchestrationPreparationError(ValueError):
    """Raised when persisted assessment context cannot form safe agent inputs."""


class RealAssessmentOrchestrationContext(BaseModel):
    """Safe runtime handoff assembled from authoritative application services."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_state: AssessmentState
    review_input: CodeReviewInput | None = None
    edge_case_input: EdgeCaseGeneratorInput | None = None
    latest_submission_id: UUID | None = None
    latest_submission_status: str | None = Field(default=None, max_length=50)


async def prepare_real_assessment_context(
    session: AsyncSession,
    interview_session_id: UUID,
) -> RealAssessmentOrchestrationContext:
    """Prepare bounded agent inputs without exposing persistence to agents."""
    assessment = await build_assessment_state(session, interview_session_id)
    current_id = assessment.current_question_id
    if current_id is None or assessment.assessment_status != "active":
        return RealAssessmentOrchestrationContext(assessment_state=assessment)

    question = next(
        (
            item
            for item in assessment.assigned_questions
            if item.question_id == current_id
        ),
        None,
    )
    if question is None:
        raise AssessmentOrchestrationPreparationError(
            "current question is not assigned to the assessment"
        )
    if question.expected_language not in {"python", "cpp", "java"}:
        raise AssessmentOrchestrationPreparationError(
            "current question has an unsupported orchestration language"
        )

    latest = None
    try:
        latest = await get_latest_submission(session, assessment.interview_session_id, current_id)
    except SubmissionAttemptNotFoundError:
        pass

    if latest is not None and (
        latest.interview_session_id != assessment.interview_session_id
        or latest.question_id != current_id
    ):
        raise AssessmentOrchestrationPreparationError(
            "latest submission does not belong to the selected assessment question"
        )
    evaluation = await get_evaluation_result(session, latest.id) if latest else None

    evaluation_status = (
        "not_attempted"
        if latest is None
        else "evaluated"
        if evaluation is not None
        else "attempted_not_evaluated"
    )
    score = evaluation.score if evaluation is not None else None
    passed_test_cases = evaluation.passed_test_cases if evaluation is not None else 0
    total_test_cases = evaluation.total_test_cases if evaluation is not None else 0
    review_summary = ReviewExecutionSummary(
        submission_status=latest.status if latest else None,
        evaluation_status=evaluation_status,
        score=score,
        passed_test_cases=passed_test_cases,
        total_test_cases=total_test_cases,
    )
    edge_summary = EdgeCaseExecutionSummary(
        evaluation_status=evaluation_status,
        score=score,
        passed_test_cases=passed_test_cases,
        total_test_cases=total_test_cases,
    )
    review_input = (
        CodeReviewInput(
            question_id=current_id,
            question_title=question.title,
            question_prompt=question.description,
            language=question.expected_language,
            source_code=latest.source_code,
            execution_summary=review_summary,
        )
        if latest is not None
        else None
    )
    edge_input = EdgeCaseGeneratorInput(
        question_id=current_id,
        question_title=question.title,
        question_prompt=question.description,
        language=question.expected_language,
        execution_summary=edge_summary,
    )
    return RealAssessmentOrchestrationContext(
        assessment_state=assessment,
        review_input=review_input,
        edge_case_input=edge_input,
        latest_submission_id=latest.id if latest else None,
        latest_submission_status=latest.status if latest else None,
    )


async def run_real_assessment_orchestration(
    session: AsyncSession,
    interview_session_id: UUID,
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
    edge_case_generator_provider: EdgeCaseGeneratorProvider | None = None,
) -> AssessmentGraphResult:
    """Run the graph from an authoritative persisted-assessment snapshot."""
    context = await prepare_real_assessment_context(session, interview_session_id)
    return invoke_assessment_graph(
        context.assessment_state,
        interviewer_provider=interviewer_provider,
        code_reviewer_provider=code_reviewer_provider,
        edge_case_generator_provider=edge_case_generator_provider,
        review_input=context.review_input,
        edge_case_input=context.edge_case_input,
    )
