"""Schemas for deterministic assessment-level results."""

from uuid import UUID

from pydantic import BaseModel

from app.models.interview import InterviewStatus


class QuestionResultResponse(BaseModel):
    question_id: UUID
    sequence_number: int
    title: str
    difficulty: str
    latest_submission_id: UUID | None
    latest_submission_status: str | None
    evaluation_status: str
    score: float | None
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
