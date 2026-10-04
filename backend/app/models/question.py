"""Question persistence model."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.interview_question import InterviewQuestion
    from app.models.question_llm_lineage import QuestionLlmLineage
    from app.models.question_provenance import QuestionProvenance
    from app.models.question_test_case import QuestionTestCase
    from app.models.submission import Submission


class QuestionStatus(StrEnum):
    """Allowed Question Bank lifecycle states."""

    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class Question(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Question presented during an interview."""

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'active', 'deprecated')",
            name="ck_questions_status",
        ),
    )

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    difficulty: Mapped[str] = mapped_column(nullable=False)
    expected_language: Mapped[str | None] = mapped_column()

    # ── Question Bank metadata (added by migration 006) ──────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=QuestionStatus.DRAFT
    )
    input_format: Mapped[str | None] = mapped_column(Text)
    output_format: Mapped[str | None] = mapped_column(Text)
    constraints_text: Mapped[str | None] = mapped_column(Text)
    supported_languages: Mapped[list[str] | None] = mapped_column(JSON)
    starter_code: Mapped[str | None] = mapped_column(Text)

    # ── relationships ─────────────────────────────────────────────────────────
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    interview_assignments: Mapped[list[InterviewQuestion]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    test_cases: Mapped[list[QuestionTestCase]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )
    provenance: Mapped[QuestionProvenance | None] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        uselist=False,
    )
    llm_lineage: Mapped[QuestionLlmLineage | None] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="QuestionLlmLineage.question_id",
    )
