"""Typed deterministic coordination contract for the assessment agents."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.interview import InterviewStatus
from app.orchestration.code_reviewer import CodeReviewResult
from app.orchestration.edge_case_generator import EdgeCaseGenerationResult
from app.orchestration.interviewer import InterviewerDecision
from app.schemas.assessment_state import AssessmentState


class AgentExecutionStatus(StrEnum):
    NOT_RUN = "not_run"
    COMPLETED = "completed"


class OrchestrationStatus(StrEnum):
    COMPLETED = "completed"
    ASSESSMENT_CLOSED = "assessment_closed"


class AgentExecutionInfo(BaseModel):
    """Bounded execution status for each agent in the workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    interviewer: AgentExecutionStatus
    code_reviewer: AgentExecutionStatus
    edge_case_generator: AgentExecutionStatus


class MultiAgentOrchestrationState(BaseModel):
    """Typed handoff state kept separate from the authoritative assessment state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_state: AssessmentState
    interviewer_decision: InterviewerDecision | None = None
    code_review: CodeReviewResult | None = None
    edge_case_generation: EdgeCaseGenerationResult | None = None
    execution: AgentExecutionInfo | None = None
    status: OrchestrationStatus | None = None


class MultiAgentOrchestrationResult(BaseModel):
    """Final safe result of one deterministic multi-agent graph invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_state: AssessmentState
    interviewer_decision: InterviewerDecision
    code_review: CodeReviewResult | None = None
    edge_case_generation: EdgeCaseGenerationResult | None = None
    execution: AgentExecutionInfo
    status: OrchestrationStatus
    reason: str = Field(min_length=1, max_length=500)

    @classmethod
    def from_agents(
        cls,
        assessment_state: AssessmentState,
        interviewer_decision: InterviewerDecision,
        code_review: CodeReviewResult | None,
        edge_case_generation: EdgeCaseGenerationResult | None,
    ) -> "MultiAgentOrchestrationResult":
        closed = assessment_state.assessment_status != InterviewStatus.ACTIVE
        return cls(
            assessment_state=assessment_state,
            interviewer_decision=interviewer_decision,
            code_review=code_review,
            edge_case_generation=edge_case_generation,
            execution=AgentExecutionInfo(
                interviewer=AgentExecutionStatus.COMPLETED,
                code_reviewer=(
                    AgentExecutionStatus.COMPLETED
                    if code_review is not None and code_review.review_status != "not_run"
                    else AgentExecutionStatus.NOT_RUN
                ),
                edge_case_generator=(
                    AgentExecutionStatus.COMPLETED
                    if edge_case_generation is not None and edge_case_generation.question_id is not None
                    else AgentExecutionStatus.NOT_RUN
                ),
            ),
            status=(
                OrchestrationStatus.ASSESSMENT_CLOSED
                if closed
                else OrchestrationStatus.COMPLETED
            ),
            reason=(
                f"Assessment is {assessment_state.assessment_status}."
                if closed
                else "Interviewer, Code Reviewer, and Edge-Case Generator completed their safe handoffs."
            ),
        )
