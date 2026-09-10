"""Schemas for code submission requests and responses."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from uuid import UUID

from app.schemas.execution import ExecutionStatus

SUPPORTED_LANGUAGES = frozenset({"python", "cpp", "java"})


class CodeSubmissionRequest(BaseModel):
    """Request payload for a submission in an interview context."""

    interview_session_id: UUID
    question_id: UUID
    language: str = Field(..., description="Programming language of the source code.")
    source_code: str = Field(..., description="Source code to submit.")
    stdin: str = Field(
        default="",
        description="Optional standard input for the future execution.",
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        """Require a supported, non-empty language identifier."""
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("language must not be empty")
        if normalized not in SUPPORTED_LANGUAGES:
            supported = ", ".join(sorted(SUPPORTED_LANGUAGES))
            raise ValueError(f"unsupported language; supported languages: {supported}")
        return normalized

    @field_validator("source_code")
    @classmethod
    def validate_source_code(cls, value: str) -> str:
        """Require source code content."""
        if not value.strip():
            raise ValueError("source_code must not be empty")
        return value


class CodeSubmissionResponse(BaseModel):
    """Public response containing the submission and execution outcome."""

    submission_id: str
    job_id: str
    job_status: str
    interview_session_id: UUID
    question_id: UUID
    status: ExecutionStatus
    message: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    execution_time_ms: float | None = Field(default=None, ge=0)
    timed_out: bool = False


class SubmissionAttemptResponse(BaseModel):
    """Public assessment data for one persisted submission attempt."""

    submission_id: str
    question_id: UUID
    language: str
    source_code: str
    stdin: str
    status: ExecutionStatus
    stdout: str
    stderr: str
    exit_code: int | None
    execution_time_ms: float | None
    timed_out: bool
    created_at: datetime


class SubmissionStatusResponse(BaseModel):
    submission_id: UUID
    job_id: UUID
    job_status: str
    submission_status: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    execution_time_ms: float | None = None
    timed_out: bool | None = None


class EvaluationCaseResponse(BaseModel):
    test_case_id: UUID
    description: str | None
    passed: bool
    status: ExecutionStatus
    stdout: str
    stderr: str


class EvaluationResponse(BaseModel):
    submission_id: UUID
    evaluation_result_id: UUID
    status: str
    total_test_cases: int
    passed_test_cases: int
    failed_test_cases: int
    score: float | None
    test_cases: list[EvaluationCaseResponse]
    created_at: datetime