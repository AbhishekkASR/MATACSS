"""Application boundary between persisted assessment data and agent inputs."""

from __future__ import annotations

import asyncio
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_provider import OpenAILLMProvider
from app.models.submission import Submission
from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewerProvider,
    DeterministicCodeReviewerProvider,
    ReviewExecutionSummary,
)
from app.orchestration.edge_case_generator import (
    DeterministicEdgeCaseGeneratorProvider,
    EdgeCaseExecutionSummary,
    EdgeCaseGeneratorInput,
    EdgeCaseGeneratorProvider,
)
from app.orchestration.llm_agent_providers import (
    LLMCodeReviewerProvider,
    LLMEdgeCaseGeneratorProvider,
    LLMInterviewerProvider,
)
from app.orchestration.assessment_graph import (
    AssessmentGraphResult,
    invoke_assessment_graph,
)
from app.orchestration.interviewer import InterviewerProvider
from app.orchestration.interviewer import DeterministicInterviewerProvider
from app.schemas.assessment_state import AssessmentState
from app.services.assessment_state_service import build_assessment_state
from app.services.database_service import (
    SubmissionAttemptNotFoundError,
    get_evaluation_result,
    get_submission_for_evaluation,
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
    feedback_question_id: UUID | None = None


async def prepare_real_assessment_context(
    session: AsyncSession,
    interview_session_id: UUID,
    submission_id: UUID | None = None,
) -> RealAssessmentOrchestrationContext:
    """Prepare bounded agent inputs without exposing persistence to agents."""
    assessment = await build_assessment_state(session, interview_session_id)
    current_id = assessment.current_question_id
    if assessment.assessment_status != "active" or (
        current_id is None and submission_id is None
    ):
        return RealAssessmentOrchestrationContext(assessment_state=assessment)

    target_submission: Submission | None = None
    if submission_id is not None:
        target_submission = await get_submission_for_evaluation(session, submission_id)
        if target_submission.interview_session_id != interview_session_id:
            raise AssessmentOrchestrationPreparationError(
                "submission does not belong to the selected assessment"
            )
        target_question_id = target_submission.question_id
    else:
        target_question_id = current_id

    question = next(
        (
            item
            for item in assessment.assigned_questions
            if item.question_id == target_question_id
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

    latest = target_submission
    if submission_id is None:
        try:
            latest = await get_latest_submission(
                session, assessment.interview_session_id, target_question_id
            )
        except SubmissionAttemptNotFoundError:
            pass

    if latest is not None and (
        latest.interview_session_id != assessment.interview_session_id
        or latest.question_id != target_question_id
    ):
        raise AssessmentOrchestrationPreparationError(
            "latest submission does not belong to the selected assessment question"
        )
    evaluation = await get_evaluation_result(session, latest.id) if latest else None
    if submission_id is not None and evaluation is None:
        raise AssessmentOrchestrationPreparationError(
            "submission must have a persisted official evaluation before feedback"
        )

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
            question_id=question.question_id,
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
        question_id=question.question_id,
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
        feedback_question_id=question.question_id if submission_id is not None else None,
    )


async def run_real_assessment_orchestration(
    session: AsyncSession,
    interview_session_id: UUID,
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
    edge_case_generator_provider: EdgeCaseGeneratorProvider | None = None,
    submission_id: UUID | None = None,
) -> AssessmentGraphResult:
    """Run the graph with configured LLM agents and an authoritative snapshot.

    Explicitly injected agent providers remain useful for deterministic operation
    and tests. Otherwise, one configured OpenAI/Azure adapter backs the LLM agents.
    """
    context = await prepare_real_assessment_context(
        session, interview_session_id, submission_id
    )
    llm_provider = None
    has_current_question = (
        context.assessment_state.assessment_status == "active"
        and context.assessment_state.current_question_id is not None
        and bool(context.assessment_state.assigned_questions)
    )
    use_llm_interviewer = interviewer_provider is None and has_current_question
    if (
        interviewer_provider is None
        and submission_id is not None
        and context.assessment_state.assessment_status == "active"
        and context.assessment_state.assigned_questions
    ):
        use_llm_interviewer = True
    use_llm_reviewer = (
        code_reviewer_provider is None
        and context.review_input is not None
    )
    use_llm_edge_case_generator = edge_case_generator_provider is None and (
        has_current_question or context.edge_case_input is not None
    )
    if use_llm_interviewer or use_llm_reviewer or use_llm_edge_case_generator:
        llm_provider = OpenAILLMProvider()
    if interviewer_provider is None:
        interviewer_provider = (
            LLMInterviewerProvider(llm_provider)
            if use_llm_interviewer and llm_provider is not None
            else DeterministicInterviewerProvider()
        )
    if code_reviewer_provider is None:
        code_reviewer_provider = (
            LLMCodeReviewerProvider(llm_provider)
            if use_llm_reviewer and llm_provider is not None
            else DeterministicCodeReviewerProvider()
        )
    if edge_case_generator_provider is None:
        edge_case_generator_provider = (
            LLMEdgeCaseGeneratorProvider(llm_provider)
            if use_llm_edge_case_generator and llm_provider is not None
            else DeterministicEdgeCaseGeneratorProvider()
        )

    return await asyncio.to_thread(
        invoke_assessment_graph,
        context.assessment_state,
        interviewer_provider=interviewer_provider,
        code_reviewer_provider=code_reviewer_provider,
        edge_case_generator_provider=edge_case_generator_provider,
        review_input=context.review_input,
        edge_case_input=context.edge_case_input,
        feedback_question_id=context.feedback_question_id,
    )
