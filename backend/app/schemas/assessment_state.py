"""Sanitized, transportable assessment state for future orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.interview import InterviewStatus

AssessmentEvaluationStatus = Literal[
    "not_attempted", "attempted_not_evaluated", "evaluated"
]


class AssessmentStateValidationError(ValueError):
    """Raised when a constructed assessment snapshot violates its contract."""


class AssessmentQuestionState(BaseModel):
    """Public question context plus the latest safe attempt/evaluation summary."""

    model_config = ConfigDict(frozen=True)

    question_id: UUID
    sequence_number: int = Field(gt=0)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    difficulty: str = Field(min_length=1)
    expected_language: str | None = None
    latest_submission_id: UUID | None = None
    latest_submission_status: str | None = None
    latest_submission_created_at: datetime | None = None
    evaluation_result_id: UUID | None = None
    evaluation_status: AssessmentEvaluationStatus
    score: float | None = Field(default=None, ge=0, le=100)
    passed_test_cases: int = Field(default=0, ge=0)
    total_test_cases: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_attempt_and_evaluation_context(self) -> "AssessmentQuestionState":
        if self.latest_submission_id is None:
            if any(
                value is not None
                for value in (
                    self.latest_submission_status,
                    self.latest_submission_created_at,
                    self.evaluation_result_id,
                    self.score,
                )
            ) or self.passed_test_cases or self.total_test_cases:
                raise AssessmentStateValidationError(
                    "unattempted questions cannot include submission or evaluation data"
                )
            if self.evaluation_status != "not_attempted":
                raise AssessmentStateValidationError(
                    "unattempted questions must have not_attempted evaluation status"
                )
        elif self.latest_submission_status is None or self.latest_submission_created_at is None:
            raise AssessmentStateValidationError(
                "latest submission id requires status and creation timestamp"
            )
        elif self.evaluation_status == "not_attempted":
            raise AssessmentStateValidationError(
                "attempted questions cannot have not_attempted evaluation status"
            )

        if self.evaluation_status == "evaluated" and self.evaluation_result_id is None:
            raise AssessmentStateValidationError(
                "evaluated questions require an evaluation result id"
            )
        if self.evaluation_status != "evaluated" and (
            self.evaluation_result_id is not None
            or self.score is not None
            or self.passed_test_cases
            or self.total_test_cases
        ):
            raise AssessmentStateValidationError(
                "only evaluated questions can include evaluation results"
            )
        if self.passed_test_cases > self.total_test_cases:
            raise AssessmentStateValidationError(
                "passed test cases cannot exceed total test cases"
            )
        return self


class AssessmentProgressState(BaseModel):
    """Derived question progress; indexes are zero-based for agent consumers."""

    model_config = ConfigDict(frozen=True)

    total_questions: int = Field(ge=0)
    attempted_questions: int = Field(ge=0)
    evaluated_questions: int = Field(ge=0)
    current_question_index: int | None = Field(default=None, ge=0)


class AssessmentState(BaseModel):
    """Read-only runtime contract, deliberately independent of persistence/agents.

    This schema contains no submission source/stdin/output, test-case data, Docker
    details, credentials, or candidate PII. It is a point-in-time projection, not
    a persistence model or a second source of truth.
    """

    model_config = ConfigDict(frozen=True)

    interview_session_id: UUID
    candidate_id: UUID
    assessment_status: InterviewStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    generated_at: datetime
    assigned_questions: tuple[AssessmentQuestionState, ...] = ()
    current_question_id: UUID | None = None
    progress: AssessmentProgressState

    @model_validator(mode="after")
    def validate_invariants(self) -> "AssessmentState":
        questions = self.assigned_questions
        sequence_numbers = [question.sequence_number for question in questions]
        question_ids = [question.question_id for question in questions]
        if sequence_numbers != sorted(sequence_numbers) or len(set(sequence_numbers)) != len(sequence_numbers):
            raise AssessmentStateValidationError(
                "assigned questions must have unique ascending sequence numbers"
            )
        if len(set(question_ids)) != len(question_ids):
            raise AssessmentStateValidationError("assigned questions must be unique")
        if self.progress.total_questions != len(questions):
            raise AssessmentStateValidationError(
                "progress total_questions must equal assigned question count"
            )
        attempted = sum(question.latest_submission_id is not None for question in questions)
        evaluated = sum(question.evaluation_status == "evaluated" for question in questions)
        if (self.progress.attempted_questions, self.progress.evaluated_questions) != (
            attempted,
            evaluated,
        ):
            raise AssessmentStateValidationError(
                "progress counts must match assigned question contexts"
            )
        if self.progress.evaluated_questions > self.progress.attempted_questions:
            raise AssessmentStateValidationError(
                "evaluated questions cannot exceed attempted questions"
            )
        if self.assessment_status == InterviewStatus.ACTIVE:
            if self.completed_at is not None:
                raise AssessmentStateValidationError(
                    "active interviews cannot have a completion timestamp"
                )
            expected_index = next(
                (index for index, question in enumerate(questions) if question.latest_submission_id is None),
                None,
            )
            if self.progress.current_question_index != expected_index:
                raise AssessmentStateValidationError(
                    "active interview current question must be the first unattempted assignment"
                )
            expected_question_id = (
                questions[expected_index].question_id if expected_index is not None else None
            )
            if self.current_question_id != expected_question_id:
                raise AssessmentStateValidationError(
                    "current question id must match current question index"
                )
        elif self.completed_at is None:
            raise AssessmentStateValidationError(
                "closed interviews require a completion timestamp"
            )
        elif self.current_question_id is not None or self.progress.current_question_index is not None:
            raise AssessmentStateValidationError(
                "closed interviews cannot have a current question"
            )
        return self
