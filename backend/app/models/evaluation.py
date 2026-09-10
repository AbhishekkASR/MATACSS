"""Persisted deterministic evaluation results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Integer, Float, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.submission import Submission


class EvaluationResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Idempotent evaluation summary and sanitized per-case details."""

    __tablename__ = "evaluation_results"

    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    total_test_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_test_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_test_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(nullable=False)
    case_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    submission: Mapped[Submission] = relationship(back_populates="evaluation_result")
