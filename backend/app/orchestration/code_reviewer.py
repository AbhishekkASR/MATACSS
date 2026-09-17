"""Bounded static code review node and provider contract."""

from __future__ import annotations

import ast
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.interview import InterviewStatus
from app.orchestration.state_adapter import validate_assessment_state
from app.schemas.assessment_state import AssessmentEvaluationStatus, AssessmentState

ReviewLanguage = Literal["python", "cpp", "java"]


class CodeReviewerAgentError(ValueError):
    """Raised when code review cannot be safely performed."""


class ReviewStatus(StrEnum):
    """Constrained outcomes for the static reviewer."""

    NOT_RUN = "not_run"
    COMPLETED = "completed"
    PARSE_ERROR = "parse_error"


class ReviewObservationCategory(StrEnum):
    CORRECTNESS = "correctness"
    CODE_QUALITY = "code_quality"
    COMPLEXITY = "complexity"
    MAINTAINABILITY = "maintainability"
    STATIC_ISSUE = "static_issue"


class ReviewSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReviewExecutionSummary(BaseModel):
    """Optional safe execution/evaluation aggregate supplied by the caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    submission_status: str | None = Field(default=None, max_length=50)
    evaluation_status: AssessmentEvaluationStatus | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    passed_test_cases: int | None = Field(default=None, ge=0)
    total_test_cases: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_case_counts(self) -> "ReviewExecutionSummary":
        if (
            self.passed_test_cases is not None
            and self.total_test_cases is not None
            and self.passed_test_cases > self.total_test_cases
        ):
            raise ValueError("passed test cases cannot exceed total test cases")
        return self


class CodeReviewInput(BaseModel):
    """Explicit minimum review payload; no hidden evaluation data is accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: UUID
    question_title: str = Field(min_length=1, max_length=500)
    question_prompt: str = Field(min_length=1, max_length=20_000)
    language: ReviewLanguage
    source_code: str = Field(max_length=100_000)
    execution_summary: ReviewExecutionSummary | None = None


class CodeReviewObservation(BaseModel):
    """A bounded static observation with explicit category and severity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: ReviewObservationCategory
    severity: ReviewSeverity
    message: str = Field(min_length=1, max_length=500)


class CodeReviewResult(BaseModel):
    """Structured, non-executing result from a CodeReviewerProvider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_status: ReviewStatus
    question_id: UUID | None = None
    correctness_summary: str = Field(min_length=1, max_length=500)
    observations: tuple[CodeReviewObservation, ...] = Field(default=(), max_length=20)
    improvement_suggestions: tuple[
        Annotated[str, Field(min_length=1, max_length=500)], ...
    ] = Field(default=(), max_length=10)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_review_context(self) -> "CodeReviewResult":
        if self.review_status == ReviewStatus.NOT_RUN:
            if self.question_id is not None or self.observations or self.improvement_suggestions:
                raise ValueError("not_run reviews cannot include question findings")
        elif self.question_id is None:
            raise ValueError("completed and parse_error reviews require a question id")
        return self


@runtime_checkable
class CodeReviewerProvider(Protocol):
    """Provider boundary for a future real LLM-backed reviewer."""

    def review(self, review_input: CodeReviewInput) -> CodeReviewResult:
        """Review only the explicitly supplied source and public context."""


class DeterministicCodeReviewerProvider:
    """Conservative standard-library static reviewer that never executes source."""

    def review(self, review_input: CodeReviewInput) -> CodeReviewResult:
        review_input = CodeReviewInput.model_validate(review_input)
        source = review_input.source_code
        if not source.strip():
            return CodeReviewResult(
                review_status=ReviewStatus.PARSE_ERROR,
                question_id=review_input.question_id,
                correctness_summary="Runtime correctness cannot be assessed because the source is empty.",
                observations=(
                    CodeReviewObservation(
                        category=ReviewObservationCategory.STATIC_ISSUE,
                        severity=ReviewSeverity.ERROR,
                        message="The submitted source code is empty.",
                    ),
                ),
                improvement_suggestions=("Provide an implementation before submitting for review.",),
                reason="Static review found no source to analyze.",
            )

        observations = [
            CodeReviewObservation(
                category=ReviewObservationCategory.CORRECTNESS,
                severity=ReviewSeverity.INFO,
                message="Static review cannot establish runtime correctness or test-case coverage.",
            ),
            CodeReviewObservation(
                category=ReviewObservationCategory.COMPLEXITY,
                severity=ReviewSeverity.INFO,
                message="Time and space complexity cannot be determined reliably from this bounded static review.",
            ),
        ]
        if review_input.language == "python":
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                detail = exc.msg or "invalid syntax"
                return CodeReviewResult(
                    review_status=ReviewStatus.PARSE_ERROR,
                    question_id=review_input.question_id,
                    correctness_summary="Runtime correctness cannot be assessed because Python parsing failed.",
                    observations=(
                        CodeReviewObservation(
                            category=ReviewObservationCategory.STATIC_ISSUE,
                            severity=ReviewSeverity.ERROR,
                            message=f"Python parse error: {detail}.",
                        ),
                    ),
                    improvement_suggestions=("Fix the Python syntax error before further review.",),
                    reason="Python standard-library parsing failed.",
                )
            if any(
                isinstance(node, ast.While)
                and isinstance(node.test, ast.Constant)
                and node.test.value is True
                for node in ast.walk(tree)
            ):
                observations.append(
                    CodeReviewObservation(
                        category=ReviewObservationCategory.STATIC_ISSUE,
                        severity=ReviewSeverity.WARNING,
                        message="A `while True` loop needs an explicit, reviewable termination path.",
                    )
                )
        if "TODO" in source or "FIXME" in source:
            observations.append(
                CodeReviewObservation(
                    category=ReviewObservationCategory.MAINTAINABILITY,
                    severity=ReviewSeverity.WARNING,
                    message="The source contains TODO or FIXME markers that should be resolved or documented.",
                )
            )
        if any(len(line) > 120 for line in source.splitlines()):
            observations.append(
                CodeReviewObservation(
                    category=ReviewObservationCategory.CODE_QUALITY,
                    severity=ReviewSeverity.INFO,
                    message="Some lines exceed 120 characters and may be harder to read.",
                )
            )

        return CodeReviewResult(
            review_status=ReviewStatus.COMPLETED,
            question_id=review_input.question_id,
            correctness_summary="Static review cannot establish runtime correctness.",
            observations=tuple(observations),
            improvement_suggestions=(
                "Validate the implementation with the assessment's authorized execution and evaluation flow.",
            ),
            reason="Deterministic static review completed without executing candidate code.",
        )


def validate_code_review_input(value: object | None) -> CodeReviewInput | None:
    """Validate explicit review input without fetching data from persistence."""
    if value is None:
        return None
    raw_value = value.model_dump(mode="python") if isinstance(value, CodeReviewInput) else value
    try:
        return CodeReviewInput.model_validate(raw_value)
    except ValidationError as exc:
        raise CodeReviewerAgentError("code reviewer requires a valid CodeReviewInput") from exc


def validate_code_review_result(value: object) -> CodeReviewResult:
    """Revalidate provider output, including models constructed without validation."""
    raw_value = value.model_dump(mode="python") if isinstance(value, CodeReviewResult) else value
    try:
        return CodeReviewResult.model_validate(raw_value)
    except ValidationError as exc:
        raise CodeReviewerAgentError("provider returned an invalid code review result") from exc


class CodeReviewerAgent:
    """Static review agent with no execution, Docker, or persistence authority."""

    def __init__(self, provider: CodeReviewerProvider) -> None:
        self._provider = provider

    def review(
        self, assessment_state: AssessmentState | object, review_input: CodeReviewInput | object | None
    ) -> CodeReviewResult:
        try:
            assessment = validate_assessment_state(assessment_state)
        except ValueError as exc:
            raise CodeReviewerAgentError("code reviewer requires a valid AssessmentState") from exc
        review = validate_code_review_input(review_input)
        if review is None:
            return CodeReviewResult(
                review_status=ReviewStatus.NOT_RUN,
                correctness_summary="No source was supplied for static review.",
                reason="No review input or submission was supplied to the orchestration layer.",
            )
        if assessment.assessment_status != InterviewStatus.ACTIVE:
            return CodeReviewResult(
                review_status=ReviewStatus.NOT_RUN,
                correctness_summary="Static review was not run because the assessment is closed.",
                reason=f"Assessment is {assessment.assessment_status}.",
            )

        assigned_question = next(
            (
                question
                for question in assessment.assigned_questions
                if question.question_id == review.question_id
            ),
            None,
        )
        if assigned_question is None:
            raise CodeReviewerAgentError("review input question is not assigned to this assessment")
        if (
            review.question_title != assigned_question.title
            or review.question_prompt != assigned_question.description
        ):
            raise CodeReviewerAgentError("review input question context does not match AssessmentState")

        try:
            provider_output = self._provider.review(review)
            result = validate_code_review_result(provider_output)
        except (TypeError, ValidationError, ValueError) as exc:
            raise CodeReviewerAgentError("provider returned an invalid code review result") from exc
        if result.review_status == ReviewStatus.NOT_RUN:
            raise CodeReviewerAgentError("provider cannot skip an explicitly supplied active review")
        if result.question_id != review.question_id:
            raise CodeReviewerAgentError("provider returned a review for a different question")
        return result
