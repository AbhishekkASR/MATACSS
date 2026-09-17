"""Deterministic feedback aggregation for the assessment graph."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.interview import InterviewStatus
from app.orchestration.code_reviewer import CodeReviewResult
from app.orchestration.edge_case_generator import EdgeCaseGenerationResult
from app.orchestration.interviewer import InterviewerDecision
from app.orchestration.multi_agent_orchestrator import MultiAgentOrchestrationResult
from app.schemas.assessment_state import AssessmentState

MAX_TEXT = 1_000
MAX_ITEMS = 20
MAX_SUGGESTIONS = 10


class FeedbackSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FeedbackCategory(StrEnum):
    ASSESSMENT = "assessment"
    QUESTION = "question"
    CODE_QUALITY = "code_quality"
    EDGE_CASE = "edge_case"
    EVALUATION = "evaluation"


class FeedbackStatus(StrEnum):
    GENERATED = "generated"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"


class AssessmentFeedback(BaseModel):
    """Official evaluation context plus AI feedback context, which remains advisory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: FeedbackStatus
    summary: str = Field(min_length=1, max_length=MAX_TEXT)
    observations: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)
    score: float | None = Field(default=None, ge=0, le=100)
    passed_test_cases: int | None = Field(default=None, ge=0)
    total_test_cases: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_integrity(self) -> "AssessmentFeedback":
        if self.passed_test_cases is not None and self.total_test_cases is not None:
            if self.passed_test_cases > self.total_test_cases:
                raise ValueError("passed test cases cannot exceed total test cases")
        return self


class QuestionFeedback(BaseModel):
    """Selected-question guidance without mutating the assessment or its assignments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: UUID | None = None
    question_title: str | None = Field(default=None, max_length=500)
    status: FeedbackStatus
    summary: str = Field(min_length=1, max_length=MAX_TEXT)
    guidance: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def validate_question_state(self) -> "QuestionFeedback":
        if self.status == FeedbackStatus.GENERATED and self.question_id is None:
            raise ValueError("generated question feedback requires a question id")
        return self


class CodeQualityFeedback(BaseModel):
    """Static review observations aggregated into one bounded result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: FeedbackStatus
    summary: str = Field(min_length=1, max_length=MAX_TEXT)
    observations: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)
    suggestions: tuple[str, ...] = Field(default=(), max_length=MAX_SUGGESTIONS)


class EdgeCaseFeedback(BaseModel):
    """Candidate edge cases remain advisory and unverified unless later executed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: FeedbackStatus
    summary: str = Field(min_length=1, max_length=MAX_TEXT)
    categories: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)
    unverified_count: int = Field(default=0, ge=0, le=MAX_ITEMS)
    guidance: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)


class FeedbackAggregationResult(BaseModel):
    """One deterministic final feedback layer result for this graph run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment: AssessmentFeedback
    question: QuestionFeedback
    code_quality: CodeQualityFeedback | None = None
    edge_cases: EdgeCaseFeedback | None = None
    status: FeedbackStatus
    reason: str = Field(min_length=1, max_length=MAX_TEXT)


class FeedbackAggregationInput(BaseModel):
    """Input accepted by the feedback aggregator; it is deliberately narrow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_state: AssessmentState
    interviewer_decision: InterviewerDecision | None = None
    code_review: CodeReviewResult | None = None
    edge_case_generation: EdgeCaseGenerationResult | None = None
    orchestration_result: MultiAgentOrchestrationResult | None = None


@runtime_checkable
class FeedbackAggregatorProvider(Protocol):
    """Provider boundary for deterministic, non-LLM feedback aggregation."""

    def aggregate(self, aggregation_input: FeedbackAggregationInput) -> FeedbackAggregationResult:
        """Combine official evaluation results with bounded agent observations."""


class DeterministicFeedbackAggregator:
    """Safe deterministic aggregator. It never executes code, Docker, or PostgreSQL."""

    def aggregate(
        self, aggregation_input: FeedbackAggregationInput
    ) -> FeedbackAggregationResult:
        validated = FeedbackAggregationInput.model_validate(aggregation_input)
        assessment = validated.assessment_state
        decision = validated.interviewer_decision
        review = validated.code_review
        edge_cases = validated.edge_case_generation
        orchestration = validated.orchestration_result

        question = None
        if decision is not None and decision.question_id is not None:
            question = next(
                (
                    assigned
                    for assigned in assessment.assigned_questions
                    if assigned.question_id == decision.question_id
                ),
                None,
            )
        elif assessment.current_question_id is not None:
            question = next(
                (
                    assigned
                    for assigned in assessment.assigned_questions
                    if assigned.question_id == assessment.current_question_id
                ),
                None,
            )

        if assessment.assessment_status != InterviewStatus.ACTIVE:
            assessment_status = FeedbackStatus.BLOCKED
            assessment_summary = (
                f"Assessment is {assessment.assessment_status}; no new evaluation or AI feedback is generated."
            )
            assessment_observations = (
                "Official execution/evaluation results remain authoritative for correctness and scoring.",
            )
            score = None
            passed = None
            total = None
        elif question is None:
            assessment_status = FeedbackStatus.INCOMPLETE
            assessment_summary = "No current question was available to report evaluation feedback."
            assessment_observations = (
                "Official evaluation remains authoritative when a valid current question exists.",
            )
            score = None
            passed = None
            total = None
        elif question.evaluation_status == "evaluated":
            assessment_status = FeedbackStatus.GENERATED
            score = question.score
            passed = question.passed_test_cases
            total = question.total_test_cases
            assessment_summary = (
                f"Official evaluation is authoritative: {passed}/{total} tests passed for the selected question "
                f"with score {score:.1f}/100. AI observations remain advisory."
            )
            assessment_observations = (
                "Deterministic execution/evaluation is authoritative for pass/fail decisions and score.",
                "AI feedback below summarizes static or candidate-side observations only.",
            )
        elif question.evaluation_status == "attempted_not_evaluated":
            assessment_status = FeedbackStatus.INCOMPLETE
            score = None
            passed = None
            total = None
            assessment_summary = (
                "A submission exists, but the official evaluation has not completed. "
                "AI feedback is advisory until deterministic evaluation finishes."
            )
            assessment_observations = (
                "Official evaluation remains pending and is the only source of correctness claims.",
            )
        else:
            assessment_status = FeedbackStatus.INCOMPLETE
            score = None
            passed = None
            total = None
            assessment_summary = (
                "No official evaluation result is available yet for this question. "
                "The agent layer is limited to advisory static observations."
            )
            assessment_observations = (
                "No execution result has been recorded for this question yet.",
            )

        if decision is not None and decision.question_id is not None:
            question_feedback_status = FeedbackStatus.GENERATED
            question_summary = (
                f"Question feedback for '{decision.question_title or 'selected question'}' is advisory and safe."
            )
            guidance = [
                "Keep the public prompt and official evaluation as the source of truth for correctness.",
                "Treat static review and generated edge cases as candidate guidance only.",
            ]
            if review is not None and review.improvement_suggestions:
                guidance.append(review.improvement_suggestions[0])
            if edge_cases is not None and edge_cases.cases:
                guidance.append(
                    f"{len(edge_cases.cases)} generated edge cases were proposed and remain unverified by default."
                )
            question_feedback = QuestionFeedback(
                question_id=decision.question_id,
                question_title=decision.question_title,
                status=question_feedback_status,
                summary=question_summary,
                guidance=tuple(guidance[:10]),
            )
        elif assessment.assessment_status != InterviewStatus.ACTIVE:
            question_feedback = QuestionFeedback(
                question_id=None,
                question_title=None,
                status=FeedbackStatus.BLOCKED,
                summary="The assessment is closed, so no interview guidance is produced.",
                guidance=(),
            )
        else:
            question_feedback = QuestionFeedback(
                question_id=None,
                question_title=None,
                status=FeedbackStatus.INCOMPLETE,
                summary="No valid question decision exists to create interview guidance.",
                guidance=(),
            )

        if review is None or review.review_status == "not_run":
            code_quality = CodeQualityFeedback(
                status=FeedbackStatus.INCOMPLETE,
                summary="No static review input was available for this question.",
                observations=(),
                suggestions=(),
            )
        else:
            code_quality = CodeQualityFeedback(
                status=FeedbackStatus.GENERATED,
                summary=(
                    "Static review completed; these observations are advisory because only deterministic "
                    "execution/evaluation can establish correctness."
                ),
                observations=tuple(
                    observation.message for observation in review.observations[:MAX_ITEMS]
                )
                or ("No static review warnings were raised for this submission.",),
                suggestions=tuple(review.improvement_suggestions[:MAX_SUGGESTIONS]),
            )

        if edge_cases is None:
            edge_case_feedback = EdgeCaseFeedback(
                status=FeedbackStatus.INCOMPLETE,
                summary="No edge-case generation output was produced for this question.",
                categories=(),
                unverified_count=0,
                guidance=(),
            )
        else:
            categories = tuple(case.category.value for case in edge_cases.cases[:MAX_ITEMS])
            unverified_count = sum(
                1 for case in edge_cases.cases if case.verification_status == "unverified"
            )
            guidance = (
                "Generated edge cases remain candidate ideas until an official execution run verifies them.",
            )
            if edge_cases.cases:
                guidance = guidance + (
                    f"{len(edge_cases.cases)} candidate cases were proposed, and {unverified_count} remain unverified.",
                )
            edge_case_feedback = EdgeCaseFeedback(
                status=(
                    FeedbackStatus.GENERATED
                    if edge_cases.cases
                    else FeedbackStatus.INCOMPLETE
                ),
                summary=(
                    "Generated edge cases are advisory only and do not modify the official test-case set."
                ),
                categories=categories,
                unverified_count=unverified_count,
                guidance=guidance[:MAX_ITEMS],
            )

        final_status = (
            FeedbackStatus.BLOCKED
            if assessment.assessment_status != InterviewStatus.ACTIVE
            else FeedbackStatus.GENERATED
            if question_feedback.status == FeedbackStatus.GENERATED
            else FeedbackStatus.INCOMPLETE
        )

        result = FeedbackAggregationResult(
            assessment=AssessmentFeedback(
                status=assessment_status,
                summary=assessment_summary,
                observations=assessment_observations,
                score=score,
                passed_test_cases=passed,
                total_test_cases=total,
            ),
            question=question_feedback,
            code_quality=code_quality,
            edge_cases=edge_case_feedback,
            status=final_status,
            reason=(
                "Deterministic evaluation is authoritative; AI feedback remains advisory and bounded."
                if final_status == FeedbackStatus.GENERATED
                else "The assessment is closed or incomplete; no expanded AI feedback was generated."
            ),
        )
        return result


class FeedbackAggregator:
    """Compatibility wrapper around the deterministic provider."""

    def __init__(self, provider: FeedbackAggregatorProvider | None = None) -> None:
        self._provider = provider or DeterministicFeedbackAggregator()

    def aggregate(self, aggregation_input: FeedbackAggregationInput) -> FeedbackAggregationResult:
        try:
            result = self._provider.aggregate(aggregation_input)
            return FeedbackAggregationResult.model_validate(result)
        except (TypeError, ValidationError, ValueError) as exc:
            raise ValueError("feedback aggregator rejected the provider output") from exc
