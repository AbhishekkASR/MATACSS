"""Authentication and user-management services."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole


class UserAlreadyExistsError(Exception):
    """Raised when a user attempts to register an existing email."""


class InvalidCredentialsError(Exception):
    """Raised when login credentials are invalid."""


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower()))


async def create_user(
    session: AsyncSession,
    email: str,
    password: str,
    role: UserRole | str = UserRole.CANDIDATE,
    active: bool = True,
) -> User:
    normalized_email = email.strip().lower()
    existing = await get_user_by_email(session, normalized_email)
    if existing is not None:
        raise UserAlreadyExistsError
    user = User(
        email=normalized_email,
        password_hash=get_password_hash(password),
        role=role.value if isinstance(role, UserRole) else str(role),
        active=active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def link_candidate_to_user(
    session: AsyncSession,
    candidate: Candidate,
    user: User,
) -> Candidate:
    candidate.user_id = user.id
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return candidate


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None or not user.active or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError
    return user


async def create_candidate_user(
    session: AsyncSession,
    name: str,
    email: str,
    password: str,
    role: UserRole | str = UserRole.CANDIDATE,
) -> tuple[User, Candidate]:
    user = await create_user(session, email, password, role=role)
    candidate = Candidate(name=name, email=email, user_id=user.id)
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    return user, candidate
