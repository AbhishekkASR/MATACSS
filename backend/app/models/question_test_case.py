"""Deterministic test cases for coding questions."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.question import Question


class QuestionTestCase(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One authoritative stdin/expected-output test case."""

    __tablename__ = "question_test_cases"

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stdin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_stdout: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_ms: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    question: Mapped[Question] = relationship(back_populates="test_cases")
