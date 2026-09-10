"""Interview session persistence model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.interview_question import InterviewQuestion
    from app.models.submission import Submission


class InterviewStatus(StrEnum):
    """Deterministic states for an interview assessment."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InterviewSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Interview session belonging to a candidate."""

    __tablename__ = "interview_sessions"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(nullable=False, default=InterviewStatus.ACTIVE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate: Mapped[Candidate] = relationship(back_populates="interview_sessions")
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="interview_session", cascade="all, delete-orphan"
    )
    question_assignments: Mapped[list[InterviewQuestion]] = relationship(
        back_populates="interview_session", cascade="all, delete-orphan"
    )
