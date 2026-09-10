"""Submission persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evaluation import EvaluationResult
    from app.models.execution_job import ExecutionJob
    from app.models.interview import InterviewSession
    from app.models.question import Question


class Submission(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Candidate source and sanitized execution result."""

    __tablename__ = "submissions"

    interview_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(nullable=False)
    source_code: Mapped[str] = mapped_column(nullable=False)
    stdin: Mapped[str] = mapped_column(nullable=False, default="")
    status: Mapped[str] = mapped_column(nullable=False, default="accepted")
    stdout: Mapped[str] = mapped_column(nullable=False, default="")
    stderr: Mapped[str] = mapped_column(nullable=False, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    execution_time_ms: Mapped[float | None] = mapped_column()
    timed_out: Mapped[bool] = mapped_column(nullable=False, default=False)
    interview_session: Mapped[InterviewSession] = relationship(
        back_populates="submissions"
    )
    question: Mapped[Question] = relationship(back_populates="submissions")
    evaluation_result: Mapped[EvaluationResult | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )
    execution_job: Mapped[ExecutionJob | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )
