"""Question persistence model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.interview_question import InterviewQuestion
    from app.models.question_test_case import QuestionTestCase
    from app.models.submission import Submission


class Question(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Question presented during an interview."""

    __tablename__ = "questions"

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    difficulty: Mapped[str] = mapped_column(nullable=False)
    expected_language: Mapped[str | None] = mapped_column()
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    interview_assignments: Mapped[list[InterviewQuestion]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    test_cases: Mapped[list[QuestionTestCase]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
