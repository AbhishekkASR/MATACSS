"""Authentication endpoints for secure API access."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import create_access_token, get_current_active_user
from app.models.user import User
from app.schemas.auth import TokenResponse, UserCreateRequest, UserLoginRequest, UserResponse
from app.services.auth_service import (
    InvalidCredentialsError,
    UserAlreadyExistsError,
    authenticate_user,
    create_candidate_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user_route(
    request: UserCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    try:
        user, _candidate = await create_candidate_user(
            session,
            name=request.name,
            email=request.email,
            password=request.password,
            role=request.role,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        ) from exc
    return UserResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        active=user.active,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login_route(
    request: UserLoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    try:
        user = await authenticate_user(session, request.email, request.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from exc
    expires_delta = timedelta(minutes=settings.jwt_expire_minutes)
    token = create_access_token(user.id, user.role, expires_delta=expires_delta)
    return TokenResponse(access_token=token, expires_in=int(expires_delta.total_seconds()))


@router.get("/me", response_model=UserResponse)
async def current_user_route(
    current_user: User | None = Depends(get_current_active_user),
) -> UserResponse:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    return UserResponse(
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        active=current_user.active,
        created_at=current_user.created_at,
    )
