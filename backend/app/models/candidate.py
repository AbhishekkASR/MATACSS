"""Candidate persistence model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.interview import InterviewSession
    from app.models.user import User


class Candidate(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Candidate who participates in interview sessions."""

    __tablename__ = "candidates"

    name: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user: Mapped[User | None] = relationship(back_populates="candidates")
    interview_sessions: Mapped[list[InterviewSession]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
