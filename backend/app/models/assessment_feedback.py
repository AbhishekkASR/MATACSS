"""Persisted advisory feedback generated for one submission."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AssessmentFeedback(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Idempotent LLM feedback, stored separately from the official evaluation."""

    __tablename__ = "assessment_feedback"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_assessment_feedback_status",
        ),
    )

    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_kind: Mapped[str | None] = mapped_column(String(40))
    interviewer_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reviewer_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    edge_case_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    aggregated_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
