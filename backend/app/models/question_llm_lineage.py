"""LLM generation and adaptation lineage for questions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.question import Question


class QuestionLlmLineage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """LLM origin metadata for generated or adapted questions.

    For curated (dataset) questions: origin='curated', all other fields NULL.
    For generated questions: origin='generated', model and timestamp populated.
    For adapted questions: origin='adapted', parent_question_id populated.
    """

    __tablename__ = "question_llm_lineage"
    __table_args__ = (
        UniqueConstraint("question_id", name="uq_question_llm_lineage_question_id"),
    )

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    generation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL", name="fk_question_llm_lineage_parent"),
        nullable=True,
    )
    generation_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    question: Mapped[Question] = relationship(
        back_populates="llm_lineage",
        foreign_keys="QuestionLlmLineage.question_id",
    )
