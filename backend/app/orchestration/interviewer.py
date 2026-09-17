"""Bounded interviewer decision node and provider contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.interview import InterviewStatus
from app.orchestration.state_adapter import validate_assessment_state
from app.schemas.assessment_state import AssessmentState


class InterviewerAgentError(ValueError):
    """Raised when an interviewer decision cannot be safely produced."""


class InterviewerDecisionType(StrEnum):
    """Constrained actions available to the interviewer node in Step 27."""

    PRESENT_QUESTION = "present_question"
    NO_ASSIGNED_QUESTIONS = "no_assigned_questions"
    ALL_QUESTIONS_ATTEMPTED = "all_questions_attempted"
    ASSESSMENT_CLOSED = "assessment_closed"


class InterviewerProviderSelection(BaseModel):
    """Minimal provider output, validated against the authoritative snapshot."""

    model_config = ConfigDict(frozen=True)

    selected_question_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    interviewer_message: str | None = Field(default=None, max_length=1_000)


@runtime_checkable
class InterviewerProvider(Protocol):
    """Provider boundary for a future real LLM integration."""

    def select_question(
        self, assessment_state: AssessmentState
    ) -> InterviewerProviderSelection:
        """Return a proposed question selection using only the supplied snapshot."""


class DeterministicInterviewerProvider:
    """Development provider that always selects the state-defined current question."""

    def select_question(
        self, assessment_state: AssessmentState
    ) -> InterviewerProviderSelection:
        assessment = validate_assessment_state(assessment_state)
        if assessment.current_question_id is None:
            raise InterviewerAgentError("active assessment has no current question")
        return InterviewerProviderSelection(
            selected_question_id=assessment.current_question_id,
            reason="The first unattempted assigned question is the current question.",
            interviewer_message="Please work through the current assigned question.",
        )


class InterviewerDecision(BaseModel):
    """Safe structured decision returned by the interviewer graph node."""

    model_config = ConfigDict(frozen=True)

    decision_type: InterviewerDecisionType
    question_id: UUID | None = None
    question_sequence_number: int | None = Field(default=None, gt=0)
    question_index: int | None = Field(default=None, ge=0)
    question_title: str | None = None
    question_prompt: str | None = None
    reason: str = Field(min_length=1, max_length=500)
    interviewer_message: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_question_context(self) -> "InterviewerDecision":
        question_fields = (
            self.question_id,
            self.question_sequence_number,
            self.question_index,
            self.question_title,
            self.question_prompt,
        )
        if self.decision_type == InterviewerDecisionType.PRESENT_QUESTION:
            if any(value is None for value in question_fields):
                raise ValueError("present_question decisions require complete question context")
        elif any(value is not None for value in question_fields):
            raise ValueError("non-question decisions cannot include question context")
        return self


class InterviewerAgent:
    """Decision/context-only agent; it has no persistence or execution authority."""

    def __init__(self, provider: InterviewerProvider) -> None:
        self._provider = provider

    def decide(self, assessment_state: AssessmentState | object) -> InterviewerDecision:
        try:
            assessment = validate_assessment_state(assessment_state)
        except ValueError as exc:
            raise InterviewerAgentError("interviewer requires a valid AssessmentState") from exc

        if assessment.assessment_status != InterviewStatus.ACTIVE:
            return InterviewerDecision(
                decision_type=InterviewerDecisionType.ASSESSMENT_CLOSED,
                reason=f"Assessment is {assessment.assessment_status} and cannot present a question.",
                interviewer_message="This assessment is no longer active.",
            )
        if not assessment.assigned_questions:
            return InterviewerDecision(
                decision_type=InterviewerDecisionType.NO_ASSIGNED_QUESTIONS,
                reason="The active assessment has no assigned questions.",
            )
        if assessment.current_question_id is None:
            return InterviewerDecision(
                decision_type=InterviewerDecisionType.ALL_QUESTIONS_ATTEMPTED,
                reason="All assigned questions have at least one submission attempt.",
            )

        try:
            provider_output = self._provider.select_question(assessment)
            selection = InterviewerProviderSelection.model_validate(provider_output)
        except (TypeError, ValidationError, ValueError) as exc:
            raise InterviewerAgentError("provider returned an invalid question selection") from exc
        assigned_by_id = {
            question.question_id: (index, question)
            for index, question in enumerate(assessment.assigned_questions)
        }
        selected = assigned_by_id.get(selection.selected_question_id)
        if selected is None:
            raise InterviewerAgentError("provider selected a question outside this assessment")
        if selection.selected_question_id != assessment.current_question_id:
            raise InterviewerAgentError("provider selected a question other than the current question")

        question_index, question = selected
        return InterviewerDecision(
            decision_type=InterviewerDecisionType.PRESENT_QUESTION,
            question_id=question.question_id,
            question_sequence_number=question.sequence_number,
            question_index=question_index,
            question_title=question.title,
            question_prompt=question.description,
            reason=selection.reason,
            interviewer_message=selection.interviewer_message,
        )
