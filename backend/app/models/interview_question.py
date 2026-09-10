"""Interview question assignment persistence model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.interview import InterviewSession
    from app.models.question import Question


class InterviewQuestion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Ordered assignment of a question to one interview session."""

    __tablename__ = "interview_questions"
    __table_args__ = (
        UniqueConstraint(
            "interview_session_id",
            "question_id",
            name="uq_interview_questions_session_question",
        ),
        UniqueConstraint(
            "interview_session_id",
            "sequence_number",
            name="uq_interview_questions_session_sequence",
        ),
    )

    interview_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    interview_session: Mapped[InterviewSession] = relationship(
        back_populates="question_assignments"
    )
    question: Mapped[Question] = relationship(back_populates="interview_assignments")
