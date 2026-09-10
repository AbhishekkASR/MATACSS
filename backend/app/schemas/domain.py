"""API schemas for candidates, interview sessions, and questions."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from app.models.interview import InterviewStatus

DIFFICULTIES = frozenset({"easy", "medium", "hard"})
QUESTION_LANGUAGES = frozenset({"python", "cpp", "java"})


def non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


class CandidateCreateRequest(BaseModel):
    name: str
    email: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return non_empty(value, "name")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = non_empty(value, "email").lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email must be valid")
        local, domain = normalized.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must be valid")
        return normalized


class CandidateResponse(BaseModel):
    candidate_id: UUID
    name: str
    email: str
    created_at: datetime


class InterviewCreateRequest(BaseModel):
    candidate_id: UUID


class InterviewResponse(BaseModel):
    interview_session_id: UUID
    candidate_id: UUID
    status: InterviewStatus
    started_at: datetime | None
    created_at: datetime
    completed_at: datetime | None = None


class InterviewProgressResponse(InterviewResponse):
    """Interview state and deterministic submission progress."""

    total_questions: int
    submitted_questions: int
    attempted_questions: int
    submission_count: int


class InterviewQuestionAssignmentRequest(BaseModel):
    question_id: UUID
    sequence_number: int = Field(gt=0)


class InterviewQuestionBulkAssignmentRequest(BaseModel):
    questions: list[InterviewQuestionAssignmentRequest] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def validate_unique_assignments(
        cls, value: list[InterviewQuestionAssignmentRequest]
    ) -> list[InterviewQuestionAssignmentRequest]:
        question_ids = [item.question_id for item in value]
        sequence_numbers = [item.sequence_number for item in value]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError("questions must not contain duplicate question_id values")
        if len(set(sequence_numbers)) != len(sequence_numbers):
            raise ValueError("questions must not contain duplicate sequence_number values")
        return value


class InterviewQuestionResponse(BaseModel):
    question_id: UUID
    sequence_number: int
    title: str
    description: str
    difficulty: str
    expected_language: str | None
    created_at: datetime


class QuestionCreateRequest(BaseModel):
    title: str
    description: str
    difficulty: str
    expected_language: str

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str, info) -> str:
        return non_empty(value, info.field_name)

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        normalized = non_empty(value, "difficulty").lower()
        if normalized not in DIFFICULTIES:
            raise ValueError("difficulty must be one of: easy, medium, hard")
        return normalized

    @field_validator("expected_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        normalized = non_empty(value, "expected_language").lower()
        if normalized not in QUESTION_LANGUAGES:
            raise ValueError("expected_language must be one of: python, cpp, java")
        return normalized


class QuestionResponse(BaseModel):
    question_id: UUID
    title: str
    description: str
    difficulty: str
    expected_language: str | None
    created_at: datetime


class QuestionTestCaseCreateRequest(BaseModel):
    stdin: str = ""
    expected_stdout: str
    time_limit_ms: int | None = Field(default=None, gt=0)
    description: str | None = None


class QuestionTestCaseResponse(BaseModel):
    test_case_id: UUID
    question_id: UUID
    stdin: str
    expected_stdout: str
    time_limit_ms: int | None
    description: str | None
    created_at: datetime
