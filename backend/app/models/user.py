"""Authenticated application users and access roles."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.candidate import Candidate


class UserRole(StrEnum):
    """Access roles supported by the platform."""

    CANDIDATE = "candidate"
    INTERVIEWER = "interviewer"
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Authentication record for a user identity."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.CANDIDATE)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    candidates: Mapped[list[Candidate]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
