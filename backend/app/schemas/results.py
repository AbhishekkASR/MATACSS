"""Schemas for deterministic assessment-level results."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.interview import InterviewStatus
from app.orchestration.code_reviewer import CodeReviewResult
from app.orchestration.edge_case_generator import EdgeCaseGenerationResult
from app.orchestration.feedback_aggregator import FeedbackAggregationResult
from app.orchestration.interviewer import InterviewerDecision


class AssessmentFeedbackReportResponse(BaseModel):
    """Saved advisory agent report, intentionally separate from official scoring."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "completed", "failed"]
    failure_kind: Literal[
        "provider_error", "context_error", "orchestration_error"
    ] | None = None
    is_advisory: Literal[True] = True
    interviewer: InterviewerDecision | None = None
    reviewer: CodeReviewResult | None = None
    edge_cases: EdgeCaseGenerationResult | None = None
    aggregated: FeedbackAggregationResult | None = None


class AgentFeedbackResponse(BaseModel):
    """Saved, advisory agent feedback for one evaluated submission."""

    model_config = ConfigDict(extra="forbid")

    submission_id: UUID
    status: Literal["completed", "failed"]
    interviewer_decision: InterviewerDecision | None = None
    code_review: CodeReviewResult | None = None
    edge_case_generation: EdgeCaseGenerationResult | None = None
    feedback: FeedbackAggregationResult | None = None
    failure_kind: Literal[
        "provider_error", "context_error", "orchestration_error"
    ] | None = None
    created_at: datetime


class QuestionResultResponse(BaseModel):
    question_id: UUID
    sequence_number: int
    title: str
    difficulty: str
    latest_submission_id: UUID | None
    latest_submission_status: str | None
    evaluation_status: str
    score: float | None
    ai_feedback: AssessmentFeedbackReportResponse | None = Field(
        default=None,
        description="Advisory AI feedback; the separate score field is the official deterministic score.",
    )
    passed_test_cases: int
    total_test_cases: int


class AssessmentResultsResponse(BaseModel):
    interview_session_id: UUID
    interview_status: InterviewStatus
    total_questions: int
    attempted_questions: int
    evaluated_questions: int
    total_passed_test_cases: int
    total_test_cases: int
    overall_score: float | None
    status: str
    questions: list[QuestionResultResponse]
    agent_feedback: list[AgentFeedbackResponse] | None = None
