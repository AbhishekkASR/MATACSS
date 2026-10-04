"""Question provenance — source, platform, and dataset metadata."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.question import Question


class QuestionProvenance(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Dataset source, platform origin, and license metadata for one question."""

    __tablename__ = "question_provenance"
    __table_args__ = (
        UniqueConstraint("question_id", name="uq_question_provenance_question_id"),
    )

    question_id: Mapped[UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(30))
    original_question_id: Mapped[str | None] = mapped_column(String(100))
    contest_id: Mapped[str | None] = mapped_column(String(100))
    contest_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(Text)
    dataset_name: Mapped[str | None] = mapped_column(String(100))
    dataset_version: Mapped[str | None] = mapped_column(String(100))

    question: Mapped[Question] = relationship(back_populates="provenance")
